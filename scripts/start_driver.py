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

import sys, os, json, time, signal

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from config import FS_EMAIL, FS_PASSWORD
try:
    from config import FIX_HEADLESS
except Exception:
    FIX_HEADLESS = False
from common_functions import launch_navigator, login, dismiss_cookies

SESSION_FILE = os.path.join(ROOT, 'tmp', 'driver_session.json')


def save_session(driver):
    try:
        executor_url = driver.command_executor._url
    except AttributeError:
        executor_url = driver.command_executor._client_config.remote_server_addr
    data = {
        'session_id':   driver.session_id,
        'executor_url': executor_url,
    }
    with open(SESSION_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'[OK] Sesión guardada en: {SESSION_FILE}')
    print(f'     session_id  : {data["session_id"]}')
    print(f'     executor_url: {data["executor_url"]}')


def main():
    print('=' * 55)
    print('start_driver.py — iniciando browser')
    print('=' * 55)

    print(f'\n[1] Abriendo browser... (headless={FIX_HEADLESS})')
    driver = launch_navigator('https://www.flashscore.com', headless=FIX_HEADLESS)

    print('[2] Login...')
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
    dismiss_cookies(driver)
    print(f'    URL actual: {driver.current_url}')

    print('\n[3] Guardando sesión...')
    save_session(driver)

    print('\n[OK] Driver listo. Mantén este proceso activo.')
    print('     Ctrl+C para cerrar el browser.\n')

    def on_exit(sig, frame):
        print('\n[EXIT] Cerrando browser...')
        try:
            os.remove(SESSION_FILE)
        except Exception:
            pass
        driver.quit()
        sys.exit(0)

    signal.signal(signal.SIGINT,  on_exit)
    signal.signal(signal.SIGTERM, on_exit)

    while True:
        time.sleep(5)


if __name__ == '__main__':
    main()
