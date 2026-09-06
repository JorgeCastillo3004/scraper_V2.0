import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))
sys.path.insert(0, os.path.join(_ROOT, 'scripts'))

from config import FS_EMAIL, FS_PASSWORD

from datetime import datetime
import argparse
import time
import json
from common_functions import *
from data_base import *
from milestone7 import *
from driver_session import get_driver, driver_tree_pss_mb, tree_pss_mb, relaunch_live_driver
from common_functions import ensure_login, dump_fs_session   # sesión reutilizable (sin re-login)

# ── Headless del driver propio (standalone) ───────────────────────────────────
# Lo manda config.py (LIVE_HEADLESS). Si config no lo define (instalación vieja),
# se infiere por DISPLAY: sin entorno gráfico (servidor) => headless obligatorio.
# Override puntual para pruebas: env LIVE_HEADLESS=1/0.
def _resolve_live_headless():
    env = os.environ.get('LIVE_HEADLESS')
    if env is not None:
        return env.strip().lower() in ('1', 'true', 'yes', 'on')
    try:
        from config import LIVE_HEADLESS as _cfg
        return bool(_cfg)
    except Exception:
        return not bool(os.environ.get('DISPLAY', ''))

LIVE_HEADLESS = _resolve_live_headless()

# ── Control de ejecución (pause / stop) ───────────────────────────────────────
_LOGS_DIR          = os.path.join(_ROOT, 'logs')
_CONTROL_FILE      = os.path.join(_LOGS_DIR, 'run_control_live.json')
_STATUS_FILE       = os.path.join(_LOGS_DIR, 'run_status_live.json')
_SPORTS_FILE       = os.path.join(_LOGS_DIR, 'run_sports_live.json')   # selección en caliente
_SCREENSHOTS_DIR   = os.path.join(_LOGS_DIR, 'screenshots', 'live', 'latest')

# Driver dedicado de Live gestionado por el panel (independiente del de corrección).
_LIVE_SESSION_FILE  = os.path.join(_ROOT, 'tmp', 'live_driver.json')
_LIVE_LAUNCHER_FILE = os.path.join(_ROOT, 'tmp', 'live_launcher.json')
# True  = el script creó su propio driver (lo cierra al salir).
# False = se reenganchó al driver del panel (NUNCA lo cierra; lo maneja el panel).
_OWN_DRIVER = True

# Umbral de memoria del driver live (MB). Si el árbol del driver supera esto, se
# recicla con HOT-SWAP ENTRE ciclos (nunca en medio de uno) — mantiene el consumo
# acotado y evita el OOM. Un ciclo de ~9 deportes crece ~1.5 GB (de ~1.2 a ~2.7 GB):
# con 3 GB el reciclaje cae cada 1-2 ciclos, que es lo buscado para correr fino en el
# servidor (11,9 GB compartidos con grafana/prometheus/loki), no una red de seguridad
# que solo salta en el extremo. Configurable con env DRIVER_MEM_LIMIT_MB.
MEM_LIMIT_MB = int(os.environ.get('DRIVER_MEM_LIMIT_MB', '3000'))

# Driver propio vivo (modo standalone). Lo actualiza el hot-swap para que el cierre
# final apunte SIEMPRE al driver actual y no al que ya se recicló (si no, el Firefox
# nuevo quedaba huérfano al salir del loop).
_CURRENT_OWN_DRIVER = None


def _live_mem_mb():
    """Memoria del árbol del driver live, medida donde corresponda según quién lo
    lanzó: el panel (launcher propio, tmp/live_launcher.json) o este mismo script
    (standalone del servidor: geckodriver + Firefox cuelgan de nuestro PID)."""
    if _OWN_DRIVER:
        return tree_pss_mb(os.getpid())
    return driver_tree_pss_mb(_LIVE_LAUNCHER_FILE)


