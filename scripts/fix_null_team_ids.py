"""
fix_null_team_ids.py
=====================
Cierra match_detail con team_id IS NULL navegando FlashScore para extraer
los URLs de cada equipo desde la pagina del match y crearlo en `team`
+ `league_team` reutilizando las funciones de milestone3.

FLUJO
-----
Por cada liga afectada:
  1) Detectar matches con al menos un match_detail.team_id IS NULL.
  2) Abrir la URL de results de la liga (de leagues_info.json).
  3) Cargar la pagina hacia atras hasta la fecha mas vieja afectada.
  4) scan_results_page() → mapea cada match (por nombre+fecha) a su URL de FlashScore.
  5) Por cada match:
       a) Navegar al match URL.
       b) Extraer los 2 team URLs con el selector NUEVO
          `participant__participantName` (FlashScore actualizo el HTML;
          milestone4.get_links_participants usa el viejo
          `participant__participantLink` que ya no existe).
       c) Por cada team URL, si el team no existe en `team`:
          - Navegar al team URL.
          - get_teams_info_part2() → extrae heading/breadcrumb/stadium/logo.
          - create_team_in_db() → INSERT a `team` + `league_team`.
       d) UPDATE match_detail para esa match_id: asignar el team_id correcto
          a la fila home / visitor segun corresponda.

USO
---
    python scripts/fix_null_team_ids.py                       # dry-run (default)
    python scripts/fix_null_team_ids.py --apply               # escribe en DB
    python scripts/fix_null_team_ids.py --league "WORLD_World Cup"  # filtra liga
    python scripts/fix_null_team_ids.py --headless            # driver headless

Driver por DEFAULT es visible (headless=False) para inspeccion manual.
"""

import sys, os, argparse, time, json, subprocess, socket
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium import webdriver

from data_base import (
    getdb, get_country_id, get_dict_league_ready, save_stadium_in_db,
    save_score_info, get_math_details_ids, get_score_by_match_detail_id,
)
from common_functions import (
    launch_navigator, login, dismiss_cookies, wait_update_page, load_json,
    generate_uuid,
)
from milestone3 import get_teams_info_part2, create_team_in_db
from milestone4 import get_statistics_game
from scripts.fix_live_matches import find_results_url, load_until_date, scan_results_page

from config import FS_EMAIL, FS_PASSWORD

FLASHSCORE_BASE       = 'https://www.flashscore.com'
LEAGUES_INFO_PATH     = 'check_points/leagues_info.json'
DRIVER_SESSION_PATH   = 'tmp/driver_session.json'
GECKODRIVER_BIN       = '/home/jorge/.cache/selenium/geckodriver/linux64/0.35.0/geckodriver'
SCAN_CACHE_DIR        = 'tmp/scan_cache'
PROBLEMS_DIR          = 'tmp/problems'

# Selecciones africanas (mantenido para retro-compatibilidad con --only-african).
# Si decidimos eliminarlo, también quitar el flag --only-african y la función is_african_match.
AFRICAN_NATIONS = {
    'Algeria', 'Angola', 'Benin', 'Botswana', 'Burkina Faso', 'Burundi',
    'Cameroon', 'Cape Verde', 'Central Africa', 'Chad', 'Comoros', 'Congo',
    'D.R. Congo', 'Djibouti', 'Egypt', 'Equatorial Guinea', 'Eritrea',
    'Eswatini', 'Ethiopia', 'Gabon', 'Gambia', 'Ghana', 'Guinea',
    'Guinea-Bissau', 'Ivory Coast', 'Kenya', 'Lesotho', 'Liberia', 'Libya',
    'Madagascar', 'Malawi', 'Mali', 'Mauritania', 'Mauritius', 'Morocco',
    'Mozambique', 'Namibia', 'Niger', 'Nigeria', 'Rwanda', 'Sao Tome and Principe',
    'Senegal', 'Seychelles', 'Sierra Leone', 'Somalia', 'South Africa',
    'South Sudan', 'Sudan', 'Tanzania', 'Togo', 'Tunisia', 'Uganda',
    'Zambia', 'Zimbabwe',
}


# ─── DRIVER: launch / reuse / save / NUNCA quit ─────────────────────────────

def _save_driver_session(driver, path=None):
    """Guarda session_id + executor_url para reuso externo."""
    path = path or DRIVER_SESSION_PATH
    try:
        executor_url = driver.command_executor._url
    except AttributeError:
        executor_url = driver.command_executor._client_config.remote_server_addr
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({
            'session_id':   driver.session_id,
            'executor_url': executor_url,
        }, f, indent=2)
    print(f"[OK] driver session guardada en {path}")


class _AttachRemote(webdriver.Remote):
    """webdriver.Remote que NO crea sesion nueva — se adjunta a una existente.

    El truco estandar es sobrescribir `start_session` con un no-op para que
    `__init__` no lance `POST /session`, y luego asignar `session_id` antes
    del primer comando.
    """
    def start_session(self, *args, **kwargs):
        return  # no crear sesion nueva


def _reuse_driver_session(path=None):
    """Conecta a un driver activo via session_id guardado. None si falla."""
    path = path or DRIVER_SESSION_PATH
    if not os.path.isfile(path):
        print(f"[WARN] no existe {path} — no se puede reusar driver")
        return None
    with open(path) as f:
        data = json.load(f)
    print(f"[REUSE] adjuntando a session_id={data['session_id']} "
          f"@ {data['executor_url']}")
    try:
        opts = webdriver.FirefoxOptions()
        driver = _AttachRemote(
            command_executor=data['executor_url'], options=opts,
        )
        driver.session_id = data['session_id']
        # Verificar que la sesion responde
        _ = driver.current_url
        print(f"[REUSE] OK — current_url: {driver.current_url}")
        return driver
    except Exception as e:
        print(f"[REUSE] FALLO: {e}")
        return None


