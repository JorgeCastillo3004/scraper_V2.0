"""
live_runner.py — orquestador del scraper LIVE
=============================================
Integra (sin reescribir lógica de scraping) los bloques ya existentes:

  - live_function.process_sport_live()  → 1 deporte/ciclo: imprime 5 campos
    (status, home, score home, visitante, score visitante) y actualiza DB.
  - common_functions.launch_navigator / login                → driver propio
  - scripts/driver_session.get_driver()                      → driver de dev
  - mem_monitor.MemSampler / browser_tree_rss_mb             → memoria
  - telegram_notify.notify / build_hourly_summary            → notificaciones

Responsabilidades:
  1. Loop infinito de supervisión sobre los deportes.
  2. Hot-swap del driver en caliente (abre driver2 + login MIENTRAS driver1
     sigue; cuando driver2 está listo, cierra driver1). SOLO sobre drivers que
     este runner lanzó. Nunca cierra el driver de desarrollo (--attach).
  3. Detección de problema → alerta Telegram inmediata. Latido "todo OK" cada
     hora con resumen de la última hora (dedup, por deporte).

Modos / flags:
  --attach            reusa el driver vivo de start_driver.py (NO lo cierra).
                      Deshabilita el hot-swap (no somos dueños del driver).
  --sports F B ...    deportes (default: FOOTBALL)
  --interval N        segundos entre ciclos (default: 60)
  --duration-min N    termina tras N minutos (0 = infinito; default 0)
  --swap-rss-mb N     umbral RSS del navegador para hot-swap (0 = desactivado)
  --swap-age-min N    edad máx del driver en min para hot-swap (0 = desactivado)
  --zero-cycles N     ciclos consecutivos con 0 partidos antes de alertar (def 2)
  --mem-interval N    cadencia del sampler de memoria en seg (default 30)
  --measure-only      Fase 0: corre + muestrea memoria; sin hot-swap ni alertas

Ejemplos:
  # Fase 0 (medición, conectado al driver de dev, visible):
  DISPLAY=:1 env_sports/bin/python scripts/live_runner.py --attach \
      --measure-only --duration-min 15
  # Producción local (driver propio):
  DISPLAY=:1 env_sports/bin/python scripts/live_runner.py \
      --swap-rss-mb 1500 --swap-age-min 60
"""

import sys, os, json, time, threading, argparse
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config import FS_EMAIL, FS_PASSWORD, LIVE_HEADLESS
from common_functions import launch_navigator, login, dismiss_cookies, load_json
from live_function import process_sport_live
from mem_monitor import (MemSampler, browser_tree_rss_mb, system_available_mb,
                         single_geckodriver_pid)
import telegram_notify as tg

# Indicador de sesión activa de FlashScore (lo usa también login() internamente).
LOGGED_IN_XPATH = '//*[contains(@class,"header__text--loggedIn")]'

FS_URL = 'https://www.flashscore.com'
# Identificador del driver que ESTE runner controla (mismo patrón que
# tmp/driver_session.json): se escribe al lanzar/relevar el driver y el sampler
# de memoria lo lee para medir el subárbol CORRECTO (no todos los geckodriver).
LIVE_DRIVER_FILE = os.path.join(ROOT, 'tmp', 'live_driver.json')


def gecko_pid(driver):
    """PID del geckodriver del driver (None si es attach / no tiene service)."""
    try:
        return driver.service.process.pid
    except Exception:
        return None


def write_live_driver_file(driver, owned, pid_override=None):
    """Guarda el identificador del driver actual para que el sampler lo lea.

    pid_override: si el driver es attached (sin .service), se pasa el pid del
    geckodriver detectado aparte, para que el sampler mida SOLO ese subárbol.
    """
    try:
        executor_url = driver.command_executor._url
    except AttributeError:
        try:
            executor_url = driver.command_executor._client_config.remote_server_addr
        except Exception:
            executor_url = None
    data = {
        'geckodriver_pid': pid_override if pid_override is not None else gecko_pid(driver),
        'session_id': getattr(driver, 'session_id', None),
        'executor_url': executor_url,
        'owned': owned,
    }
    os.makedirs(os.path.dirname(LIVE_DRIVER_FILE), exist_ok=True)
    with open(LIVE_DRIVER_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return data


def verify_logged_in(driver, timeout=10):
    """Confirma (por código) que la sesión de FlashScore está activa en `driver`.
    Es el GATE antes de cerrar driver1: no se cierra hasta verificar esto en
    driver2. login() ya lo chequea, pero re-verificamos explícitamente."""
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.XPATH, LOGGED_IN_XPATH)))
        return True
    except Exception:
        return False