def _hotswap_own_driver(old_driver):
    """Hot-swap del driver PROPIO (standalone, sin panel): levanta y verifica el
    navegador NUEVO y recién entonces cierra el viejo → nunca se queda sin driver.
    Si el nuevo falla (login/red), devuelve el viejo intacto."""
    nuevo = None
    try:
        try:
            ses = dump_fs_session(old_driver)      # el viejo sigue logueado: sesión fresca
        except Exception:
            ses = None                             # sin ella, ensure_login usa disco o loguea
        nuevo = _launch_own_driver(session=ses)
        _ = nuevo.current_url                      # verificación mínima: sesión viva
    except Exception as e:
        print('[RECICLAJE] hot-swap NO realizado (%s: %s) — se mantiene el driver actual.'
              % (type(e).__name__, e))
        if nuevo is not None:
            try:
                nuevo.quit()
            except Exception:
                pass
        return old_driver
    try:
        old_driver.quit()                          # el viejo solo muere con reemplazo verificado
    except Exception:
        pass
    global _CURRENT_OWN_DRIVER
    _CURRENT_OWN_DRIVER = nuevo
    return nuevo


def _heartbeat(sports=None, interval=None):
    """Refresca el estado del live ENTRE CICLOS.

    Sin esto, `run_status_live.json` conservaba la marca del arranque para siempre
    (verificado: 8 h corriendo y `updated_at` seguía en la hora de inicio), así que no
    servía para saber si el proceso estaba vivo o colgado — justo lo que el detector
    de staleness necesita mirar."""
    try:
        _write_status('running', sports, interval)
    except Exception:
        pass


def _maybe_recycle_live(driver):
    """Mide la memoria del árbol del driver live; si supera MEM_LIMIT_MB lo recicla
    con hot-swap y devuelve el driver nuevo. Funciona en los DOS modos: driver del
    panel (attached) y driver propio (standalone del servidor) — antes salía de una
    en modo propio, que es justo como corre el live del servidor, y por eso el
    Firefox crecía sin techo hasta el OOM."""
    _heartbeat()                 # latido: se llama entre ciclos, es el punto natural
    try:
        mb = _live_mem_mb()
    except Exception:
        return driver
    if mb < MEM_LIMIT_MB or mb <= 0:
        return driver
    ts = datetime.now().strftime('%H:%M:%S')
    print('[RECICLAJE %s] CAUSA=MEMORIA: árbol driver live=%.0f MB >= umbral %d MB → hot-swap…'
          % (ts, mb, MEM_LIMIT_MB))
    if _OWN_DRIVER:
        driver = _hotswap_own_driver(driver)
    else:
        driver = relaunch_live_driver(old_driver=driver)   # hot-swap: verifica el nuevo, cierra el viejo
    nueva = _live_mem_mb()
    print('[RECICLAJE %s] hot-swap completado — memoria ahora=%.0f MB.'
          % (datetime.now().strftime('%H:%M:%S'), nueva))
    return driver


def _launch_own_driver(session=None):
    """Navegador propio ya logueado. No pasa por el formulario si puede evitarlo:
    reutiliza la sesión de FlashScore (cookies + localStorage `lsid_*`), sea la del
    driver viejo en un hot-swap (`session`, la más fresca) o la de tmp/fs_session.json
    en un arranque en frío. Solo loguea de verdad si la sesión ya no sirve."""
    d = launch_navigator('https://www.flashscore.com', headless=LIVE_HEADLESS, lightweight=True)
    print('[INFO] Navegador listo — resolviendo sesión...')
    modo = ensure_login(d, FS_EMAIL, FS_PASSWORD, session=session)
    print('[INFO] Sesión lista (%s).' % modo)
    return d