def _free_port():
    """Devuelve un puerto TCP libre (kernel-assigned)."""
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def launch_detached_driver(url=FLASHSCORE_BASE, headless=False):
    """
    Lanza un driver Firefox+geckodriver DETACHED del proceso python actual.

    Truco: spawneo geckodriver con `subprocess.Popen(start_new_session=True)`
    para que quede en su propio process group y SOBREVIVA cuando python sale.
    Selenium estandar (launch_navigator/webdriver.Firefox(service=...)) lo
    spawnea como subprocess en el mismo PG, asi que muere con python.

    Returns:
        webdriver.Remote conectado al geckodriver detached.
    """
    port = _free_port()
    print(f"[DETACH] spawneando geckodriver detached en puerto {port}")
    subprocess.Popen(
        [GECKODRIVER_BIN, '--port', str(port)],
        start_new_session=True,        # <-- clave: setsid
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    # Esperar a que geckodriver acepte conexiones
    for _ in range(50):
        try:
            with socket.socket() as s:
                s.settimeout(0.3)
                s.connect(('localhost', port))
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError(f"geckodriver no arranco en puerto {port}")

    # Opciones Firefox identicas a launch_navigator
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--disable-infobars')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-browser-side-navigation')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--no-sandbox')
    if headless:
        print('[DETACH] mode headless')
        opts.add_argument('--headless')

    driver = webdriver.Remote(
        command_executor=f'http://localhost:{port}',
        options=opts,
    )
    driver.get(url)
    driver.execute_script("document.body.style.zoom='50%'")
    print(f"[DETACH] driver listo — session_id={driver.session_id}")
    return driver


def get_or_launch_driver(reuse=True, headless=False, session_path=None):
    """Devuelve un driver activo. Si reuse=True intenta primero conectar a
    la session guardada; si falla, lanza uno detached nuevo y guarda la session."""
    if reuse:
        d = _reuse_driver_session(path=session_path)
        if d is not None:
            return d
        print("[INFO] fallback a launch_detached_driver")
    driver = launch_detached_driver(FLASHSCORE_BASE, headless=headless)
    try:
        login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
    except Exception as e:
        print(f"[WARN] login fallo: {e} — sigo sin login")
    _save_driver_session(driver, path=session_path)
    return driver


def is_african_match(match_name):
    """True si ambos lados de 'TeamA~TeamB' son selecciones africanas."""
    if not match_name or '~' not in match_name:
        return False
    home, _, away = match_name.partition('~')
    return home.strip() in AFRICAN_NATIONS and away.strip() in AFRICAN_NATIONS

# Scope por defecto: solo WORLD + AFRICA World Cup (subset chico para validar)
DEFAULT_LEAGUES = [
    ('FOOTBALL', 'WORLD_World Cup'),
    ('FOOTBALL', 'AFRICA_World Cup'),
]


# ─── DETECCION EN DB ────────────────────────────────────────────────────────

def detect_null_team_matches(con, league_ids, match_id_filter=None):
    """
    Retorna lista de dicts para matches que requieran alguna reparacion:
      - match_detail con team_id IS NULL  (puede ser COMPLETED o SCHEDULED)
      - match COMPLETED sin score_entity en al menos un match_detail
      - match COMPLETED con match.statistic vacio (NULL, '', '{}')

    Cada dict incluye {match_id, name, match_date, status, statistic,
                       league_id, season_id, sport_id, country_id_liga,
                       league_name, sport_name, country_name,
                       needs_team_fix, needs_score_fix, needs_stats_fix}.

    Si match_id_filter se pasa, restringe a ese match_id (para test puntual)
    y devuelve los 3 flags evaluados sobre ese match.
    """
    cur = con.cursor()
    base_select = """
        SELECT DISTINCT m.match_id, m.name, m.match_date, m.status, m.statistic,
               m.league_id, m.season_id,
               l.sport_id, l.country_id, l.league_name,
               s.name AS sport_name, c.country_name,
               EXISTS (
                   SELECT 1 FROM match_detail md2
                    WHERE md2.match_id = m.match_id AND md2.team_id IS NULL
               ) AS needs_team_fix,
               EXISTS (
                   SELECT 1 FROM match_detail md3
                    LEFT JOIN score_entity se ON se.match_detail_id = md3.match_detail_id
                    WHERE md3.match_id = m.match_id AND se.score_id IS NULL
               ) AND m.status = 'COMPLETED' AS needs_score_fix,
               (m.statistic IS NULL OR m.statistic IN ('', '{}'))
                  AND m.status = 'COMPLETED' AS needs_stats_fix
          FROM match m
          JOIN match_detail md ON md.match_id = m.match_id
          JOIN league l ON l.league_id = m.league_id
          JOIN sport  s ON s.sport_id  = l.sport_id
          LEFT JOIN country c ON c.country_id = l.country_id
    """
    if match_id_filter:
        cur.execute(base_select + " WHERE m.match_id = %s", (match_id_filter,))
    else:
        cur.execute(base_select + """
             WHERE m.league_id = ANY(%s)
               AND (
                   EXISTS (SELECT 1 FROM match_detail md4
                             WHERE md4.match_id = m.match_id AND md4.team_id IS NULL)
                OR (m.status = 'COMPLETED' AND (m.statistic IS NULL OR m.statistic IN ('', '{}')))
                OR (m.status = 'COMPLETED' AND EXISTS (
                       SELECT 1 FROM match_detail md5
                        LEFT JOIN score_entity se ON se.match_detail_id = md5.match_detail_id
                        WHERE md5.match_id = m.match_id AND se.score_id IS NULL))
               )
             ORDER BY m.match_date DESC
        """, (league_ids,))
    cols = ['match_id','name','match_date','status','statistic',
            'league_id','season_id','sport_id','country_id_liga',
            'league_name','sport_name','country_name',
            'needs_team_fix','needs_score_fix','needs_stats_fix']
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    # Filtrar matches confirmados "sin cobertura de stats" (cache persistente).
    # Si el match SOLO necesitaba stats y ya esta confirmado sin cobertura,
    # se excluye completamente. Si tambien necesita team/score, se mantiene
    # pero marcamos needs_stats_fix=False para no perder tiempo en la rama
    # de stats.
    without_stats = get_confirmed_without_stats_ids()
    if without_stats:
        filtered = []
        skipped_only_stats = 0
        skipped_stats_branch = 0
        for m in rows:
            if m['match_id'] in without_stats:
                if m['needs_stats_fix'] and not m['needs_team_fix'] and not m['needs_score_fix']:
                    # Solo necesitaba stats y ya esta confirmado sin cobertura -> excluir
                    skipped_only_stats += 1
                    continue
                # Necesita otros fixes -> mantener pero deshabilitar stats
                if m['needs_stats_fix']:
                    m['needs_stats_fix'] = False
                    skipped_stats_branch += 1
            filtered.append(m)
        if skipped_only_stats or skipped_stats_branch:
            print(f"[WITHOUT_STATS_CACHE] excluidos completamente: {skipped_only_stats}, "
                  f"stats-branch deshabilitada: {skipped_stats_branch}")
        rows = filtered

    return rows


# ─── EXTRACCION DE LINKS DESDE EL MATCH ─────────────────────────────────────

