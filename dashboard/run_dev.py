"""
dashboard/run_dev.py
────────────────────
Modo desarrollo: reinicia app.py automáticamente al detectar
cambios en cualquier archivo .py del proyecto.

Uso:
    cd /root/scraper_v3
    source <env>/bin/activate
    python dashboard/run_dev.py

Requiere: pip install watchdog
"""

import subprocess
import sys
import os
import time
import socket
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CMD   = [sys.executable, os.path.join(os.path.dirname(__file__), 'app.py')]
APP_PORT  = 8502

COOLDOWN = 1.5   # segundos entre reinicios (evita recargas múltiples al guardar)


def _kill_port(port: int):
    """Mata cualquier proceso que esté usando el puerto dado."""
    try:
        result = subprocess.run(
            ['fuser', '-k', f'{port}/tcp'],
            capture_output=True
        )
    except FileNotFoundError:
        pass  # fuser no disponible, ignorar


def _wait_port_free(port: int, timeout: float = 8.0):
    """Espera hasta que el puerto quede libre o se agote el timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return True   # puerto libre
        time.sleep(0.3)
    return False  # timeout


class RestartHandler(FileSystemEventHandler):
    def __init__(self, restart_fn):
        self._restart = restart_fn
        self._last    = 0

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith('.py'):
            return
        now = time.time()
        if now - self._last < COOLDOWN:
            return
        self._last = now
        rel = os.path.relpath(event.src_path, WATCH_DIR)
        print(f'\n[DEV] Cambio detectado: {rel}  → reiniciando...\n')
        self._restart()


def run():
    proc        = [None]
    first_start = [True]

    def start():
        if proc[0] and proc[0].poll() is None:
            proc[0].terminate()
            proc[0].wait()
        # Matar cualquier proceso huérfano en el puerto y esperar que quede libre
        _kill_port(APP_PORT)
        if not _wait_port_free(APP_PORT):
            print(f'[DEV] ⚠  Puerto {APP_PORT} sigue ocupado tras 8s — forzando arranque')
        env = os.environ.copy()
        if not first_start[0]:
            env['FLET_NO_BROWSER'] = '1'   # reinicios: no abrir nueva pestaña
        first_start[0] = False
        proc[0] = subprocess.Popen(APP_CMD, cwd=WATCH_DIR, env=env)

    def restart():
        start()

    start()

    observer = Observer()
    observer.schedule(RestartHandler(restart), path=WATCH_DIR, recursive=True)
    observer.start()

    print(f'[DEV] Observando cambios en: {WATCH_DIR}')
    print('[DEV] Ctrl+C para detener\n')

    try:
        while True:
            time.sleep(1)
            if proc[0] and proc[0].poll() is not None:
                print('[DEV] El proceso terminó. Esperando cambios para reiniciar...')
                # Espera al próximo cambio, no reinicia solo
    except KeyboardInterrupt:
        print('\n[DEV] Deteniendo...')
        observer.stop()
        if proc[0] and proc[0].poll() is None:
            proc[0].terminate()

    observer.join()


if __name__ == '__main__':
    run()
