"""
driver_session.py
-----------------
Helper para reconectarse al driver activo sin abrir un browser nuevo.

Uso en cualquier script de prueba:
    from driver_session import get_driver
    driver = get_driver()
    print(driver.current_url)
"""

import sys, os, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

SESSION_FILE = os.path.join(ROOT, 'tmp', 'driver_session.json')


def get_driver():
    """
    Reconecta al browser activo usando la sesión guardada por start_driver.py.
    No abre un browser nuevo ni hace login.
    """
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.firefox.options import Options

    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            f'No se encontró sesión activa en {SESSION_FILE}\n'
            'Ejecuta primero: python scripts/start_driver.py'
        )

    with open(SESSION_FILE) as f:
        data = json.load(f)

    session_id   = data['session_id']
    executor_url = data['executor_url']
    # Selenium 4.4+: executor_url puede venir como http://127.0.0.1:PORT
    if not executor_url.startswith('http'):
        executor_url = 'http://' + executor_url

    # Patch temporal para evitar que Selenium abra una sesión nueva
    original_execute = WebDriver.execute

    def patched_execute(self, driver_command, params=None):
        if driver_command == 'newSession':
            return {
                'success': 0,
                'value': {'sessionId': session_id, 'capabilities': {}},
                'sessionId': session_id
            }
        return original_execute(self, driver_command, params)

    WebDriver.execute = patched_execute
    driver = WebDriver(command_executor=executor_url, options=Options())
    WebDriver.execute = original_execute
    driver.session_id = session_id

    print(f'[OK] Reconectado al browser.')
    print(f'     URL actual : {driver.current_url}')
    return driver