def get_team_links_from_match(driver):
    """
    Extrae [home_team_url, away_team_url] absolutos desde la pagina del match.

    Usa el selector de FlashScore (estable para Football, Basketball,
    American Football, Hockey):
        <a href="/team/<slug>/<id>/" class="participant__participantName ...">

    Espera con WebDriverWait a que aparezcan AMBOS links (timing es el
    fallo principal en deportes secundarios — el container duelParticipant
    aparece antes que sus hijos).

    Toma el primero como home y el segundo como away (orden DOM = orden
    HOME/AWAY de FlashScore).

    Returns:
        (home_url, away_url) — strings absolutos. (None, None) si fallo.
    """
    from selenium.webdriver.support.ui import WebDriverWait
    xpath_all = "//a[contains(@class,'participant__participantName')]"
    try:
        WebDriverWait(driver, 10).until(
            lambda d: len(d.find_elements(By.XPATH, xpath_all)) >= 2
        )
    except Exception as e:
        print(f"  [WARN] timeout esperando team links: {e}")

    links = driver.find_elements(By.XPATH, xpath_all)
    if len(links) < 2:
        print(f"  [WARN] solo encontre {len(links)} link(s), esperaba 2")
        return (None, None)

    def absolute(href):
        if not href:
            return None
        if href.startswith('/'):
            return FLASHSCORE_BASE + href
        return href

    return absolute(links[0].get_attribute('href')), absolute(links[1].get_attribute('href'))


# ─── CREACION DE STADIUM SI APLICA ──────────────────────────────────────────

# heading__info en team page contiene cosas distintas segun el equipo:
#   - Clubs:        "<Stadium Name>(capacity)"
#   - Selecciones:  "FIFA: <rank>."  → no es un estadio
# Patrones a tratar como NO-stadium (ranking, info no relevante).
_NON_STADIUM_PREFIXES = ('FIFA:', 'IIHF:', 'FIBA:', 'WORLD RANKING:', 'RANKING:')


def _parse_stadium_text(raw):
    """
    Devuelve (name, capacity) si raw parece un stadium, o (None, 0) si no.

    Ejemplos:
      'Stade Bambari'                  -> ('Stade Bambari', 0)
      'Old Trafford(74879)'            -> ('Old Trafford', 74879)
      'FIFA: 139.'                     -> (None, 0)
      ''                               -> (None, 0)
    """
    if not raw:
        return None, 0
    raw = raw.strip()
    for pref in _NON_STADIUM_PREFIXES:
        if raw.upper().startswith(pref):
            return None, 0
    # Extraer capacidad si viene entre parentesis al final
    name, capacity = raw, 0
    if '(' in raw and raw.endswith(')'):
        head, _, cap = raw.rpartition('(')
        cap = cap.rstrip(')').replace(',', '').replace(' ', '').replace('.', '')
        if cap.isdigit():
            name = head.strip()
            capacity = int(cap)
    return (name or None), capacity


def ensure_stadium_created(con, stadium_raw, dry_run=False):
    """
    Si stadium_raw es un nombre valido, reusa el stadium existente (matching
    por nombre) o crea uno nuevo.

    Args:
        con         : conexion psycopg2 activa (no se usa para INSERT
                      porque save_stadium_in_db usa la conexion modulo;
                      se pasa solo para la query de lookup).
        stadium_raw : texto crudo extraido de heading__info del team page.
        dry_run     : si True, no crea (devuelve 'WOULD_CREATE:<name>').

    Returns:
        stadium_id (str) o '' si no aplica / no se pudo.
    """
    name, capacity = _parse_stadium_text(stadium_raw)
    if not name:
        return ''
    # Buscar por nombre
    cur = con.cursor()
    cur.execute("SELECT stadium_id FROM stadium WHERE name = %s LIMIT 1", (name,))
    row = cur.fetchone()
    if row:
        print(f"    [STADIUM] reusando existente {name!r} → {row[0]}")
        return row[0]
    if dry_run:
        print(f"    [STADIUM DRY-RUN] WOULD CREATE {name!r} capacity={capacity}")
        return f"WOULD_CREATE:{name}"
    stadium_id = generate_uuid()
    try:
        save_stadium_in_db({
            'stadium_id': stadium_id,
            'capacity':   capacity,
            'desc_i18n':  '',
            'name':       name,
            'photo':      '',
        })
        print(f"    [STADIUM CREATED] {name!r} id={stadium_id} capacity={capacity}")
        return stadium_id
    except Exception as e:
        print(f"    [STADIUM ERROR] {name!r}: {e}")
        return ''


# ─── CACHE team_url → team_id (Fix 1) ──────────────────────────────────────

def load_url_team_cache(sport_key, league_key):
    """
    Lee el JSON de leagues_season/{SPORT}/{LEAGUE}.json y devuelve un dict
    {team_url: team_id} de todos los teams ya creados.

    VALIDA que cada team_id realmente exista en la tabla `team` de DB —
    evita FK violations cuando el JSON quedo desactualizado por crashes
    previos (cache stale).

    Permite que `ensure_team_created` haga early-return SIN navegar al
    team page si la URL ya está cacheada (ahorro ~8 seg por team repetido).
    """
    path = _league_season_json_path(sport_key, league_key)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        data = json.load(f)

    raw_cache = {}
    for team_name, info in data.items():
        url = info.get('team_url', '')
        tid = info.get('team_id', '')
        if url and tid:
            raw_cache[url] = tid

    # Validar contra DB: solo conservar team_ids que existan en `team`
    if not raw_cache:
        return {}
    con = getdb()
    cur = con.cursor()
    cur.execute("SELECT team_id FROM team WHERE team_id = ANY(%s)",
                (list(raw_cache.values()),))
    valid_ids = {row[0] for row in cur.fetchall()}
    con.close()

    cache = {url: tid for url, tid in raw_cache.items() if tid in valid_ids}
    stale = len(raw_cache) - len(cache)
    print(f"[CACHE] team_url cargado: {len(cache)} entradas validas de {path}"
          f" ({stale} entradas stale ignoradas)")
    return cache


# ─── CACHE persistente de scan_results_page (Fix 2) ────────────────────────

def _scan_cache_path(league_id):
    return os.path.join(SCAN_CACHE_DIR, f'{league_id}.json')


def load_scan_cache(league_id):
    """Lee tmp/scan_cache/<league_id>.json. Retorna {match_id: scraped_dict} o {}."""
    path = _scan_cache_path(league_id)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        cache = json.load(f)
    print(f"[CACHE] scan cargado: {len(cache)} match URLs de {path}")
    return cache


