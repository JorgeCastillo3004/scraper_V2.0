"""
start_driver_no_login.py — alternativa a start_driver.py SIN login.

FlashScore cambió el flow de login (botón 'Continue with email' no aparece)
y todas las paginas que necesita el scraper (results, match, team, stats)
son publicas sin login.

Este script lanza el browser y solo acepta cookies. Guarda la session en
tmp/driver_session.json igual que start_driver.py.

Uso:
    cd /home/jorge/work/scraper_V2.0
    env_sports/bin/python scripts/start_driver_no_login.py
"""

import sys, os, json, time, signal

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from common_functions import launch_navigator, dismiss_cookies

SESSION_FILE = os.path.join(ROOT, 'tmp', 'driver_session.json')


def save_session(driver):
    try:
        executor_url = driver.command_executor._url
    except AttributeError:
        executor_url = driver.command_executor._client_config.remote_server_addr
    sid = driver.session_id
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    with open(SESSION_FILE, 'w') as f:
        json.dump({'session_id': sid, 'executor_url': executor_url}, f, indent=2)
    print(f'  session guardada: {SESSION_FILE}')
    print(f'    session_id: {sid}')
    print(f'    executor:   {executor_url}')


def main():
    print('=' * 55)
    print('start_driver_no_login.py — sin autenticacion')
    print('=' * 55)

    print('\n[1] Abriendo browser y cargando flashscore.com...')
    driver = launch_navigator('https://www.flashscore.com/', headless=False)
    time.sleep(2)

    print('\n[2] Aceptar cookies si aparece...')
    dismiss_cookies(driver)
    time.sleep(1)

    print('\n[3] Reducir zoom a 50% (compactacion DOM)...')
    try:
        driver.execute_script("document.body.style.zoom='50%'")
    except Exception:
        pass

    print(f'\n[4] Browser listo. current_url: {driver.current_url}')

    save_session(driver)

    print('\nDriver vivo. Para reusar desde otros scripts:')
    print('  from fix_null_team_ids import _reuse_driver_session')
    print('  d = _reuse_driver_session()')
    print('\nDeja el browser abierto (no llamar driver.quit()).')

    def on_exit(sig, frame):
        print('\n[EXIT] senal recibida — saliendo SIN cerrar el browser.')
        sys.exit(0)
    signal.signal(signal.SIGINT,  on_exit)
    signal.signal(signal.SIGTERM, on_exit)
    while True:
        time.sleep(30)


if __name__ == '__main__':
    main()
