"""
auto_repair_matches.py
======================
Orquestador autónomo que repara todos los `match_detail` con team_id NULL.

Integra en UN solo proceso lo que antes hacían: watchdog_loop.sh +
start_driver.py + fix_null_team_ids.py + intervención manual.

QUÉ HACE
--------
1. Descubre desde la DB todas las ligas que tienen matches con team_id NULL.
2. Asegura un driver Selenium vivo (lanza start_driver.py si no hay sesión).
3. Procesa liga por liga llamando a `fix_null_team_ids()` (reusa toda la
   lógica ya validada de extracción/creación de teams).
4. Entre ligas: verifica salud del driver (memoria + responsividad). Si el
   driver está degradado, lo recicla (kill + relaunch + login).
5. Persiste un skip-set para ligas irresolubles (todas las iteraciones
   fallaron) — no las reintenta indefinidamente.
6. Repite hasta que NULL=0 o no haya progreso entre iteraciones.

LOGS
----
- logs/auto_repair/auto_repair_YYYYMMDD_HHMM.log  — log principal del orquestador
- logs/auto_repair/per_league/<league_id>.log     — log detallado por liga
- logs/auto_repair/stats.json                     — stats acumulados por liga
- tmp/auto_repair_skip.json                       — ligas marcadas como irresolubles
- tmp/problems/<league_id>.json                   — matches que no se pudieron
                                                    reparar (lo escribe fix_null_team_ids)

REGLAS DE DRIVER (sagradas, ver docs/DRIVER_RULES.md)
-----------------------------------------------------
- Si hay session válida, se reusa (NO se lanza segundo driver).
- Reciclo del driver = kill start_driver.py + geckodriver + firefox + relaunch.
  Nunca se dejan dos drivers vivos en paralelo.

REGLA DE DB (sagrada, ver CLAUDE.md)
------------------------------------
- Solo INSERT/UPDATE. JAMÁS DELETE/DROP/TRUNCATE.

USO
---
    # ejecución dry-run (solo reporta)
    python scripts/auto_repair_matches.py

    # ejecución real (escribe en DB)
    python scripts/auto_repair_matches.py --apply

    # con skip extra de ligas conocidas problemáticas
    python scripts/auto_repair_matches.py --apply \\
        --skip "AM._FOOTBALL/CANADA_CFL" \\
        --skip "FOOTBALL/COSTA RICA_Primera Division" \\
        --skip "FOOTBALL/ECUADOR_Liga Pro"

    # timeout por liga (default 25 min)
    python scripts/auto_repair_matches.py --apply --league-timeout 1500

    # background con nohup
    nohup python -u scripts/auto_repair_matches.py --apply \\
        > logs/auto_repair/stdout.log 2>&1 &
    disown
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import datetime
from contextlib import contextmanager

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from data_base import getdb

# ─── Paths ─────────────────────────────────────────────────────────────────
DRIVER_SESSION_PATH = os.path.join(ROOT, 'tmp', 'driver_session.json')
SKIP_SET_PATH       = os.path.join(ROOT, 'tmp', 'auto_repair_skip.json')
LOGS_DIR            = os.path.join(ROOT, 'logs', 'auto_repair')
PER_LEAGUE_DIR      = os.path.join(LOGS_DIR, 'per_league')
STATS_PATH          = os.path.join(LOGS_DIR, 'stats.json')
START_DRIVER_PY     = os.path.join(ROOT, 'scripts', 'start_driver.py')
PY_BIN              = os.path.join(ROOT, 'env_sports', 'bin', 'python')

# ─── Umbrales ──────────────────────────────────────────────────────────────
MEM_RECYCLE_MB       = 300    # < esto → reciclar driver entre ligas
MEM_CRITICAL_MB      = 200    # < esto → reciclar AHORA (mid-league)
DRIVER_LAUNCH_TIMEOUT = 120   # segundos para esperar "Sesión guardada"
DEFAULT_LEAGUE_TIMEOUT = 1500  # 25 min por liga


# ───────────────────────────────────────────────────────────────────────────
# Logging
# ───────────────────────────────────────────────────────────────────────────

class Logger:
    """Logger simple con timestamp, escribe a stdout + archivo."""

    def __init__(self, log_path):
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.fp = open(log_path, 'a', buffering=1)  # line-buffered
        self.path = log_path

    def __call__(self, msg, level='INFO'):
        line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {msg}"
        print(line, flush=True)
        self.fp.write(line + '\n')

    def close(self):
        try:
            self.fp.close()
        except Exception:
            pass


# ───────────────────────────────────────────────────────────────────────────
# Skip set persistente
# ───────────────────────────────────────────────────────────────────────────

def load_skip_set():
    """Lee tmp/auto_repair_skip.json → set de claves 'SPORT_KEY/LEAGUE_KEY'."""
    if not os.path.isfile(SKIP_SET_PATH):
        return set()
    with open(SKIP_SET_PATH) as f:
        data = json.load(f)
    return set(data.get('skip', []))


def save_skip_set(skip_set, reasons=None):
    """Persiste skip-set + razones por liga."""
    os.makedirs(os.path.dirname(SKIP_SET_PATH), exist_ok=True)
    payload = {
        'skip': sorted(skip_set),
        'reasons': reasons or {},
        'updated_at': datetime.datetime.utcnow().isoformat(timespec='seconds'),
    }
    with open(SKIP_SET_PATH, 'w') as f:
        json.dump(payload, f, indent=2)


# ───────────────────────────────────────────────────────────────────────────
# Stats acumulados
# ───────────────────────────────────────────────────────────────────────────

def load_stats():
    if not os.path.isfile(STATS_PATH):
        return {'iterations': [], 'by_league': {}}
    with open(STATS_PATH) as f:
        return json.load(f)


def save_stats(stats):
    os.makedirs(os.path.dirname(STATS_PATH), exist_ok=True)
    with open(STATS_PATH, 'w') as f:
        json.dump(stats, f, indent=2, default=str)


# ───────────────────────────────────────────────────────────────────────────
# Helpers de sistema
# ───────────────────────────────────────────────────────────────────────────

def mem_available_mb():
    """Memoria disponible en MB (campo 'available' de free -m)."""
    out = subprocess.check_output(['free', '-m']).decode()
    for line in out.splitlines():
        if line.startswith('Mem:'):
            return int(line.split()[6])
    return -1


def count_null_in_db():
    """SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL."""
    con = getdb()
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")
        return cur.fetchone()[0]
    finally:
        con.close()


def discover_problem_leagues():
    """
    DISTINCT (sport_key, league_key, league_id, count) de todas las ligas
    que tienen al menos un match con team_id NULL en match_detail.

    Mapea sport_id+league_name → sport_key/league_key usando leagues_info.json.

    Returns:
        list de dicts ordenados por cantidad DESC.
    """
    con = getdb()
    try:
        cur = con.cursor()
        cur.execute("""
            SELECT l.league_id,
                   s.name AS sport_name,
                   l.league_name,
                   c.country_name,
                   COUNT(DISTINCT m.match_id) AS null_matches
              FROM match m
              JOIN match_detail md ON md.match_id = m.match_id
              JOIN league l ON l.league_id = m.league_id
              JOIN sport  s ON s.sport_id  = l.sport_id
              LEFT JOIN country c ON c.country_id = l.country_id
             WHERE md.team_id IS NULL
             GROUP BY l.league_id, s.name, l.league_name, c.country_name
             ORDER BY null_matches DESC
        """)
        rows = cur.fetchall()
    finally:
        con.close()

    # Mapear a SPORT_KEY/LEAGUE_KEY de leagues_info.json
    from common_functions import load_json
    leagues_info = load_json('check_points/leagues_info.json')

    result = []
    for league_id, sport_name, league_name, country_name, n in rows:
        sport_key, league_key = _resolve_league_key(
            leagues_info, sport_name, country_name, league_name, league_id,
        )
        result.append({
            'league_id':    league_id,
            'sport_name':   sport_name,
            'country_name': country_name,
            'league_name':  league_name,
            'null_matches': n,
            'sport_key':    sport_key,
            'league_key':   league_key,
            'resolved':     bool(sport_key and league_key),
        })
    return result


def _resolve_league_key(leagues_info, sport_name, country_name, league_name, league_id):
    """
    Encuentra (sport_key, league_key) en leagues_info.json a partir de los
    datos de DB. Match exacto por league_id si está en el JSON.

    Returns (sport_key, league_key) o (None, None) si no se resuelve.
    """
    for sk, ligas in leagues_info.items():
        for lk, info in ligas.items():
            if info.get('league_id') == league_id:
                return sk, lk
    return None, None


# ───────────────────────────────────────────────────────────────────────────
# Gestión del driver
# ───────────────────────────────────────────────────────────────────────────

def driver_session_valid():
    """True si tmp/driver_session.json existe y la session responde."""
    if not os.path.isfile(DRIVER_SESSION_PATH):
        return False
    try:
        from fix_null_team_ids import _reuse_driver_session
        d = _reuse_driver_session()
        if d is None:
            return False
        # _reuse_driver_session ya verificó current_url
        return True
    except Exception:
        return False


def start_driver_pids():
    """PIDs de start_driver.py corriendo."""
    out = subprocess.run(
        ['pgrep', '-f', 'start_driver.py'],
        capture_output=True, text=True,
    )
    return [int(p) for p in out.stdout.split() if p.strip()]


def launch_driver(log):
    """Lanza start_driver.py detached y espera login (max DRIVER_LAUNCH_TIMEOUT)."""
    log("Lanzando start_driver.py …")
    log_path = os.path.join(
        LOGS_DIR,
        f"start_driver_{datetime.datetime.now():%Y%m%d_%H%M%S}.log",
    )
    with open(log_path, 'w') as lf:
        subprocess.Popen(
            [PY_BIN, '-u', START_DRIVER_PY],
            stdout=lf, stderr=lf,
            start_new_session=True,
            cwd=ROOT,
        )
    # Esperar "Sesión guardada"
    waited = 0
    while waited < DRIVER_LAUNCH_TIMEOUT:
        time.sleep(3)
        waited += 3
        try:
            with open(log_path) as f:
                if 'Sesión guardada' in f.read():
                    log(f"  driver listo en {waited}s — log: {log_path}")
                    return True
        except Exception:
            pass
    log(f"  ERROR: driver no logueó en {DRIVER_LAUNCH_TIMEOUT}s (log: {log_path})",
        level='ERROR')
    return False


def kill_existing_driver(log):
    """Mata SOLO procesos del driver del scraping. Identificadores seguros:
      - start_driver.py        → script launcher
      - geckodriver            → driver de Selenium
      - rust_mozprofile        → perfil temporal de Selenium (este firefox sí)
    NUNCA usar pkill firefox-bin → mataría el Firefox personal del usuario.
    """
    pids = start_driver_pids()
    log(f"Matando driver del scraping: start_driver pids={pids}")
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    subprocess.run(['pkill', '-9', '-f', 'geckodriver'])
    # Filtro por mozprofile: SOLO Firefox lanzado por Selenium tiene este perfil.
    # Esto NO afecta a tu Firefox personal/regular del sistema.
    subprocess.run(['pkill', '-9', '-f', 'rust_mozprofile'])
    time.sleep(3)


def recycle_driver(log, reason):
    """kill + launch + verificación. Retorna True si quedó vivo."""
    log(f"RECICLANDO DRIVER — razón: {reason}", level='WARN')
    mem_before = mem_available_mb()
    kill_existing_driver(log)
    # eliminar JSON viejo para que la próxima reuse no apunte a sesión muerta
    try:
        os.remove(DRIVER_SESSION_PATH)
    except FileNotFoundError:
        pass
    ok = launch_driver(log)
    mem_after = mem_available_mb()
    log(f"  mem: {mem_before} MB → {mem_after} MB")
    return ok


def ensure_driver_healthy(log):
    """
    Asegura que el driver está vivo y la memoria es OK.

    Orden de checks (importante: session-first para no matar drivers
    detached funcionales que no tengan start_driver.py padre vivo):

    1. ¿Session responde a current_url?
       SÍ → solo reciclar si memoria <MEM_RECYCLE_MB.
       NO → continuar al paso 2.
    2. ¿Hay >1 start_driver.py corriendo? → matar huérfanos + relanzar.
    3. No hay driver usable → reciclar (mata viejos + relanza).
    """
    session_ok = driver_session_valid()
    if session_ok:
        mem = mem_available_mb()
        if mem < MEM_RECYCLE_MB:
            log(f"Session válida pero mem baja ({mem} MB < {MEM_RECYCLE_MB}) → reciclar")
            return recycle_driver(log, reason=f'low_memory_{mem}MB')
        return True  # todo OK, no tocar

    pids = start_driver_pids()
    if len(pids) > 1:
        log(f"DETECTADO {len(pids)} start_driver (huérfanos) → reciclar", level='WARN')
        return recycle_driver(log, reason='multiple_start_driver_pids')

    log("Session inválida y sin driver usable → lanzar uno nuevo", level='WARN')
    return recycle_driver(log, reason='no_driver_or_unresponsive_session')


# ───────────────────────────────────────────────────────────────────────────
# Ejecución por liga con timeout
# ───────────────────────────────────────────────────────────────────────────

class LeagueTimeout(Exception):
    pass


# Patrones que identifican errores transversales (DB caída, red, etc) — NO
# son fallos del scraping de la liga; reintentar sin penalizar consecutive_failures.
TRANSIENT_ERROR_PATTERNS = (
    'OperationalError',                   # psycopg2 connection issues
    'connection to server',               # postgres connect timeout
    'timeout expired',                    # postgres timeout
    'Connection refused',                 # postgres down
    'Could not connect',                  # network
    'Name or service not known',          # DNS
    'Temporary failure in name resolution', # DNS
    'Network is unreachable',
    'Read timed out',                     # selenium/requests timeout
)


def is_transient_error(stats_dict):
    """True si el error registrado en stats parece transversal (DB/red),
    no un fallo de scraping de esa liga."""
    err = (stats_dict or {}).get('error', '') or ''
    return any(pat in err for pat in TRANSIENT_ERROR_PATTERNS)


@contextmanager
def time_limit(seconds):
    """Context manager que lanza LeagueTimeout tras `seconds`."""
    def _handler(signum, frame):
        raise LeagueTimeout(f"timeout {seconds}s alcanzado")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def run_league(sport_key, league_key, dry_run, timeout, log):
    """
    Ejecuta `fix_null_team_ids()` para UNA liga, con timeout, capturando stats.

    Devuelve (stats_dict, status) donde status ∈ {'ok','timeout','error'}.
    """
    from fix_null_team_ids import fix_null_team_ids

    # Redirigir stdout a log per-league
    per_league_log = os.path.join(
        PER_LEAGUE_DIR,
        f"{sport_key}_{league_key}".replace('/', '_').replace(' ', '_') + '.log',
    )
    os.makedirs(PER_LEAGUE_DIR, exist_ok=True)

    log(f"  → ejecutando (timeout={timeout}s, log liga={per_league_log})")

    with open(per_league_log, 'a') as lf:
        lf.write(f"\n{'='*72}\n"
                 f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] "
                 f"START {sport_key}/{league_key} dry_run={dry_run}\n"
                 f"{'='*72}\n")
        lf.flush()

        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = lf
        try:
            with time_limit(timeout):
                stats = fix_null_team_ids(
                    dry_run=dry_run,
                    headless=False,
                    sport_keys=[(sport_key, league_key)],
                    reuse_driver=True,
                    keep_alive=True,
                ) or {}
            status = 'ok'
        except LeagueTimeout as e:
            stats = {'error': str(e)}
            status = 'timeout'
        except Exception as e:
            stats = {'error': f'{type(e).__name__}: {e}'}
            status = 'error'
            import traceback
            traceback.print_exc(file=lf)
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    return stats, status


# ───────────────────────────────────────────────────────────────────────────
# Loop principal
# ───────────────────────────────────────────────────────────────────────────

def auto_repair_loop(dry_run, extra_skip, league_timeout, max_iters, log):
    """
    Loop hasta NULL=0 o no haya progreso entre iteraciones consecutivas.

    Args:
        dry_run        : True → no escribe en DB.
        extra_skip     : set de claves 'SPORT_KEY/LEAGUE_KEY' a saltar.
        league_timeout : segundos máximos por liga.
        max_iters      : máximo de iteraciones del loop externo.
    """
    skip_reasons = {}
    skip_set = load_skip_set() | extra_skip
    accumulated_stats = load_stats()

    log(f"{'='*72}")
    log(f"AUTO REPAIR — dry_run={dry_run} timeout/liga={league_timeout}s")
    log(f"Skip set inicial ({len(skip_set)}): {sorted(skip_set)}")
    log(f"{'='*72}")

    null_history = [count_null_in_db()]
    log(f"NULL en DB al inicio: {null_history[0]}")

    for it in range(1, max_iters + 1):
        log(f"\n{'─'*72}")
        log(f"ITERACIÓN {it}/{max_iters}")
        log(f"{'─'*72}")

        leagues = discover_problem_leagues()
        # Filtrar resueltas y aplicar skip
        pending = []
        for lg in leagues:
            if not lg['resolved']:
                log(f"  [UNRESOLVED] {lg['sport_name']}/{lg['league_name']} "
                    f"({lg['null_matches']} NULL) no está en leagues_info.json",
                    level='WARN')
                continue
            key = f"{lg['sport_key']}/{lg['league_key']}"
            if key in skip_set:
                log(f"  [SKIP] {key} ({lg['null_matches']} NULL)")
                continue
            pending.append(lg)

        if not pending:
            log("No quedan ligas a procesar (todas skip o resueltas).")
            break

        log(f"\nLigas pendientes en esta iter: {len(pending)}")
        for lg in pending:
            log(f"  • {lg['sport_key']}/{lg['league_key']} — {lg['null_matches']} NULL")

        # Procesar liga por liga
        for lg in pending:
            key = f"{lg['sport_key']}/{lg['league_key']}"
            log(f"\n[LIGA] {key} ({lg['null_matches']} NULL)")

            if not ensure_driver_healthy(log):
                log("  no se pudo asegurar driver — abortando iteración", level='ERROR')
                break

            t0 = time.time()
            stats, status = run_league(
                lg['sport_key'], lg['league_key'],
                dry_run=dry_run, timeout=league_timeout, log=log,
            )
            elapsed = int(time.time() - t0)

            entry = accumulated_stats['by_league'].setdefault(key, {
                'runs': 0, 'fixed_total': 0, 'errors_total': 0,
                'last_status': '', 'last_run_at': '', 'consecutive_failures': 0,
            })
            entry['runs'] += 1
            entry['fixed_total'] += stats.get('matches_fixed', 0)
            entry['errors_total'] += stats.get('errors', 0)
            entry['last_status'] = status
            entry['last_run_at'] = datetime.datetime.utcnow().isoformat(timespec='seconds')

            log(f"  status={status} stats={stats} ({elapsed}s)")

            # Decisión sobre skip:
            #  - Error transversal (DB caída, red) → NO contar fallo; reintentar pronto.
            #  - timeout/error real → contar como fallo consecutivo.
            #  - completó pero 0 reparados y todos errores → contar como fallo.
            #  - 2+ fallos consecutivos → skip permanente.
            if status == 'error' and is_transient_error(stats):
                log(f"  → error transversal (DB/red), NO penaliza consecutive_failures. "
                    f"Pausa 30s antes de continuar.", level='WARN')
                time.sleep(30)
                # No incrementa consecutive_failures ni save_skip_set
                save_stats(accumulated_stats)
                continue

            failed = (
                status != 'ok'
                or (stats.get('matches_total', 0) > 0
                    and stats.get('matches_fixed', 0) == 0)
            )
            if failed:
                entry['consecutive_failures'] += 1
                if entry['consecutive_failures'] >= 2:
                    skip_set.add(key)
                    skip_reasons[key] = (
                        f"{entry['consecutive_failures']} fallos consecutivos; "
                        f"último status={status}"
                    )
                    log(f"  → SKIP permanente ({skip_reasons[key]})", level='WARN')
            else:
                entry['consecutive_failures'] = 0

            save_stats(accumulated_stats)
            save_skip_set(skip_set, skip_reasons)

            # Si memoria crítica mid-iteración, reciclar antes de la siguiente liga
            mem = mem_available_mb()
            if mem < MEM_CRITICAL_MB:
                log(f"  mem crítica ({mem} MB) → reciclar antes de próxima liga",
                    level='WARN')
                recycle_driver(log, reason=f'critical_low_memory_{mem}MB')

        # Fin iteración
        null_now = count_null_in_db()
        null_history.append(null_now)
        delta = null_history[-2] - null_now
        log(f"\n[ITER {it} DONE] NULL: {null_history[-2]} → {null_now} (Δ={-delta:+})")

        if null_now == 0:
            log("✓ NULL=0 — TODOS LOS MATCHES REPARADOS")
            break

        if delta <= 0:
            log("Sin progreso en esta iteración. Verificando si hay ligas no-skip "
                "que aún tengan NULL …")
            still = [lg for lg in discover_problem_leagues()
                     if lg['resolved']
                     and f"{lg['sport_key']}/{lg['league_key']}" not in skip_set]
            if not still:
                log("No quedan ligas no-skip — terminando.")
                break
            log(f"Quedan {len(still)} ligas pero todas con dificultades. "
                f"Reintenta próxima iter.")

    # Reporte final
    log(f"\n{'='*72}")
    log("REPORTE FINAL")
    log(f"{'='*72}")
    log(f"NULL inicial : {null_history[0]}")
    log(f"NULL final   : {null_history[-1]}")
    log(f"Reparados    : {null_history[0] - null_history[-1]}")
    log(f"Iteraciones  : {len(null_history) - 1}")
    log(f"Skip set     : {len(skip_set)} ligas")
    for k in sorted(skip_set):
        log(f"   • {k}  ({skip_reasons.get(k, 'preexistente')})")
    log(f"\nStats por liga → {STATS_PATH}")
    log(f"Skip set      → {SKIP_SET_PATH}")
    log(f"Logs por liga → {PER_LEAGUE_DIR}/")


# ───────────────────────────────────────────────────────────────────────────
# CLI
# ───────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--apply', action='store_true',
                   help='Escribe en DB (default: dry-run)')
    p.add_argument('--skip', action='append', default=[],
                   metavar='SPORT_KEY/LEAGUE_KEY',
                   help='Skip una liga (puede repetirse). Se acumula sobre '
                        'el skip-set persistente de tmp/auto_repair_skip.json')
    p.add_argument('--league-timeout', type=int, default=DEFAULT_LEAGUE_TIMEOUT,
                   metavar='SEG',
                   help=f'Segundos máximos por liga (default {DEFAULT_LEAGUE_TIMEOUT}s)')
    p.add_argument('--max-iters', type=int, default=5,
                   help='Máximo de pasadas sobre toda la queue (default 5)')
    p.add_argument('--reset-skip', action='store_true',
                   help='Vacía el skip-set persistente antes de empezar')
    args = p.parse_args()

    if args.reset_skip and os.path.isfile(SKIP_SET_PATH):
        os.remove(SKIP_SET_PATH)

    log_path = os.path.join(
        LOGS_DIR,
        f"auto_repair_{datetime.datetime.now():%Y%m%d_%H%M}.log",
    )
    log = Logger(log_path)

    try:
        auto_repair_loop(
            dry_run=not args.apply,
            extra_skip=set(args.skip),
            league_timeout=args.league_timeout,
            max_iters=args.max_iters,
            log=log,
        )
    except KeyboardInterrupt:
        log("Interrumpido por usuario (Ctrl+C)", level='WARN')
    finally:
        log("FIN")
        log.close()


if __name__ == '__main__':
    main()