# ─── CACHE persistente: matches sin cobertura de stats en FlashScore ───────
#
# Muchos matches (eliminatorias menores, basket/baseball sin cobertura, etc.)
# NUNCA tendran stats publicados en FlashScore. Tras detectarlos como
# 'no_stats_on_page', los registramos aqui para que detect_null_team_matches
# los excluya en futuras corridas y no perder tiempo re-procesandolos.
#
# Politica: tras 2+ intentos fallidos, el match se marca como sin cobertura
# permanente. Re-verificacion tras 30 dias (por si FlashScore agrega
# cobertura).

WITHOUT_STATS_PATH = os.path.join('tmp', 'without_statistics.json')
WITHOUT_STATS_MIN_ATTEMPTS = 1          # 1 intento basta — match ya revisado
WITHOUT_STATS_RECHECK_DAYS = 30         # recheck despues de N dias


def load_without_stats_cache():
    """Lee tmp/without_statistics.json → {match_id: {checked_at, attempts, reason}}."""
    if not os.path.isfile(WITHOUT_STATS_PATH):
        return {}
    try:
        with open(WITHOUT_STATS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def mark_match_without_stats(match_id, reason='no_stats_on_page'):
    """
    Incrementa el contador de intentos fallidos para este match_id en
    tmp/without_statistics.json. Retorna el numero de intentos actuales
    para que el caller decida si persistir en DB.
    """
    from datetime import datetime
    os.makedirs(os.path.dirname(WITHOUT_STATS_PATH), exist_ok=True)
    cache = load_without_stats_cache()
    entry = cache.get(match_id, {'attempts': 0})
    entry['attempts'] = entry.get('attempts', 0) + 1
    entry['checked_at'] = datetime.now().isoformat(timespec='seconds')
    entry['reason'] = reason
    cache[match_id] = entry
    with open(WITHOUT_STATS_PATH, 'w') as f:
        json.dump(cache, f, indent=2)
    return entry['attempts']


def persist_without_stats_in_db(con, match_id, dry_run=False):
    """
    Marca el match en DB como 'without_statistics' en la columna match.statistic.
    Esto evita que vuelva a aparecer como needs_stats_fix en futuras detecciones
    (la query usa NULL/''/'{}' como criterio de "sin stats").
    Solo INSERT-equivalente: si ya tiene stats reales, NO sobrescribe.
    """
    if dry_run:
        print(f"    [DRY-RUN] WOULD UPDATE match.statistic='without_statistics' for {match_id[:8]}")
        return False
    cur = con.cursor()
    cur.execute(
        """UPDATE match SET statistic = 'without_statistics'
           WHERE match_id = %s
             AND (statistic IS NULL OR statistic IN ('', '{}'))""",
        (match_id,)
    )
    updated = cur.rowcount
    con.commit()
    return updated > 0


def get_confirmed_without_stats_ids():
    """
    Retorna set de match_ids confirmados "sin cobertura" (>= MIN_ATTEMPTS
    intentos fallidos y checked dentro de RECHECK_DAYS).
    """
    from datetime import datetime, timedelta
    cache = load_without_stats_cache()
    if not cache:
        return set()
    cutoff = datetime.now() - timedelta(days=WITHOUT_STATS_RECHECK_DAYS)
    confirmed = set()
    for mid, entry in cache.items():
        if entry.get('attempts', 0) < WITHOUT_STATS_MIN_ATTEMPTS:
            continue
        try:
            checked = datetime.fromisoformat(entry.get('checked_at', ''))
        except Exception:
            checked = datetime.now()
        if checked >= cutoff:
            confirmed.add(mid)
    return confirmed


def _problems_path(league_id):
    return os.path.join(PROBLEMS_DIR, f'{league_id}.json')


def save_problem(league_id, match_id, match_name, match_date, reason,
                 match_url=None, home_url=None, away_url=None):
    """
    Guarda un match no resoluble en tmp/problems/<league_id>.json.
    No detiene el script — solo registra para inspección manual posterior.
    """
    os.makedirs(PROBLEMS_DIR, exist_ok=True)
    path = _problems_path(league_id)
    data = {}
    if os.path.isfile(path):
        with open(path) as f:
            data = json.load(f)
    import datetime
    data[match_id] = {
        'name':       match_name,
        'match_date': str(match_date),
        'reason':     reason,
        'match_url':  match_url or '',
        'home_url':   home_url or '',
        'away_url':   away_url or '',
        'recorded_at': datetime.datetime.utcnow().isoformat(timespec='seconds'),
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"    [PROBLEM RECORDED] {match_name} → {path} (reason: {reason})")


def save_scan_cache(league_id, cache):
    """Persiste scan cache. Merge con lo que ya hay."""
    os.makedirs(SCAN_CACHE_DIR, exist_ok=True)
    path = _scan_cache_path(league_id)
    existing = {}
    if os.path.isfile(path):
        with open(path) as f:
            existing = json.load(f)
    existing.update(cache)
    # Anotar timestamp en cada entrada
    import datetime
    now = datetime.datetime.utcnow().isoformat(timespec='seconds')
    for k, v in existing.items():
        if isinstance(v, dict) and 'scanned_at' not in v:
            v['scanned_at'] = now
    with open(path, 'w') as f:
        json.dump(existing, f, indent=2, default=str)
    print(f"[CACHE] scan guardado: {len(existing)} entradas en {path}")


# ─── ACTUALIZACION DEL JSON de la liga ─────────────────────────────────────

def _league_season_json_path(sport_key, league_key):
    """Devuelve ruta del JSON de check_points/leagues_season para la liga."""
    return os.path.join(
        'check_points', 'leagues_season', sport_key, f'{league_key}.json',
    )


def upsert_team_in_league_json(sport_key, league_key, team_name,
                               team_id, team_url, stadium_id=''):
    """
    Agrega o actualiza el registro del team en
    `check_points/leagues_season/{SPORT}/{LEAGUE}.json`.

    Estructura por liga:
        { team_name: { team_id, team_url, stadium_id }, ... }
    """
    path = _league_season_json_path(sport_key, league_key)
    if not os.path.isfile(path):
        print(f"    [JSON] no existe {path} — creando vacio")
        data = {}
        os.makedirs(os.path.dirname(path), exist_ok=True)
    else:
        with open(path) as f:
            data = json.load(f)

    existing = data.get(team_name)
    entry = {
        'team_id':    team_id,
        'team_url':   team_url,
        'stadium_id': stadium_id or '',
    }
    if existing == entry:
        print(f"    [JSON] {team_name!r} ya estaba con misma info — no toco")
        return False
    data[team_name] = entry
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"    [JSON] upsert {team_name!r} en {path}")
    return True


# ─── CREACION DE TEAM SI NO EXISTE ──────────────────────────────────────────