def _close_own_driver(driver=None):
    """Cierra el driver PROPIO (jamás el del panel). Tras un hot-swap la referencia
    local del llamador puede ser la vieja, así que cierra también la que quedó viva
    en _CURRENT_OWN_DRIVER: sin esto un Firefox reciclado quedaba huérfano al salir."""
    global _CURRENT_OWN_DRIVER
    if not _OWN_DRIVER:
        return
    for d in {id(x): x for x in (driver, _CURRENT_OWN_DRIVER) if x is not None}.values():
        try:
            d.quit()
        except Exception:
            pass
    _CURRENT_OWN_DRIVER = None


def _acquire_driver():
    """Devuelve (driver, owned). Reengancha al driver live del panel si existe
    (tmp/live_driver.json); si no, crea uno propio con login (fallback)."""
    if os.path.exists(_LIVE_SESSION_FILE):
        try:
            d = get_driver(_LIVE_SESSION_FILE)
            print('[INFO] Reenganchado al driver de live del panel (no se cierra al terminar).')
            return d, False
        except Exception as e:
            print(f'[WARN] No se pudo reenganchar al driver de live ({type(e).__name__}: {e}); '
                  'creando uno propio.')
    print('[INFO] No hay driver de live del panel — lanzando navegador propio...')
    global _CURRENT_OWN_DRIVER
    _CURRENT_OWN_DRIVER = _launch_own_driver()
    return _CURRENT_OWN_DRIVER, True


def _save_screenshot(driver, label: str):
    os.makedirs(_SCREENSHOTS_DIR, exist_ok=True)
    png  = os.path.join(_SCREENSHOTS_DIR, 'live_0.png')
    meta = os.path.join(_SCREENSHOTS_DIR, 'live_0.json')
    try:
        original_size = driver.get_window_size()
        try:
            total_height = driver.execute_script('return document.body.scrollHeight')
            driver.set_window_size(original_size['width'], max(total_height, original_size['height']))
            driver.save_screenshot(png)
        finally:
            driver.set_window_size(original_size['width'], original_size['height'])
        with open(meta, 'w', encoding='utf-8') as f:
            json.dump({
                'label':       label,
                'captured_at': datetime.now().isoformat(),
                'url':         getattr(driver, 'current_url', ''),
                'image_url':   '/artifacts/screenshots/live/latest/live_0.png',
            }, f)
    except Exception:
        pass


def _write_control(command: str):
    os.makedirs(_LOGS_DIR, exist_ok=True)
    try:
        with open(_CONTROL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'command': command}, f)
    except Exception:
        pass


def _read_control() -> str:
    try:
        with open(_CONTROL_FILE, encoding='utf-8') as f:
            return json.load(f).get('command', 'none')
    except Exception:
        return 'none'


def _write_sports(sports: list, interval: int = None):
    os.makedirs(_LOGS_DIR, exist_ok=True)
    try:
        data = {'sports': sports, 'updated_at': datetime.now().isoformat()}
        if interval is not None:
            data['interval'] = interval   # siembra del intervalo (editable en caliente)
        with open(_SPORTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception:
        pass


def _read_sports():
    """Selección de deportes deseada (escrita por el panel). None si no hay archivo."""
    try:
        with open(_SPORTS_FILE, encoding='utf-8') as f:
            s = json.load(f).get('sports')
            return s if s else None
    except Exception:
        return None


def _read_interval():
    """Intervalo (segundos) deseado, escrito por el panel EN CALIENTE en el mismo
    archivo que los deportes. None si no hay -> se mantiene el del arranque."""
    try:
        with open(_SPORTS_FILE, encoding='utf-8') as f:
            iv = json.load(f).get('interval')
            return int(iv) if iv else None
    except Exception:
        return None


def _write_status(state: str, sports: list = None, interval: int = None):
    os.makedirs(_LOGS_DIR, exist_ok=True)
    try:
        with open(_STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'state':      state,
                'sports':     sports or [],
                'interval':   interval,
                'pid':        os.getpid(),   # para que el panel re-enganche tras reiniciar la API
                'updated_at': datetime.now().isoformat(),
            }, f)
    except Exception:
        pass


