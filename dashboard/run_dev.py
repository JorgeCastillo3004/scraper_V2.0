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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_CMD   = [sys.executable, os.path.join(os.path.dirname(__file__), 'app.py')]

COOLDOWN = 1.5   # segundos entre reinicios (evita recargas múltiples al guardar)


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
    proc = [None]

    def start():
        if proc[0] and proc[0].poll() is None:
            proc[0].terminate()
            proc[0].wait()
        proc[0] = subprocess.Popen(APP_CMD, cwd=WATCH_DIR)

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