def ensure_team_created(driver, team_url, league_inf, dict_teams_db,
                        sport_id, dry_run, sport_key=None, league_key=None,
                        url_cache=None, stadium_out=None):
    """
    Si el team no existe en `team`, navega a su URL y lo crea via milestone3.

    Args:
        team_url      : URL absoluta del equipo.
        league_inf    : dict con sport_id, sport_name, league_id, league_name,
                        season_id, country_id.
        dict_teams_db : cache en memoria que mantiene `create_team_in_db`.
        sport_id      : id del deporte.
        dry_run       : si True, no escribe a DB; solo simula.

    Returns:
        team_id (str) o None si fallo.
    """
    if not team_url:
        return None

    # FIX 1: cache hit por team_url → no navegar
    if url_cache is not None and team_url in url_cache:
        cached_id = url_cache[team_url]
        print(f"    [CACHE HIT] {team_url} → team_id={cached_id} (sin navegar)")
        return cached_id

    print(f"    -> navegando a team_url: {team_url}")
    try:
        wait_update_page(driver, team_url, 'heading')
        dismiss_cookies(driver)
    except Exception as e:
        print(f"    [ERROR] navegando: {e}")
        return None

    # Datos por defecto para los campos no aplicables (no venimos de standings)
    team_info_dummy = {
        'statistics': {},
        'last_results': [],
        'position': 0,
        'team_url': team_url,
    }

    try:
        dict_team = get_teams_info_part2(driver, league_inf, team_info_dummy)
    except Exception as e:
        print(f"    [ERROR] extrayendo team info: {e}")
        return None

    # get_teams_info_part2 devuelve team_country (nombre de pais) pero
    # create_team_in_db espera country_id (hash). Mapeamos con la DB.
    try:
        country_id = get_country_id(dict_team['team_country'])
    except Exception:
        country_id = league_inf.get('country_id')
    dict_team['country_id'] = country_id

    # Campos EXACTOS que se insertarían en `team` (verificación de prueba):
    print("    [TEAM FIELDS] " + " | ".join(f"{k}={dict_team.get(k)!r}" for k in dict_team))

    if dry_run:
        print(f"    [DRY-RUN] WOULD CREATE team: {dict_team.get('team_name')} "
              f"country_id={country_id} team_id={dict_team['team_id']}")
        return dict_team['team_id']

    try:
        team_id = create_team_in_db(dict_teams_db, sport_id, dict_team)
        print(f"    [CREATED/EXISTING] team_id={team_id} "
              f"name={dict_team['team_name']}")

        # Stadium: crear si el team page expone uno valido (no ranking FIFA)
        stadium_id = ''
        stadium_raw = dict_team.get('stadium', '')
        if stadium_raw:
            stadium_id = ensure_stadium_created(
                con=getdb(), stadium_raw=stadium_raw, dry_run=dry_run,
            )
        # exponer el stadium_id al caller (para que el match use el del equipo)
        if stadium_out is not None:
            stadium_out['stadium_id'] = stadium_id

        # Sincronizar el JSON de la liga (no critico si falla)
        if sport_key and league_key:
            try:
                upsert_team_in_league_json(
                    sport_key, league_key,
                    team_name=dict_team['team_name'],
                    team_id=team_id,
                    team_url=team_url,
                    stadium_id=stadium_id,
                )
            except Exception as e:
                print(f"    [WARN] upsert JSON fallo: {e}")
        # FIX 1: actualizar cache para que próximos matches con este team
        # tampoco naveguen
        if url_cache is not None and team_id:
            url_cache[team_url] = team_id
        return team_id
    except Exception as e:
        print(f"    [ERROR] create_team_in_db: {e}")
        return None


# ─── ACTUALIZACION DE match_detail ──────────────────────────────────────────

def update_match_detail_team(con, match_id, home_team_id, away_team_id, dry_run):
    """
    Repara match_detail asignando team_id al detail correspondiente.

    Decide entre INSERT y UPDATE segun el estado actual del match:
      - Si NO hay filas en match_detail → INSERT 2 filas (home + visitor).
      - Si hay 1 fila → completa la faltante con INSERT, y si esa fila
        tiene team_id NULL la actualiza si encaja (home o visitor).
      - Si hay >=2 filas con team_id NULL → UPDATE las que tengan NULL.

    Returns:
        dict con conteos: { inserted_home, inserted_away,
                            updated_home, updated_away }
    """
    cur = con.cursor()
    # Inspeccionar estado actual del match_detail
    cur.execute("""
        SELECT match_detail_id, home, visitor, team_id
          FROM match_detail
         WHERE match_id = %s
    """, (match_id,))
    rows = cur.fetchall()

    has_home    = any(r[1] for r in rows)
    has_visitor = any(r[2] for r in rows)

    stats = {'inserted_home': 0, 'inserted_away': 0,
             'updated_home': 0, 'updated_away': 0}

    if dry_run:
        # Reportar el plan
        plan = []
        if not has_home:
            plan.append(f"INSERT home (team_id={home_team_id})")
        else:
            plan.append(f"UPDATE home WHERE team_id IS NULL → {home_team_id}")
        if not has_visitor:
            plan.append(f"INSERT away (team_id={away_team_id})")
        else:
            plan.append(f"UPDATE visitor WHERE team_id IS NULL → {away_team_id}")
        for p in plan:
            print(f"    [DRY-RUN] WOULD {p}")
        return stats

    # --- HOME ---
    if not has_home:
        cur.execute("""
            INSERT INTO match_detail (match_detail_id, home, visitor, match_id, team_id)
            VALUES (%s, TRUE, FALSE, %s, %s)
        """, (generate_uuid(), match_id, home_team_id))
        stats['inserted_home'] = cur.rowcount
    else:
        cur.execute("""
            UPDATE match_detail SET team_id = %s
             WHERE match_id = %s AND team_id IS NULL AND home = TRUE
        """, (home_team_id, match_id))
        stats['updated_home'] = cur.rowcount

    # --- VISITOR ---
    if not has_visitor:
        cur.execute("""
            INSERT INTO match_detail (match_detail_id, home, visitor, match_id, team_id)
            VALUES (%s, FALSE, TRUE, %s, %s)
        """, (generate_uuid(), match_id, away_team_id))
        stats['inserted_away'] = cur.rowcount
    else:
        cur.execute("""
            UPDATE match_detail SET team_id = %s
             WHERE match_id = %s AND team_id IS NULL AND visitor = TRUE
        """, (away_team_id, match_id))
        stats['updated_away'] = cur.rowcount

    con.commit()
    return stats