class RelevoThread:
    """
    Lanza driver2 + login en un HILO aparte, sin bloquear el loop que sigue en
    driver1. Aprovecha la espera entre ciclos (~1 min) para hacer el login del
    relevo en paralelo. Expone:
      .start()   arranca el hilo (1 sola vez)
      .ready     True cuando driver2 está lanzado Y su login fue VERIFICADO
      .error     excepción si algo falló (driver2 NO sirve → no cerrar driver1)
      .driver2   el driver listo
      .swapped   marca de que el relevo ya se consumió
    """
    def __init__(self):
        self._t = None
        self.driver2 = None
        self.ready = False
        self.error = None
        self.started = False
        self.swapped = False

    def _run(self):
        try:
            d = launch_owned_driver()              # visible + login (3 intentos)
            if not verify_logged_in(d):            # gate explícito
                raise RuntimeError('driver2 lanzado pero login NO verificado '
                                   '(header__text--loggedIn ausente)')
            self.driver2 = d
            self.ready = True
        except Exception as e:
            self.error = e

    def start(self):
        self.started = True
        self._t = threading.Thread(target=self._run, daemon=True, name='relevo')
        self._t.start()


# ── logging: stdout + archivo ────────────────────────────────────────────────
class Tee:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, 'a', buffering=1)
        self.stdout = sys.stdout
    def write(self, s):
        self.stdout.write(s)
        self.f.write(s)
    def flush(self):
        self.stdout.flush(); self.f.flush()


def log(msg):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {msg}')


# ── driver: propio vs attach ─────────────────────────────────────────────────
def launch_owned_driver():
    """Lanza navegador propio + login (con reintentos internos de login)."""
    log(f'lanzando navegador propio (headless={LIVE_HEADLESS})...')
    d = launch_navigator(FS_URL, headless=LIVE_HEADLESS)
    log('login...')
    login(d, email_=FS_EMAIL, password_=FS_PASSWORD)  # max_attempts=3 interno
    dismiss_cookies(d)
    log(f'driver propio listo — {d.current_url}')
    return d


def attach_driver():
    from driver_session import get_driver
    log('conectando al driver de desarrollo (get_driver)...')
    return get_driver()


def hotswap(old_driver):
    """
    Relevo en caliente: abre driver2 + login MIENTRAS driver1 sigue vivo;
    cuando driver2 está listo, cierra driver1 y devuelve driver2.
    Solo para drivers que este runner posee.
    """
    log('HOT-SWAP: abriendo driver de relevo (driver1 sigue activo)...')
    new_driver = launch_owned_driver()
    log('HOT-SWAP: relevo listo — cerrando driver1...')
    try:
        old_driver.quit()
    except Exception as e:
        log(f'HOT-SWAP: warning al cerrar driver1: {type(e).__name__}: {e}')
    write_live_driver_file(new_driver, owned=True)  # actualizar identificador
    log('HOT-SWAP: completado, continuando en driver2.')
    return new_driver


