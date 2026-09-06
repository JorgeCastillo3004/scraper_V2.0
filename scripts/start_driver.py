"""
start_driver.py
---------------
Abre el browser UNA sola vez, hace login en FlashScore,
guarda la sesión en tmp/driver_session.json y se queda activo.

Uso:
    cd /home/jorge/work/scraper_V2.0
    source sports_env/bin/activate
    python scripts/start_driver.py

Dejar corriendo en background o en terminal separada.
Los scripts de prueba se reconectan a esta sesión sin abrir un browser nuevo.
"""

import sys, os, json, time, signal, argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from config import FS_EMAIL, FS_PASSWORD
try:
    from config import FIX_HEADLESS
except Exception:
    FIX_HEADLESS = False
from common_functions import launch_navigator, login, dismiss_cookies, ensure_login

# Sesión por defecto = driver de corrección. Con --session-file el MISMO script
# sirve para otros drivers (p.ej. el de live → tmp/live_driver.json).
SESSION_FILE = os.path.join(ROOT, 'tmp', 'driver_session.json')


def save_session(driver, session_file):
    try:
        executor_url = driver.command_executor._url
    except AttributeError:
        executor_url = driver.command_executor._client_config.remote_server_addr
    data = {
        'session_id':   driver.session_id,
        'executor_url': executor_url,
    }
    with open(session_file, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'[OK] Sesión guardada en: {session_file}')
    print(f'     session_id  : {data["session_id"]}')
    print(f'     executor_url: {data["executor_url"]}')


def main(session_file=SESSION_FILE, headless=FIX_HEADLESS, label='driver', lightweight=False, load_images=False):
    print('=' * 55)
    print(f'start_driver.py — iniciando browser ({label})')
    print('=' * 55)

    print(f'\n[1] Abriendo browser... (headless={headless}, lightweight={lightweight}, load_images={load_images})')
    driver = launch_navigator('https://www.flashscore.com', headless=headless,
                              lightweight=lightweight, load_images=load_images)

    try:
        dismiss_cookies(driver)            # cerrar consentimiento ANTES por si tapa el botón LOGIN
        print('[2] Sesión (reutiliza la guardada; solo loguea si hace falta)...')
        print(f'    modo: {ensure_login(driver, FS_EMAIL, FS_PASSWORD)}')
        dismiss_cookies(driver)
        print(f'    URL actual: {driver.current_url}')

        print('\n[3] Guardando sesión...')
        save_session(driver, session_file)
    except BaseException as e:
        # CLAVE: si el login/setup falla, cerrar el browser para NO dejar un Firefox
        # huérfano (antes la excepción saltaba el quit y se acumulaban drivers).
        print(f'\n[ERROR] Falló el setup/login ({type(e).__name__}: {e}). '
              'Cerrando el browser para no dejar driver huérfano...')
        try:
            os.remove(session_file)
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        raise

    print('\n[OK] Driver listo. Mantén este proceso activo.')
    print('     Ctrl+C para cerrar el browser.\n')

    def on_exit(sig, frame):
        print('\n[EXIT] Cerrando browser...')
        try:
            os.remove(session_file)
        except Exception:
            pass
        driver.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT,  on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    while True:
        time.sleep(5)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Abre un driver Firefox+login y mantiene la sesión viva.')
    p.add_argument('--session-file', default=SESSION_FILE,
                   help='JSON donde guardar la sesión (default: driver de corrección).')
    p.add_argument('--label', default='driver', help='Etiqueta para los logs.')
    p.add_argument('--lightweight', action='store_true',
                   help='Modo bajo consumo de RAM (sin imágenes, 1 proceso, sin caché disco).')
    p.add_argument('--load-images', dest='load_images', action='store_true',
                   help='Forzar carga de imágenes aunque sea lightweight (flujos de CREACIÓN '
                        'que descargan logos/fotos, p.ej. tenis).')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--headless',    dest='headless', action='store_true',  default=None)
    g.add_argument('--no-headless', dest='headless', action='store_false')
    args = p.parse_args()
    headless = FIX_HEADLESS if args.headless is None else args.headless
    main(session_file=args.session_file, headless=headless, label=args.label,
         lightweight=args.lightweight, load_images=args.load_images)