def fix_score_entities(con, match_id, scraped, dry_run):
    """
    Asegura que cada match_detail del match tenga su fila en score_entity.
    Usa los goles capturados en scan_results_page (scraped['home_result'],
    scraped['visitor_result']).

    Returns:
        dict con conteos: { inserted_home, inserted_away, already_present }
    """
    stats = {'inserted_home': 0, 'inserted_away': 0, 'already_present': 0}
    details = get_math_details_ids(match_id)  # {match_detail_id: home_flag}
    if not details:
        return stats

    home_pts    = scraped.get('home_result', '')
    visitor_pts = scraped.get('visitor_result', '')

    for detail_id, home_flag in details.items():
        if get_score_by_match_detail_id(detail_id):
            stats['already_present'] += 1
            continue
        points = home_pts if home_flag else visitor_pts
        label = 'home' if home_flag else 'visitor'
        if dry_run:
            print(f"    [DRY-RUN] WOULD INSERT score_entity {label} points={points!r}")
            continue
        save_score_info({
            'score_id':        generate_uuid(),
            'points':          points,
            'match_detail_id': detail_id,
        })
        if home_flag:
            stats['inserted_home'] += 1
        else:
            stats['inserted_away'] += 1
    return stats


def fix_match_statistic(con, driver, match_id, dry_run):
    """
    Extrae estadisticas reutilizando milestone4.get_statistics_game (clic
    al boton "Stats" + lectura wcl-statistics). Devuelve dict 33+ cats
    tipico en Premier League. Si get_statistics_game devuelve {} se marca
    el match como sin cobertura.

    NOTA: la primera llamada justo despues de navegar a match_url puede
    devolver solo las 5 stats del tab "Top Stats" porque las otras
    secciones (Shots/Passing/etc) cargan lazy. Si pasa, reintentamos una
    vez tras ~3s — la 2da llamada captura las 33+ cats reales.

    Returns:
        dict { extracted_categories, updated } o { 'skipped': reason }.
    """
    import ast as _ast
    import time as _time

    def _try_extract():
        try:
            s = get_statistics_game(driver)
        except Exception as e:
            return {}, f'extract_error: {e}'
        try:
            d = _ast.literal_eval(s) if s else {}
            if not isinstance(d, dict):
                d = {}
        except Exception:
            d = {}
        return d, None

    info, err = _try_extract()
    if err:
        return {'skipped': err, 'updated': 0}

    # Reintentos para evitar marcar como "sin cobertura" por timing.
    # FlashScore renderiza Top Stats (~5 cats) en 1-2s y el resto en 3-5s.
    # Si tras navegar al match la primera lectura es 0 o <10 cats, esperar
    # y reintentar hasta 2 veces con sleep creciente.
    for attempt, wait_s in enumerate([3, 5], start=1):
        if len(info) >= 10:
            break
        print(f"    [RETRY {attempt}/2] {len(info)} cats — esperando {wait_s}s...")
        _time.sleep(wait_s)
        info_new, err_new = _try_extract()
        if not err_new and len(info_new) > len(info):
            info = info_new

    cat_count = len(info)

    if cat_count == 0:
        mark_match_without_stats(match_id, reason='no_stats_extracted')
        persist_without_stats_in_db(con, match_id, dry_run=dry_run)
        return {'skipped': 'no_stats_extracted', 'updated': 0}

    # IMPRIMIR en pantalla las categorias y valores que se van a guardar
    print(f"    [STATS EXTRAIDAS] {cat_count} categorias:")
    for k, v in info.items():
        print(f"        - {k:32s} home={v.get('home',''):>14s}  away={v.get('away',''):>14s}")

    if dry_run:
        print(f"    [DRY-RUN] WOULD UPDATE match.statistic ({cat_count} categorias)")
        _append_insert_log(match_id, cat_count, info, dry_run=True)
        return {'extracted_categories': cat_count, 'updated': 0}

    cur = con.cursor()
    cur.execute(
        "UPDATE match SET statistic = %s WHERE match_id = %s",
        (str(info), match_id),
    )
    updated = cur.rowcount
    con.commit()
    _append_insert_log(match_id, cat_count, info, dry_run=False)
    return {'extracted_categories': cat_count, 'updated': updated}


# ─── Ring-buffer log de ultimos 20 inserts (JSONL) ─────────────────────────
INSERT_LOG_PATH = 'tmp/logs/stats_inserts.jsonl'
INSERT_LOG_MAX  = 20

def _append_insert_log(match_id, cat_count, info, dry_run=False):
    """Agrega entrada al log; rota a ultimas INSERT_LOG_MAX entries."""
    import datetime as _dt
    os.makedirs(os.path.dirname(INSERT_LOG_PATH), exist_ok=True)
    entry = {
        'ts': _dt.datetime.now().isoformat(timespec='seconds'),
        'match_id': match_id,
        'dry_run': dry_run,
        'cat_count': cat_count,
        'stats': info,
    }
    existing = []
    if os.path.isfile(INSERT_LOG_PATH):
        with open(INSERT_LOG_PATH) as f:
            for line in f:
                line = line.strip()
                if line:
                    try: existing.append(json.loads(line))
                    except Exception: pass
    existing.append(entry)
    existing = existing[-INSERT_LOG_MAX:]
    with open(INSERT_LOG_PATH, 'w') as f:
        for e in existing:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


# ─── ORQUESTACION PRINCIPAL ─────────────────────────────────────────────────

