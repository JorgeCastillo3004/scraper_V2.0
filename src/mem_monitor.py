"""
mem_monitor.py
==============
Medición de consumo de memoria del navegador del scraper (Fase 0 de
docs/mejoras_live.md) y soporte para el disparador del hot-swap.

Mide el RSS del **árbol completo** del navegador: geckodriver + firefox +
content procs (Web Content / Isolated Web Co). No depende de conocer el PID
exacto: localiza los geckodriver vivos y suma cada uno + sus descendientes.
"""

import os
import json
import time
import threading
from datetime import datetime

import psutil

# Procesos raíz del navegador controlado por Selenium
_ROOT_NAMES = ("geckodriver",)


def read_geckodriver_pid(pid_file):
    """
    Lee el identificador del driver guardado por quien lanzó el navegador
    (mismo patrón que tmp/driver_session.json): otro componente lee este archivo
    para medir/conectarse al driver CORRECTO, sin adivinar entre varios.

    Devuelve el geckodriver_pid (int) o None si el archivo no existe / no aplica.
    """
    if not pid_file:
        return None
    try:
        with open(pid_file) as f:
            data = json.load(f)
        pid = data.get('geckodriver_pid')
        return int(pid) if pid else None
    except Exception:
        return None


def _iter_browser_roots(root_pid=None):
    """
    Genera los procesos raíz a medir.

    - root_pid=None: todos los geckodriver vivos (comportamiento histórico).
    - root_pid=<pid>: SOLO ese proceso (el geckodriver que lanzó el runner),
      para aislar la medición de un driver concreto. Clave para Fase 0 (medir
      un driver fresco sin contar otros) y para el hot-swap (no sumar driver1 +
      driver2 mientras coexisten).
    """
    if root_pid is not None:
        try:
            yield psutil.Process(root_pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        return
    for p in psutil.process_iter(['pid', 'name']):
        try:
            name = (p.info['name'] or '').lower()
            if any(k in name for k in _ROOT_NAMES):
                yield p
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def single_geckodriver_pid():
    """
    Devuelve el PID del geckodriver vivo si hay EXACTAMENTE uno (caso típico al
    arrancar: el driver1 attached). Si hay 0 o >1, devuelve None (ambiguo).
    Sirve para que un driver attached (sin .service) pueda identificar su pid y
    el sampler mida solo su subárbol.
    """
    pids = [p.pid for p in _iter_browser_roots()]
    return pids[0] if len(pids) == 1 else None


def browser_tree_rss_mb(root_pid=None):
    """
    Suma el RSS (MB) del/los geckodriver + sus descendientes (firefox y content
    procs). Devuelve (rss_mb, n_procs).

    Si `root_pid` se pasa, mide SOLO el subárbol de ese geckodriver; si no, mide
    todos los geckodriver vivos.
    """
    seen = set()
    total = 0.0
    n = 0
    for root in _iter_browser_roots(root_pid):
        procs = [root]
        try:
            procs += root.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        for p in procs:
            if p.pid in seen:
                continue
            seen.add(p.pid)
            try:
                total += p.memory_info().rss / 1_048_576
                n += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    return total, n


def system_available_mb():
    """MemAvailable del sistema en MB."""
    return psutil.virtual_memory().available / 1_048_576


class MemSampler(threading.Thread):
    """
    Hilo que muestrea el RSS del árbol del navegador cada `interval` segundos y
    lo escribe en `log_path` (formato CSV simple). Sirve para la Fase 0 (medir y
    extrapolar el crecimiento) y para observar corridas largas.

    Línea: ISO_TS,elapsed_s,elapsed_min,rss_mb,n_procs,sys_avail_mb
    """

    def __init__(self, log_path, interval=30, label='live', pid_file=None):
        super().__init__(daemon=True)
        self.log_path = log_path
        self.interval = interval
        self.label = label
        # Si se pasa pid_file, en cada muestreo se lee de ahí el geckodriver_pid
        # del driver actual (sigue al driver tras un hot-swap) y se mide SOLO ese
        # subárbol. Si es None, se miden todos los geckodriver (modo histórico).
        self.pid_file = pid_file
        self._stop = threading.Event()
        self._t0 = None

    def stop(self):
        self._stop.set()

    def run(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self._t0 = time.time()
        with open(self.log_path, 'a', buffering=1) as f:
            f.write(f'# mem sampler label={self.label} interval={self.interval}s '
                    f'start={datetime.now().isoformat()}\n')
            f.write('iso_ts,elapsed_s,elapsed_min,rss_mb,n_procs,sys_avail_mb\n')
            while not self._stop.is_set():
                root_pid = read_geckodriver_pid(self.pid_file)
                rss_mb, n = browser_tree_rss_mb(root_pid)
                elapsed_s = time.time() - self._t0
                line = (f'{datetime.now().isoformat()},{elapsed_s:.0f},'
                        f'{elapsed_s/60:.2f},{rss_mb:.1f},{n},'
                        f'{system_available_mb():.0f}\n')
                f.write(line)
                # esperar en cortes de 1s para poder parar rápido
                waited = 0
                while waited < self.interval and not self._stop.is_set():
                    time.sleep(1)
                    waited += 1
