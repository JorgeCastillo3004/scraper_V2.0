"""
connect_driver.py
-----------------
Utilidad para reconectarse a un driver Selenium activo creado desde
el Jupyter Notebook (main_depuracion.ipynb) sin necesidad de reiniciar
el browser ni hacer login nuevamente.

Funcionamiento:
1. Detecta el proceso geckodriver activo via `pgrep` y extrae su puerto.
2. Localiza el archivo de conexión del kernel de Jupyter más reciente
   en ~/.local/share/jupyter/runtime/.
3. Se conecta al kernel via jupyter_client y ejecuta código para obtener
   el session_id y executor_url del driver activo.
4. Reconecta al browser existente usando WebDriver remoto, parcheando
   temporalmente el método `execute` para evitar crear una nueva sesión.

Uso:
    # Desde terminal:
    source /home/you/env/sports_env/bin/activate
    python connect_driver.py

    # Desde otro script Python:
    from connect_driver import get_active_driver
    driver = get_active_driver()
    print(driver.current_url)
"""

import subprocess
import glob
import time
import sys
import os

sys.path.insert(0, '/home/you/work_2026')


def get_geckodriver_port():
    """
    Busca el proceso geckodriver activo y retorna su puerto.
    Retorna None si no hay ninguno corriendo.
    """
    result = subprocess.run(['pgrep', '-a', 'geckodriver'], capture_output=True, text=True)
    for line in result.stdout.strip().split('\n'):
        if '--port' in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == '--port' and i + 1 < len(parts):
                    return parts[i + 1]
    return None


def get_latest_kernel_file():
    """
    Retorna la ruta al archivo JSON del kernel de Jupyter más reciente
    en el directorio de runtime de Jupyter.
    """
    runtime_dir = os.path.expanduser('~/.local/share/jupyter/runtime/')
    kernel_files = glob.glob(runtime_dir + 'kernel-*.json')
    if not kernel_files:
        return None
    # Ordenar por fecha de modificación, el más reciente primero
    return max(kernel_files, key=os.path.getmtime)


def get_session_from_kernel(kernel_file):
    """
    Se conecta al kernel de Jupyter activo y ejecuta código para
    obtener el session_id y executor_url del driver Selenium.

    Retorna un dict {'session_id': ..., 'executor_url': ...}
    o None si falla.
    """
    try:
        import jupyter_client
    except ImportError:
        print("ERROR: jupyter_client no está instalado en este entorno.")
        return None

    km = jupyter_client.BlockingKernelClient(connection_file=kernel_file)
    km.load_connection_file()
    km.start_channels()

    try:
        km.wait_for_ready(timeout=10)
    except Exception as e:
        print(f"ERROR: No se pudo conectar al kernel: {e}")
        km.stop_channels()
        return None

    # Código que se ejecuta dentro del kernel para obtener los datos del driver
    code = """
try:
    print('SESSION_ID:', driver.session_id)
    print('EXECUTOR_URL:', driver.command_executor._url)
except Exception as e:
    print('DRIVER_ERROR:', e)
"""
    km.execute(code)
    result = {}

    while True:
        try:
            msg = km.get_iopub_msg(timeout=8)
            if msg['msg_type'] == 'stream':
                text = msg['content']['text']
                for line in text.strip().split('\n'):
                    if line.startswith('SESSION_ID:'):
                        result['session_id'] = line.split(':', 1)[1].strip()
                    elif line.startswith('EXECUTOR_URL:'):
                        result['executor_url'] = line.split(':', 1)[1].strip()
                    elif line.startswith('DRIVER_ERROR:'):
                        print(f"ERROR en kernel: {line}")
                        return None
            elif msg['msg_type'] == 'status' and msg['content']['execution_state'] == 'idle':
                break
        except Exception:
            break

    km.stop_channels()
    return result if 'session_id' in result else None


def get_active_driver():
    """
    Función principal. Detecta y retorna el driver Selenium activo
    del Jupyter Notebook sin crear una nueva sesión de browser.

    Retorna el objeto WebDriver reconectado, o None si falla.
    """
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.firefox.options import Options

    # 1. Verificar que geckodriver está corriendo
    port = get_geckodriver_port()
    if not port:
        print("ERROR: No se encontró ningún proceso geckodriver activo.")
        print("Ejecuta primero las celdas del notebook main_depuracion.ipynb")
        return None
    print(f"Geckodriver detectado en puerto: {port}")

    # 2. Localizar el kernel de Jupyter más reciente
    kernel_file = get_latest_kernel_file()
    if not kernel_file:
        print("ERROR: No se encontró ningún kernel de Jupyter activo.")
        return None
    print(f"Kernel encontrado: {os.path.basename(kernel_file)}")

    # 3. Obtener session_id y executor_url desde el kernel
    session_info = get_session_from_kernel(kernel_file)
    if not session_info:
        print("ERROR: No se pudo obtener la sesión del driver desde el kernel.")
        print("Asegúrate de que las celdas del driver y login ya fueron ejecutadas.")
        return None

    session_id = session_info['session_id']
    executor_url = session_info['executor_url']
    print(f"Session ID: {session_id}")
    print(f"Executor URL: {executor_url}")

    # 4. Reconectar al driver existente sin crear nueva sesión
    # Se parchea temporalmente WebDriver.execute para interceptar
    # el comando "newSession" y retornar la sesión existente en su lugar.
    original_execute = WebDriver.execute

    def patched_execute(self, driver_command, params=None):
        if driver_command == "newSession":
            return {
                'success': 0,
                'value': {'sessionId': session_id, 'capabilities': {}},
                'sessionId': session_id
            }
        return original_execute(self, driver_command, params)

    WebDriver.execute = patched_execute
    options = Options()
    driver = WebDriver(command_executor=executor_url, options=options)
    WebDriver.execute = original_execute  # Restaurar método original
    driver.session_id = session_id

    # 5. Verificar conexión
    try:
        print(f"\nConectado exitosamente.")
        print(f"URL actual: {driver.current_url}")
        print(f"Título: {driver.title}")
    except Exception as e:
        print(f"ERROR al verificar conexión: {e}")
        return None

    return driver


if __name__ == '__main__':
    """
    Ejecución directa desde terminal para verificar la conexión.
    Útil para confirmar que el driver del notebook está accesible.
    """
    print("=" * 50)
    print("Conectando al driver Selenium activo...")
    print("=" * 50)
    driver = get_active_driver()
    if driver:
        print("\nDriver listo para usar.")
    else:
        print("\nNo se pudo conectar al driver.")
