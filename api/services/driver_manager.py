"""
Driver Manager (panel)
----------------------
Control de los **drivers Selenium dedicados** del panel. Lanza y detiene
`scripts/start_driver.py` (abre su PROPIO Firefox, login en FlashScore, guarda la
sesión en un JSON) y expone status/start/stop por cada driver.

Hay DOS drivers independientes, cada uno con su propia sesión y launcher:
  - **corrección** (Inconsistencias / fix_results) → tmp/driver_session.json
  - **live**       (Live Scores)                  → tmp/live_driver.json
Son independientes: pueden estar vivos a la vez sin pisarse.

SEGURIDAD (reglas no negociables del proyecto):
  - "Matar driver" envía SIGTERM SOLO al proceso start_driver.py que lanzamos
    nosotros (PID guardado en su launcher JSON). start_driver.py atiende la señal
    y hace driver.quit() de su PROPIO browser + borra el session file.
  - JAMÁS se hace pkill firefox/geckodriver: eso podría matar el navegador del
    usuario.
  - Si ya hay un driver vivo (de ese tipo), no se lanza un segundo.

El modo headless lo definen `FIX_HEADLESS` (corrección) y `LIVE_HEADLESS` (live)
en config.py y lo aplica start_driver.py.
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

from api.config import PROJECT_ROOT

# start_driver.py es un script del scraper → corre en el venv dedicado sports_env
# (no en el del panel). Fallback al intérprete de la API si no existe.
_SPORTS_ENV_PY = os.path.join(PROJECT_ROOT, 'sports_env', 'bin', 'python')
PYTHON = _SPORTS_ENV_PY if os.path.exists(_SPORTS_ENV_PY) else sys.executable


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _fix_headless() -> bool:
    # Seleccionable desde el panel: CONFIG.json → FIX_DRIVER_HEADLESS (si está, manda);
    # si no, cae al valor fijo de config.py (FIX_HEADLESS). Se aplica al próximo
    # (re)lanzamiento del driver de corrección.
    try:
        import json
        from api.config import CONFIG_PATH
        with open(CONFIG_PATH) as f:
            v = json.load(f).get('FIX_DRIVER_HEADLESS', None)
        if v is not None:
            return bool(v)
    except Exception:
        pass
    try:
        from config import FIX_HEADLESS
        return bool(FIX_HEADLESS)
    except Exception:
        return False


def _live_headless() -> bool:
    try:
        from config import LIVE_HEADLESS
        return bool(LIVE_HEADLESS)
    except Exception:
        return False


class DriverManager:
    """Maneja un driver dedicado (start_driver.py) identificado por sus archivos.

    session_file  : JSON con session_id/executor_url (lo escribe start_driver.py).
    launcher_file : JSON con el pid del proceso start_driver.py que lanzamos.
    launch_log    : log de la corrida de start_driver.py.
    headless_fn   : callable → bool (FIX_HEADLESS o LIVE_HEADLESS).
    note_label    : etiqueta para los mensajes ('de corrección' / 'live').
    """

    def __init__(self, *, session_file, launcher_file, launch_log,
                 headless_fn, note_label, lightweight=False):
        self.session_file  = session_file
        self.launcher_file = launcher_file
        self.launch_log    = launch_log
        self.headless_fn   = headless_fn
        self.note_label    = note_label
        self.lightweight   = lightweight   # modo bajo consumo de RAM (driver de live)

    def _base_cmd(self, session_file, label_suffix=''):
        headless = self.headless_fn()
        cmd = [
            PYTHON, 'scripts/start_driver.py',
            '--session-file', session_file,
            '--label', self.note_label + label_suffix,
            '--headless' if headless else '--no-headless',
        ]
        if self.lightweight:
            cmd.append('--lightweight')
        return cmd

    def _read_launcher(self) -> dict:
        try:
            with open(self.launcher_file) as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_launcher(self, data: dict):
        os.makedirs(os.path.dirname(self.launcher_file), exist_ok=True)
        with open(self.launcher_file, 'w') as f:
            json.dump(data, f)

    def status(self) -> dict:
        """Estado del driver: vivo si el launcher sigue corriendo y hay sesión."""
        info = self._read_launcher()
        pid = info.get('pid')
        alive = _pid_alive(pid)
        session_exists = os.path.exists(self.session_file)
        return {
            'alive': bool(alive and session_exists),
            'launcher_running': bool(alive),
            'session_ready': session_exists,
            'pid': pid if alive else None,
            'headless': info.get('headless'),
            'started_at': info.get('started_at'),
        }

    def start(self) -> dict:
        """Lanza start_driver.py detached (si no hay uno vivo). No abre 2 drivers."""
        st = self.status()
        if st['launcher_running']:
            return {'ok': True, 'already_running': True, **st}

        headless = self.headless_fn()

        # Limpiar session stale para que start_driver escriba una fresca.
        try:
            if os.path.exists(self.session_file):
                os.remove(self.session_file)
        except Exception:
            pass

        os.makedirs(os.path.dirname(self.launch_log), exist_ok=True)
        env = {**os.environ, 'NO_RICH': '1', 'PYTHONUNBUFFERED': '1'}
        env.setdefault('DISPLAY', ':1')   # Firefox visible necesita display X

        cmd = self._base_cmd(self.session_file)
        try:
            log_file = open(self.launch_log, 'a')
            proc = subprocess.Popen(
                cmd,
                stdout=log_file, stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT, env=env,
                start_new_session=True,   # setsid → sobrevive y se aísla del padre
            )
        except Exception as e:
            return {'ok': False, 'error': f'No se pudo lanzar el driver: {e}'}

        self._write_launcher({
            'pid': proc.pid,
            'started_at': datetime.now().isoformat(),
            'headless': headless,
        })
        return {'ok': True, 'pid': proc.pid, 'session_ready': False,
                'note': f'Driver {self.note_label} lanzándose; la sesión estará lista en ~10-40s (login).'}

    def _rm(self, path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _cleanup_files(self):
        # Borra launcher y session oficial (tras hot-swap el proceso puede tener su
        # session en un temporal, así que limpiamos la oficial explícitamente).
        self._rm(self.launcher_file)
        self._rm(self.session_file)

    def stop(self) -> dict:
        """SIGTERM SOLO al start_driver.py que lanzamos (cierre limpio, sin pkill)."""
        info = self._read_launcher()
        pid = info.get('pid')
        if not _pid_alive(pid):
            self._cleanup_files()
            return {'ok': True, 'note': f'No había driver {self.note_label} vivo.'}

        try:
            # SIGTERM → start_driver.on_exit: driver.quit() (su Firefox) + rm session.
            os.kill(int(pid), signal.SIGTERM)
        except Exception as e:
            return {'ok': False, 'error': f'No se pudo detener el driver (pid={pid}): {e}'}

        self._cleanup_files()
        return {'ok': True, 'stopped_pid': pid}

    def hotswap(self, timeout=120) -> dict:
        """Relevo EN CALIENTE (mínimo uso de recursos): lanza un driver NUEVO a un
        session file TEMPORAL, espera a que loguee, y RECIÉN AHÍ cierra el VIEJO y
        promueve el nuevo. Si el nuevo NO loguea, mata el temporal y deja el VIEJO
        intacto (nunca te quedás sin driver). Tras un swap OK queda UN solo driver
        vivo (el viejo se cierra de inmediato); el solapamiento de 2 drivers dura solo
        lo que tarda el login del nuevo."""
        headless = self.headless_fn()
        # session temporal ÚNICO (evita choques entre relevos sucesivos).
        tmp_session = '%s.relevo_%s' % (self.session_file, datetime.now().strftime('%H%M%S%f'))
        os.makedirs(os.path.dirname(self.launch_log), exist_ok=True)
        env = {**os.environ, 'NO_RICH': '1', 'PYTHONUNBUFFERED': '1'}
        env.setdefault('DISPLAY', ':1')
        cmd = self._base_cmd(tmp_session, '-relevo')
        try:
            log_file = open(self.launch_log, 'a')
            new_proc = subprocess.Popen(
                cmd, stdout=log_file, stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT, env=env, start_new_session=True)
        except Exception as e:
            return {'ok': False, 'kept_old': True, 'error': f'no se pudo lanzar el relevo: {e}'}

        # 1) Esperar a que el NUEVO loguee (aparezca su session) o muera (login falló).
        ready = False
        waited = 0.0
        while waited < timeout:
            if os.path.exists(tmp_session):
                ready = True
                break
            if new_proc.poll() is not None:
                self._rm(tmp_session)
                return {'ok': False, 'kept_old': True,
                        'error': 'el relevo murió antes de loguear (login falló); se mantiene el viejo'}
            time.sleep(1.0)
            waited += 1.0
        if not ready:
            try: os.kill(new_proc.pid, signal.SIGTERM)
            except Exception: pass
            self._rm(tmp_session)
            return {'ok': False, 'kept_old': True,
                    'error': f'el relevo no logueó en {int(timeout)}s; se mantiene el viejo'}

        # 2) NUEVO listo → CERRAR el VIEJO (libera recursos) y esperar que muera.
        old_pid = self._read_launcher().get('pid')
        if _pid_alive(old_pid):
            try: os.kill(int(old_pid), signal.SIGTERM)
            except Exception: pass
            for _ in range(30):
                if not _pid_alive(old_pid):
                    break
                time.sleep(0.5)

        # 3) Promover el nuevo: su sesión pasa a ser la oficial + actualizar launcher.
        try:
            with open(tmp_session) as f:
                content = f.read()
            with open(self.session_file, 'w') as f:
                f.write(content)
        except Exception as e:
            return {'ok': False, 'kept_old': False, 'error': f'no se pudo promover el relevo: {e}'}
        self._write_launcher({
            'pid': new_proc.pid,
            'started_at': datetime.now().isoformat(),
            'headless': headless,
        })
        return {'ok': True, 'pid': new_proc.pid, 'stopped_old': old_pid}


# ── Instancias: corrección (Inconsistencias) y live (Live Scores) ────────────
_TMP  = os.path.join(PROJECT_ROOT, 'tmp')
_LOGS = os.path.join(_TMP, 'logs')

correction = DriverManager(
    session_file  = os.path.join(_TMP, 'driver_session.json'),
    launcher_file = os.path.join(_TMP, 'driver_launcher.json'),
    launch_log    = os.path.join(_LOGS, 'driver_launch.log'),
    headless_fn   = _fix_headless,
    note_label    = 'de corrección',
    lightweight   = True,   # 2026-06-16: scraping solo necesita texto → sin imágenes, menos RAM, recicla menos
)

live = DriverManager(
    session_file  = os.path.join(_TMP, 'live_driver.json'),
    launcher_file = os.path.join(_TMP, 'live_launcher.json'),
    launch_log    = os.path.join(_LOGS, 'live_driver_launch.log'),
    headless_fn   = _live_headless,
    note_label    = 'live',
    lightweight   = True,   # driver de live en modo bajo consumo de RAM
)

# Compat: el router /api/driver/* y driver_session.relaunch_driver usan el driver
# de corrección por estas funciones de módulo (se mantienen sin cambios externos).
SESSION_FILE  = correction.session_file
LAUNCHER_FILE = correction.launcher_file
LAUNCH_LOG    = correction.launch_log


def status() -> dict:
    return correction.status()


def start() -> dict:
    return correction.start()


def stop() -> dict:
    return correction.stop()
