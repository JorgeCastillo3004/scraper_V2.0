"""
driver_session.py
-----------------
Helper para reconectarse al driver activo sin abrir un browser nuevo.

Uso en cualquier script de prueba:
    from driver_session import get_driver
    driver = get_driver()
    print(driver.current_url)
"""

import sys, os, json, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

SESSION_FILE  = os.path.join(ROOT, 'tmp', 'driver_session.json')
LAUNCHER_FILE = os.path.join(ROOT, 'tmp', 'driver_launcher.json')
# Driver de Live (independiente del de corrección).
LIVE_SESSION_FILE  = os.path.join(ROOT, 'tmp', 'live_driver.json')
LIVE_LAUNCHER_FILE = os.path.join(ROOT, 'tmp', 'live_launcher.json')


def get_driver(session_file=SESSION_FILE):
    """
    Reconecta al browser activo usando la sesión guardada por start_driver.py.
    No abre un browser nuevo ni hace login.

    session_file: path del JSON de sesión a reusar. Default = driver de corrección
    (tmp/driver_session.json). El driver live pasa tmp/live_driver.json.
    """
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.firefox.options import Options

    if not os.path.exists(session_file):
        raise FileNotFoundError(
            f'No se encontró sesión activa en {session_file}\n'
            'Ejecuta primero: python scripts/start_driver.py'
        )

    with open(session_file) as f:
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


# ── Memoria del árbol del driver + reciclado ──────────────────────────────────
# Mide y recicla SOLO el árbol del driver del scraper (launcher start_driver.py +
# su geckodriver + su Firefox --marionette + content procs). NUNCA toca el Firefox
# del usuario (árbol aparte). Reusa la mecánica de los botones del panel
# (api/services/driver_manager: SIGTERM SOLO al launcher, jamás pkill firefox).

def _launcher_pid(launcher_file=LAUNCHER_FILE):
    try:
        with open(launcher_file) as f:
            return int(json.load(f).get('pid'))
    except Exception:
        return None


def _proc_children():
    import collections
    m = collections.defaultdict(list)
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/stat') as f:
                ppid = int(f.read().rsplit(')', 1)[1].split()[1])
            m[ppid].append(int(pid))
        except Exception:
            pass
    return m


def _descendants(root, m):
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        out.append(p)
        stack += m.get(p, [])
    return out


def tree_pss_mb(pid):
    """Memoria PSS (MB, reparte lo compartido) del árbol de procesos que cuelga de
    `pid` (el propio proceso incluido). Base de `driver_tree_pss_mb`; se usa directo
    cuando el driver NO lo lanzó el panel sino el propio script (live standalone del
    servidor), donde no hay launcher_file que consultar: ahí geckodriver + Firefox +
    sus content procs son descendientes del PID del script.
    Devuelve 0.0 si no se puede medir (para NO reciclar por una medición fallida)."""
    if not pid:
        return 0.0
    m = _proc_children()
    total_kb = 0
    for p in _descendants(pid, m):
        try:
            with open(f'/proc/{p}/smaps_rollup') as f:
                for ln in f:
                    if ln.startswith('Pss:'):
                        total_kb += int(ln.split()[1])
                        break
        except Exception:
            pass
    return total_kb / 1024.0


def driver_tree_pss_mb(launcher_file=LAUNCHER_FILE):
    """Memoria PSS (MB) del árbol del driver del scraper lanzado por el PANEL.
    `launcher_file` selecciona el driver a medir (corrección por defecto, o el de
    live con LIVE_LAUNCHER_FILE). Devuelve 0.0 si no se puede medir."""
    return tree_pss_mb(_launcher_pid(launcher_file))


def _relaunch(manager, session_file, timeout=120):
    """Recicla un driver del panel: lo DETIENE (libera la RAM del Firefox) y lanza
    uno NUEVO con login, esperando a que la sesión esté lista, y devuelve el driver
    reconectado. `manager` es la instancia de driver_manager (correction o live) y
    `session_file` su JSON de sesión. Lanza RuntimeError si no queda lista en `timeout`."""
    manager.stop()                             # SIGTERM al launcher → start_driver: quit() + rm session
    for _ in range(30):                        # esperar cierre del browser viejo
        if not os.path.exists(session_file):
            break
        time.sleep(0.5)

    manager.start()                            # lanza start_driver.py detached (con login)
    waited = 0.0
    while waited < timeout:                     # esperar a que la nueva sesión quede lista
        if os.path.exists(session_file):
            time.sleep(1.5)                     # margen para que termine de escribir el JSON
            try:
                return get_driver(session_file)
            except Exception:
                pass
        time.sleep(1.0)
        waited += 1.0
    raise RuntimeError('relaunch: la sesión nueva no quedó lista en %ss' % timeout)


def relaunch_driver(old_driver=None, timeout=120):
    """Recicla el driver de CORRECCIÓN con HOT-SWAP (igual que el de live): lanza +
    verifica el driver NUEVO (detached, start_new_session) ANTES de cerrar el viejo →
    NUNCA te quedás sin driver. Si el nuevo no loguea, mantiene el viejo intacto.

    Antes usaba `_relaunch` = stop()+start(): cerraba el driver y abría una VENTANA sin
    driver; en un chain por-liga el relanzado no sobrevivía al fin del proceso → quedaba
    'driver perdido' y las ligas siguientes fallaban. (2026-06-16)"""
    from api.services import driver_manager as dm
    res = dm.correction.hotswap(timeout=timeout)
    if res.get('ok'):
        return get_driver(SESSION_FILE)
    print('[RECICLAJE] hot-swap NO realizado (%s) — se mantiene el driver actual.'
          % res.get('error', '?'))
    return old_driver if old_driver is not None else get_driver(SESSION_FILE)


def relaunch_live_driver(old_driver=None, timeout=120):
    """Recicla el driver de LIVE con HOT-SWAP: lanza+verifica el nuevo ANTES de cerrar
    el viejo (mínimo uso de recursos, sin downtime). Si el swap es OK devuelve el
    driver nuevo re-enganchado; si falla (login del nuevo), devuelve old_driver — el
    viejo sigue vivo, nunca te quedás sin driver."""
    from api.services import driver_manager as dm
    res = dm.live.hotswap(timeout=timeout)
    if res.get('ok'):
        return get_driver(LIVE_SESSION_FILE)
    print('[RECICLAJE] hot-swap NO realizado (%s)' % res.get('error', '?'))
    return old_driver if old_driver is not None else get_driver(LIVE_SESSION_FILE)