def fix_null_team_ids(*, dry_run=True, headless=False,
                      sport_keys=None, match_id_filter=None,
                      reuse_driver=True, keep_alive=True,
                      only_african=False, only_stats_past=False,
                      session_path=None, verbose=True):
    """
    Procesa los matches con team_id NULL en las ligas indicadas.

    Args:
        dry_run    : True (default) no escribe a DB; solo simula.
        headless   : False (default) — driver visible para inspeccion.
        sport_keys : lista de tuplas (SPORT_KEY, LEAGUE_KEY) de leagues_info,
                     ej. [('FOOTBALL','WORLD_World Cup'), ('FOOTBALL','AFRICA_World Cup')].
        verbose    : detalle por match.

    Returns:
        dict con stats: { leagues, matches_total, matches_fixed,
                          teams_created, errors }
    """
    sport_keys = sport_keys or DEFAULT_LEAGUES
    leagues_info = load_json(LEAGUES_INFO_PATH)

    # Resolver league_ids desde leagues_info
    league_ids = []
    league_meta = {}
    for sport_key, league_key in sport_keys:
        try:
            info = leagues_info[sport_key][league_key]
        except KeyError:
            print(f"[WARN] {sport_key}/{league_key} no existe en leagues_info")
            continue
        league_ids.append(info['league_id'])
        league_meta[info['league_id']] = {
            'sport_key': sport_key,
            'league_key': league_key,
            'results_url': info.get('results') or info.get('url'),
            'season_id': info['season_id'],
            'country_id': info.get('country_id'),
        }

    if not league_ids:
        print("[ABORT] no hay ligas a procesar.")
        return {}

    # Detectar matches afectados
    con = getdb()
    try:
        matches = detect_null_team_matches(con, league_ids, match_id_filter=match_id_filter)
    finally:
        con.close()

    if only_african:
        before = len(matches)
        matches = [m for m in matches if is_african_match(m['name'])]
        print(f"[FILTER] only_african: {before} → {len(matches)} matches")

    if only_stats_past:
        from datetime import date
        today = date.today()
        before = len(matches)
        filtered = []
        for m in matches:
            if not m.get('needs_stats_fix'):
                continue
            if m['match_date'] is None or m['match_date'] >= today:
                continue
            # Forzar a SOLO procesar la rama de stats (apaga team/score)
            m['needs_team_fix'] = False
            m['needs_score_fix'] = False
            filtered.append(m)
        matches = filtered
        print(f"[FILTER] only_stats_past: {before} → {len(matches)} matches (date < {today})")

    # Override: si vamos a un match puntual con una liga distinta a la que
    # tiene asignada en DB (caso comun: match mal-asignado), redirige al
    # league_id de la URL que estamos por scanear.
    if match_id_filter and league_meta:
        override_lid = next(iter(league_meta))
        for m in matches:
            if m['league_id'] != override_lid:
                print(f"[OVERRIDE] match {m['match_id']} estaba en "
                      f"{m['league_id'][:8]}…, lo proceso bajo "
                      f"{override_lid[:8]}…")
                m['league_id'] = override_lid

    if not matches:
        print("Sin matches incompletos (team_id NULL / score / stats) para los filtros indicados.")
        # Imprimir RESUMEN para que el watchdog pueda detectar el fin
        print('\n' + '=' * 72)
        print(f"RESUMEN (dry_run={dry_run})")
        print(f"  Ligas procesadas    : 0")
        print(f"  Matches detectados  : 0")
        print(f"  Matches reparados   : 0")
        print(f"  Scores agregados    : 0")
        print(f"  Stats agregados     : 0")
        print(f"  Errores             : 0")
        print('=' * 72)
        return {}

    n_team  = sum(1 for m in matches if m.get('needs_team_fix'))
    n_score = sum(1 for m in matches if m.get('needs_score_fix'))
    n_stats = sum(1 for m in matches if m.get('needs_stats_fix'))
    print('=' * 72)
    print(f"MATCHES INCOMPLETOS: {len(matches)}  (dry_run={dry_run})")
    print(f"  needs team_fix : {n_team}")
    print(f"  needs score_fix: {n_score}")
    print(f"  needs stats_fix: {n_stats}")
    print(f"Ligas: {[(k['sport_key'], k['league_key']) for k in league_meta.values()]}")
    print('=' * 72)

    # Agrupar por liga
    by_league = defaultdict(list)
    for m in matches:
        by_league[m['league_id']].append(m)

    # Driver: reusar si hay session activa; si no, lanzar y guardar
    print(f"\n[DRIVER] reuse_driver={reuse_driver} headless={headless} "
          f"keep_alive={keep_alive} session_path={session_path or DRIVER_SESSION_PATH}")
    driver = get_or_launch_driver(reuse=reuse_driver, headless=headless,
                                   session_path=session_path)

    # Cache en memoria para create_team_in_db — usar sport_id de la primera liga
    # (todas las ligas en scope deben ser del mismo deporte; si no, este cache se rellena vacio para el primero)
    first_sport_id = matches[0]['sport_id']
    dict_teams_db = get_dict_league_ready(sport_id=first_sport_id)

    stats = defaultdict(int)
    stats['leagues'] = len(by_league)
    stats['matches_total'] = len(matches)

    con = getdb()
    try:
        for league_id, league_matches in by_league.items():
            meta = league_meta[league_id]
            sport_key = meta['sport_key']
            league_key = meta['league_key']
            results_url = meta['results_url']

            print('\n' + '─' * 72)
            print(f"[{sport_key}] {league_key} — {len(league_matches)} matches")
            print(f"  results_url: {results_url}")

            if not results_url:
                print("  [SKIP] sin URL de results en leagues_info")
                stats['errors'] += len(league_matches)
                continue

            # Cargar pagina hasta la fecha mas vieja
            try:
                wait_update_page(driver, results_url, 'container__heading')
                dismiss_cookies(driver)
            except Exception as e:
                print(f"  [ERROR] navegando results: {e}")
                stats['errors'] += len(league_matches)
                continue

            # FIX 2: cargar scan cache persistente y solo escanear lo faltante
            scan_cache = load_scan_cache(league_id)
            ids_needed = {m['match_id'] for m in league_matches}
            ids_cached = set(scan_cache.keys()) & ids_needed
            ids_missing = ids_needed - ids_cached
            print(f"  [SCAN CACHE] {len(ids_cached)} cacheados / {len(ids_missing)} faltantes")

            if ids_missing:
                # Solo escanear los matches no cacheados
                oldest = min(m['match_date'] for m in league_matches
                              if m['match_id'] in ids_missing)
                load_until_date(driver, oldest)
                matches_to_scan = [m for m in league_matches if m['match_id'] in ids_missing]
                newly_found = scan_results_page(driver, matches_to_scan)
                # Mergear y persistir
                scan_cache.update(newly_found)
                save_scan_cache(league_id, newly_found)

            found = scan_cache

            # Construir league_inf reutilizable
            league_inf = {
                'sport_id':    league_matches[0]['sport_id'],
                'sport_name':  league_matches[0]['sport_name'],
                'league_id':   league_id,
                'league_name': league_matches[0]['league_name'],
                'season_id':   meta['season_id'],
                'country_id':  meta['country_id'],
            }

            # FIX 1: pre-cargar url_cache para este sport_key/league_key
            url_cache = load_url_team_cache(sport_key, league_key)

            # Por cada match afectado
            for m in league_matches:
                flags = []
                if m.get('needs_team_fix'):  flags.append('team')
                if m.get('needs_score_fix'): flags.append('score')
                if m.get('needs_stats_fix'): flags.append('stats')
                print(f"\n  >>> {m['match_date']} {m['name']}  needs={'+'.join(flags) or 'none'}")

                if m['match_id'] not in found:
                    print("    [SKIP] no encontrado en results page")
                    save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                 reason='not_found_in_results_page')
                    stats['errors'] += 1
                    continue

                scraped = found[m['match_id']]
                match_url = scraped['link_details']
                print(f"    match_url: {match_url}")

                try:
                    wait_update_page(driver, match_url, 'duelParticipant')
                    dismiss_cookies(driver)
                except Exception as e:
                    print(f"    [ERROR] navegando al match: {e}")
                    save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                 reason='nav_error_match_page', match_url=match_url)
                    stats['errors'] += 1
                    continue

                # ── PASO 1: team_id NULL ─────────────────────────────────
                if m.get('needs_team_fix'):
                    home_url, away_url = get_team_links_from_match(driver)
                    print(f"    home_url: {home_url}")
                    print(f"    away_url: {away_url}")

                    if not (home_url and away_url):
                        print("    [SKIP team] no se extrajeron los 2 links de team")
                        save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                     reason='team_links_not_extracted', match_url=match_url,
                                     home_url=home_url, away_url=away_url)
                        stats['errors'] += 1
                        # No 'continue': sigue intentando score/stats si aplica.
                    else:
                        home_team_id = ensure_team_created(
                            driver, home_url, league_inf, dict_teams_db,
                            league_inf['sport_id'], dry_run,
                            sport_key=sport_key, league_key=league_key,
                            url_cache=url_cache,
                        )
                        away_team_id = ensure_team_created(
                            driver, away_url, league_inf, dict_teams_db,
                            league_inf['sport_id'], dry_run,
                            sport_key=sport_key, league_key=league_key,
                            url_cache=url_cache,
                        )

                        if not (home_team_id and away_team_id):
                            print("    [ERROR] no se pudo resolver los 2 teams")
                            save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                         reason='teams_not_resolved', match_url=match_url,
                                         home_url=home_url, away_url=away_url)
                            stats['errors'] += 1
                        elif home_team_id == away_team_id:
                            print("    [WARN] mismo team_id para home y away — saltado")
                            save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                         reason='same_team_id_home_away', match_url=match_url,
                                         home_url=home_url, away_url=away_url)
                            stats['errors'] += 1
                        else:
                            md_stats = update_match_detail_team(
                                con, m['match_id'], home_team_id, away_team_id, dry_run,
                            )
                            total_changed = sum(md_stats.values())
                            if dry_run or total_changed > 0:
                                print(f"    [OK] match_detail {md_stats}")
                                stats['matches_fixed'] += 1
                            else:
                                print("    [WARN] No se afectaron filas (quiza ya tenian team_id)")

                # ── PASO 2: score_entity (solo COMPLETED) ────────────────
                if m.get('needs_score_fix'):
                    try:
                        sc_stats = fix_score_entities(con, m['match_id'], scraped, dry_run)
                        if dry_run or sc_stats['inserted_home'] or sc_stats['inserted_away']:
                            print(f"    [OK] score_entity {sc_stats}")
                            stats['scores_added'] += sc_stats['inserted_home'] + sc_stats['inserted_away']
                    except Exception as e:
                        print(f"    [ERROR] score_entity: {e}")
                        save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                     reason=f'score_error: {e}', match_url=match_url)
                        stats['errors'] += 1

                # ── PASO 3: match.statistic (solo COMPLETED) ─────────────
                if m.get('needs_stats_fix'):
                    try:
                        st_stats = fix_match_statistic(con, driver, m['match_id'], dry_run)
                        if 'skipped' in st_stats:
                            print(f"    [SKIP stats] {st_stats['skipped']}")
                        else:
                            print(f"    [OK] match.statistic {st_stats}")
                            stats['stats_added'] += st_stats.get('updated', 0)
                    except Exception as e:
                        print(f"    [ERROR] stats: {e}")
                        save_problem(league_id, m['match_id'], m['name'], m['match_date'],
                                     reason=f'stats_error: {e}', match_url=match_url)
                        stats['errors'] += 1

        print('\n' + '=' * 72)
        print(f"RESUMEN (dry_run={dry_run})")
        print(f"  Ligas procesadas    : {stats['leagues']}")
        print(f"  Matches detectados  : {stats['matches_total']}")
        print(f"  Matches reparados   : {stats['matches_fixed']}")
        print(f"  Scores agregados    : {stats['scores_added']}")
        print(f"  Stats agregados     : {stats['stats_added']}")
        print(f"  Errores             : {stats['errors']}")
        print('=' * 72)
        return dict(stats)
    finally:
        con.close()
        if not keep_alive:
            try:
                driver.quit()
                print("[DRIVER] cerrado (keep_alive=False)")
            except Exception:
                pass
        else:
            # Re-guarda session_id por si cambio durante la corrida (no deberia)
            try:
                _save_driver_session(driver, path=session_path)
            except Exception:
                pass
            print(f"[DRIVER] sigue vivo — session_id={driver.session_id}\n"
                  f"  Para reusar: agrega --reuse-driver al proximo run, o desde\n"
                  f"  Python:  d = _reuse_driver_session()")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',    action='store_true', help='Escribe en DB (default: dry-run)')
    p.add_argument('--headless', action='store_true', help='Driver headless (default: visible)')
    p.add_argument('--league',   action='append', default=None,
                   metavar='SPORT_KEY/LEAGUE_KEY',
                   help='Filtra una liga (puede repetirse). Ej: '
                        'FOOTBALL/WORLD_World Cup')
    p.add_argument('--match-id', default=None,
                   help='Procesar solo este match_id (test puntual)')
    p.add_argument('--no-reuse', action='store_true',
                   help='NO intentar reusar el driver guardado; siempre lanza uno nuevo.')
    p.add_argument('--quit-at-end', action='store_true',
                   help='Cerrar el driver al terminar (default: lo deja vivo).')
    p.add_argument('--only-african', action='store_true',
                   help='Filtra matches donde AMBOS equipos son selecciones africanas.')
    p.add_argument('--only-stats-past', action='store_true',
                   help='Solo matches con needs_stats_fix=True y match_date<hoy. '
                        'Apaga team_fix y score_fix en esos matches.')
    p.add_argument('--session-file', default=None,
                   help='Path al JSON de sesion del driver (default: tmp/driver_session.json). '
                        'Util para correr 2 instancias en paralelo con drivers separados.')
    args = p.parse_args()

    sport_keys = None
    if args.league:
        sport_keys = []
        for spec in args.league:
            sk, lk = spec.split('/', 1)
            sport_keys.append((sk, lk))

    fix_null_team_ids(
        dry_run=not args.apply,
        headless=args.headless,
        sport_keys=sport_keys,
        match_id_filter=args.match_id,
        reuse_driver=not args.no_reuse,
        keep_alive=not args.quit_at_end,
        only_african=args.only_african,
        only_stats_past=args.only_stats_past,
        session_path=args.session_file,
    )


if __name__ == '__main__':
    main()
