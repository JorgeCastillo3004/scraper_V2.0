"""
Driver Manager (panel)
----------------------
Control del **driver Selenium dedicado** que usan las correcciones del panel
(sección Inconsistencias / fix_results). Lanza y detiene `scripts/start_driver.py`,
que abre su PROPIO Firefox, hace login en FlashScore y guarda la sesión en
`tmp/driver_session.json`. Los fixes (`fix_null_team_ids.py`) reusan esa sesión.

SEGURIDAD (reglas no negociables del proyecto):
  - "Matar driver" envía SIGTERM SOLO al proceso start_driver.py que lanzamos
    nosotros (PID guardado en tmp/driver_launcher.json). start_driver.py atiende
    la señal y hace driver.quit() de su PROPIO browser + borra el session file.
  - JAMÁS se hace pkill firefox/geckodriver: eso podría matar el navegador del
    usuario. Si el driver queda pesado/colgado, se usa el script dedicado
    (scripts/stop_process.py), no este botón.
  - Si ya hay un driver vivo, no se lanza un segundo (evita drivers en paralelo).

El modo headless lo define `FIX_HEADLESS` en config.py (local visible / server
headless) y lo aplica start_driver.py.
"""

import json
import os
import signal
import subprocess
import sys
from datetime import datetime

from api.config import PROJECT_ROOT

SESSION_FILE  = os.path.join(PROJECT_ROOT, 'tmp', 'driver_session.json')
LAUNCHER_FILE = os.path.join(PROJECT_ROOT, 'tmp', 'driver_launcher.json')
LAUNCH_LOG    = os.path.join(PROJECT_ROOT, 'tmp', 'logs', 'driver_launch.log')


def _read_launcher() -> dict:
    try:
        with open(LAUNCHER_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_launcher(data: dict):
    os.makedirs(os.path.dirname(LAUNCHER_FILE), exist_ok=True)
    with open(LAUNCHER_FILE, 'w') as f:
        json.dump(data, f)


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _fix_headless() -> bool:
    try:
        from config import FIX_HEADLESS
        return bool(FIX_HEADLESS)
    except Exception:
        return False


def status() -> dict:
    """Estado del driver dedicado: vivo si el launcher sigue corriendo."""
    info = _read_launcher()
    pid = info.get('pid')
    alive = _pid_alive(pid)
    session_exists = os.path.exists(SESSION_FILE)
    return {
        'alive': bool(alive and session_exists),
        'launcher_running': bool(alive),
        'session_ready': session_exists,
        'pid': pid if alive else None,
        'headless': info.get('headless'),
        'started_at': info.get('started_at'),
    }


def start() -> dict:
    """Lanza start_driver.py detached (si no hay uno vivo). No abre 2 drivers."""
    st = status()
    if st['launcher_running']:
        return {'ok': True, 'already_running': True, **st}

    # Limpiar session stale para que start_driver escriba una fresca.
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass

    os.makedirs(os.path.dirname(LAUNCH_LOG), exist_ok=True)
    env = {**os.environ, 'NO_RICH': '1', 'PYTHONUNBUFFERED': '1'}
    env.setdefault('DISPLAY', ':1')   # Firefox visible necesita display X

    try:
        log_file = open(LAUNCH_LOG, 'a')
        proc = subprocess.Popen(
            [sys.executable, 'scripts/start_driver.py'],
            stdout=log_file, stderr=subprocess.STDOUT,
            cwd=PROJECT_ROOT, env=env,
            start_new_session=True,   # setsid → sobrevive y se aísla del padre
        )
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo lanzar el driver: {e}'}

    _write_launcher({
        'pid': proc.pid,
        'started_at': datetime.now().isoformat(),
        'headless': _fix_headless(),
    })
    # El login puede tardar; la sesión aparece cuando start_driver la guarda.
    return {'ok': True, 'pid': proc.pid, 'session_ready': False,
            'note': 'Driver lanzándose; la sesión estará lista en ~10-40s (login).'}


def stop() -> dict:
    """SIGTERM SOLO al start_driver.py que lanzamos (cierre limpio, sin pkill)."""
    info = _read_launcher()
    pid = info.get('pid')
    if not _pid_alive(pid):
        # Nada vivo: limpiar artefactos para reflejar estado real.
        try:
            if os.path.exists(LAUNCHER_FILE):
                os.remove(LAUNCHER_FILE)
        except Exception:
            pass
        return {'ok': True, 'note': 'No había driver del panel vivo.'}

    try:
        # SIGTERM → start_driver.on_exit: driver.quit() (su propio Firefox) + rm session.
        os.kill(int(pid), signal.SIGTERM)
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo detener el driver (pid={pid}): {e}'}

    try:
        if os.path.exists(LAUNCHER_FILE):
            os.remove(LAUNCHER_FILE)
    except Exception:
        pass
    return {'ok': True, 'stopped_pid': pid}