# ── resumen horario (dedup por (sport,name), último resultado) ───────────────
class HourlyTracker:
    def __init__(self):
        self._seen = {}  # (sport, name) -> (timestamp, match_info)

    def add(self, sport, match_info):
        self._seen[(sport, match_info['name'])] = (time.time(), match_info)

    def prune(self, window_s=3600):
        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if now - v[0] <= window_s}

    def by_sport(self):
        self.prune()
        out = {}
        for (sport, _name), (_ts, info) in self._seen.items():
            out.setdefault(sport, []).append(info)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--attach', action='store_true')
    ap.add_argument('--sports', nargs='+', default=['FOOTBALL'])
    ap.add_argument('--interval', type=int, default=60)
    ap.add_argument('--duration-min', type=int, default=0)
    ap.add_argument('--swap-rss-mb', type=float, default=0)
    ap.add_argument('--swap-age-min', type=float, default=0)
    ap.add_argument('--zero-cycles', type=int, default=2)
    ap.add_argument('--mem-interval', type=int, default=30)
    ap.add_argument('--measure-only', action='store_true')
    # Disparador de PRUEBA del relevo paralelo: tras el ciclo N se lanza driver2
    # (en hilo, durante la espera) y, una vez su login está VERIFICADO, se cierra
    # driver1 entre ciclos y se sigue en driver2. Funciona aunque driver1 sea
    # propio o attached. 0 = desactivado.
    ap.add_argument('--swap-after-cycle', type=int, default=0)
    args = ap.parse_args()

    ts = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    runner_log = os.path.join(ROOT, 'logs', f'live_runner_{ts}.log')
    mem_log = os.path.join(ROOT, 'logs', f'live_mem_{ts}.log')
    sys.stdout = Tee(runner_log)

    log('=' * 60)
    log('live_runner.py START')
    log(f'  sports={args.sports} interval={args.interval}s '
        f'attach={args.attach} measure_only={args.measure_only}')
    log(f'  duration_min={args.duration_min} '
        f'swap_rss_mb={args.swap_rss_mb} swap_age_min={args.swap_age_min}')
    log(f'  runner_log={runner_log}')
    log(f'  mem_log={mem_log}')
    log(f'  telegram_enabled={tg.enabled()}')
    log('=' * 60)

    # sampler de memoria — lee LIVE_DRIVER_FILE para medir SOLO el driver actual
    sampler = MemSampler(mem_log, interval=args.mem_interval, label='live',
                         pid_file=LIVE_DRIVER_FILE)

    swap_enabled = (not args.attach) and (not args.measure_only) \
        and (args.swap_rss_mb > 0 or args.swap_age_min > 0)
    if args.attach and (args.swap_rss_mb > 0 or args.swap_age_min > 0):
        log('[NOTE] --attach: hot-swap DESACTIVADO (no se cierra el driver de dev).')

    dict_sports_url = load_json('check_points/sports_url_m2.json')
    tracker = HourlyTracker()

    # arranque del driver
    if args.attach:
        driver = attach_driver()
    else:
        driver = launch_owned_driver()
    driver_started = time.time()

    # pid del geckodriver de driver1: propio → de su .service; attached → único
    # geckodriver vivo al arrancar (antes de lanzar el relevo).
    active_pid = gecko_pid(driver) or single_geckodriver_pid()

    # guardar identificador del driver y arrancar el sampler (mide ese driver)
    ident = write_live_driver_file(driver, owned=(not args.attach),
                                   pid_override=active_pid)
    log(f'driver1 id: geckodriver_pid={ident["geckodriver_pid"]} '
        f'session={ident["session_id"]}')
    if ident['geckodriver_pid'] is None:
        log('[NOTE] sin geckodriver_pid: el sampler medirá TODOS los geckodriver.')
    sampler.start()

    # relevo paralelo (modo prueba): se arma vacío y se dispara tras N ciclos
    relevo = RelevoThread()

    def log_mem(tag):
        """Loguea memoria en el MISMO log del runner (para verificar después)."""
        rss, n = (browser_tree_rss_mb(active_pid) if active_pid
                  else browser_tree_rss_mb())
        msg = f'  MEM[{tag}] driver_actual(pid={active_pid}) {rss:.0f}MB/{n}p'
        if relevo.started and not relevo.swapped and relevo.driver2 is not None:
            p2 = gecko_pid(relevo.driver2)
            rss2, n2 = browser_tree_rss_mb(p2)
            msg += f' | driver2(pid={p2}) {rss2:.0f}MB/{n2}p'
        rss_all, n_all = browser_tree_rss_mb()
        msg += f' | TOTAL {rss_all:.0f}MB/{n_all}p | sys_libre={system_available_mb():.0f}MB'
        log(msg)

    t_start = time.time()
    last_heartbeat = time.time()
    zero_streak = 0
    cycle = 0

    try:
        while True:
            cycle += 1
            current_date = datetime.now().date()
            cycle_matches = 0
            cycle_problem = None

            # ── RELEVO: solo ENTRE ciclos (driver1 nunca a mitad de ciclo) ──
            if relevo.started and not relevo.swapped:
                if relevo.ready:
                    log_mem('pre-swap')
                    old_pid = active_pid
                    log(f'RELEVO listo y login VERIFICADO → cerrando driver1 '
                        f'(pid={old_pid}) y pasando a driver2.')
                    try:
                        driver.quit()
                        log(f'driver1 (pid={old_pid}) cerrado.')
                    except Exception as e:
                        log(f'warning al cerrar driver1: {type(e).__name__}: {e}')
                    driver = relevo.driver2
                    active_pid = gecko_pid(driver)
                    write_live_driver_file(driver, owned=True, pid_override=active_pid)
                    driver_started = time.time()
                    relevo.swapped = True
                    log(f'AHORA en driver2 (pid={active_pid}). Solo 1 driver vivo.')
                    log_mem('post-swap')
                elif relevo.error is not None:
                    log(f'[PROBLEM] relevo falló, se mantiene driver1: '
                        f'{type(relevo.error).__name__}: {relevo.error}')
                    relevo.swapped = True  # no reintentar en esta prueba
                    if not args.measure_only:
                        tg.notify(f'⚠️ LIVE: relevo de driver falló: {relevo.error}')

            for sport in args.sports:
                try:
                    found = process_sport_live(driver, sport, current_date,
                                               dict_sports_url=dict_sports_url)
                    cycle_matches += len(found)
                    for m in found:
                        tracker.add(sport, m)
                except Exception as e:
                    cycle_problem = f'{sport}: {type(e).__name__}: {e}'
                    log(f'[PROBLEM] {cycle_problem}')

            # ── detección de problema ────────────────────────────────────────
            if cycle_matches == 0:
                zero_streak += 1
            else:
                zero_streak = 0

            log(f'ciclo {cycle}: {cycle_matches} partidos | zero_streak={zero_streak}')
            log_mem(f'ciclo{cycle}')

            # ── lanzar el relevo paralelo tras el ciclo N (modo prueba) ──────
            if (args.swap_after_cycle and cycle == args.swap_after_cycle
                    and not relevo.started):
                log(f'lanzando driver2 EN HILO durante la espera '
                    f'(relevo paralelo; driver1 sigue disponible)...')
                relevo.start()

            if not args.measure_only:
                if cycle_problem:
                    tg.notify(f'⚠️ LIVE problema en ciclo {cycle}: {cycle_problem}')
                elif zero_streak >= args.zero_cycles:
                    tg.notify(f'⚠️ LIVE: {zero_streak} ciclos consecutivos con 0 '
                              f'partidos/elementos (posible página rota). '
                              f'sports={args.sports}')

                # latido "todo OK" cada hora
                if time.time() - last_heartbeat >= 3600:
                    summary = tg.build_hourly_summary(tracker.by_sport())
                    tg.notify(summary)
                    last_heartbeat = time.time()

            # ── hot-swap por memoria/edad ────────────────────────────────────
            if swap_enabled:
                rss_mb, _n = browser_tree_rss_mb(gecko_pid(driver))
                age_min = (time.time() - driver_started) / 60
                reason = None
                if args.swap_rss_mb > 0 and rss_mb > args.swap_rss_mb:
                    reason = f'RSS={rss_mb:.0f}MB > {args.swap_rss_mb:.0f}MB'
                elif args.swap_age_min > 0 and age_min > args.swap_age_min:
                    reason = f'edad={age_min:.1f}min > {args.swap_age_min:.0f}min'
                if reason:
                    log(f'HOT-SWAP disparado: {reason}')
                    try:
                        driver = hotswap(driver)
                        driver_started = time.time()
                    except Exception as e:
                        log(f'[PROBLEM] hot-swap falló: {type(e).__name__}: {e}')
                        tg.notify(f'⚠️ LIVE: hot-swap falló: {type(e).__name__}: {e}')

            # ── fin por duración (Fase 0) ────────────────────────────────────
            if args.duration_min and (time.time() - t_start) >= args.duration_min * 60:
                log(f'duración {args.duration_min}min alcanzada — terminando.')
                break

            # espera entre ciclos
            time.sleep(max(0, args.interval))

    except KeyboardInterrupt:
        log('interrumpido por usuario (Ctrl+C).')
    finally:
        sampler.stop()
        log('live_runner.py END')
        # No cerramos el driver:
        #  - attach: es el driver de desarrollo (sagrado).
        #  - propio: se deja vivo para inspección/reuso; el cierre lo controla
        #    el hot-swap o el usuario.


if __name__ == '__main__':
    main()