def _check_control(driver=None):
    """
    Comprueba el archivo de control en cada iteración del loop.
    - 'stop'  → cierra driver y lanza SystemExit
    - 'pause' → espera en bucle hasta recibir 'resume' o 'stop'
    - 'none'  → continúa normalmente
    """
    cmd = _read_control()

    if cmd == 'stop':
        print('[INFO] Comando stop recibido — cerrando limpiamente...')
        _close_own_driver(driver)         # nunca cierra el driver del panel
        _write_status('stopped')
        _write_control('none')
        raise SystemExit('Stop solicitado')

    if cmd == 'pause':
        print('[INFO] Pausado — esperando reanudación...')
        _write_status('paused')
        while True:
            time.sleep(2)
            cmd = _read_control()
            if cmd == 'resume':
                _write_control('none')
                _write_status('running')
                print('[INFO] Reanudado.')
                break
            if cmd == 'stop':
                print('[INFO] Stop durante pausa — cerrando...')
                _close_own_driver(driver)         # nunca cierra el driver del panel
                _write_status('stopped')
                _write_control('none')
                raise SystemExit('Stop solicitado durante pausa')


# ── Loop principal ─────────────────────────────────────────────────────────────

def main_live(sports: list, interval: int):
    print(f"[INFO] Iniciando live scraper...")
    print(f"[INFO] Deportes seleccionados: {', '.join(sports)}")
    print(f"[INFO] Intervalo entre ciclos: {interval}s")
    print(f"[INFO] Reciclado de driver por memoria: ACTIVO (umbral {MEM_LIMIT_MB} MB, entre ciclos)")
    retry_count = 0
    MAX_RETRIES = 10
    RETRY_DELAY = 30

    _write_control('none')
    _write_sports(sports, interval)       # siembra deportes + intervalo (editables en caliente)
    _write_status('running', sports, interval)

    global _OWN_DRIVER
    while True:
        driver = None
        try:
            _check_control()

            driver, _OWN_DRIVER = _acquire_driver()   # attach al driver del panel o crear propio
            _save_screenshot(driver, 'login_ready')
            print("[INFO] Driver listo — comenzando ciclo live...")
            retry_count = 0

            _check_control(driver)
            _write_status('running', sports, interval)

            live_games(
                driver,
                list_sports=sports,
                interval=interval,
                check_control=_check_control,
                save_screenshot=_save_screenshot,
                maybe_recycle=_maybe_recycle_live,
                sports_provider=_read_sports,
                interval_provider=_read_interval,
            )

        except SystemExit:
            break

        except Exception as e:
            retry_count += 1
            print(f'[RESTART {datetime.now():%H:%M:%S}] CAUSA=ERROR: {type(e).__name__}: {e} '
                  f'(intento {retry_count}/{MAX_RETRIES}) → re-engancha/recrea el driver')
            if retry_count >= MAX_RETRIES:
                print(f'[ERROR] main_live detenido tras {MAX_RETRIES} crashes consecutivos.')
                _write_status('error', sports, interval)
                break
            print(f'[INFO] Reiniciando en {RETRY_DELAY}s...')
            for _ in range(RETRY_DELAY // 2):
                time.sleep(2)
                try:
                    _check_control()
                except SystemExit:
                    return

        finally:
            # Solo cerrar si el driver es PROPIO; el del panel lo maneja el panel.
            _close_own_driver(driver)

    _write_status('stopped')
    print('[INFO] main_live finalizado.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Live scraper — milestone7')
    parser.add_argument(
        '--sports', nargs='+',
        default=['FOOTBALL'],
        help='Lista de deportes a procesar, e.g. --sports FOOTBALL BASKETBALL',
    )
    parser.add_argument(
        '--interval', type=int,
        default=60,
        help='Segundos entre ciclos de actualización (default: 60)',
    )
    args = parser.parse_args()
    main_live(sports=args.sports, interval=args.interval)
