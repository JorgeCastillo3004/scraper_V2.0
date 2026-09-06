#!/usr/bin/env python
"""
engine_runner.py — proceso MOTOR del scraper (servicio `scraper-engine`).

Único dueño de la ejecución de larga vida (ver
`documentacion/especificacion_ejecucion_permanente.md`). NO reimplementa lógica:
orquesta piezas que YA existen, en un proceso supervisado por systemd.

Responsabilidades:
  1. SCHEDULER — reusa `api.services.scheduler.start_scheduler()` (Noticias /
     fix_team_ids / LIVE_MISSING_REPAIR). El loop ya lee CONFIG.json en caliente
     y persiste su estado en logs/scheduler_*_state.json.
  2. LIVE — supervisa `main2.py` (mismo comando que lanza el panel vía
     process_manager.build_command('live', ...)). Si el live no da señales de
     vida (heartbeat por mtime del log), lo (re)lanza. NO lo mata al apagar el
     engine: el live debe sobrevivir a reinicios del engine (regla del proyecto)
     → en el próximo arranque el engine detecta el heartbeat fresco y NO duplica.
  3. ESTADO — escribe tmp/engine_status.json (heartbeat + última supervisión)
     para que el panel muestre el estado real (no un Popen local).

Reglas respetadas: nunca `pkill`/`kill` de firefox/gecko; el live se cierra solo
con su propio hot-swap. La API NO debe correr el scheduler en paralelo: arrancar
el panel con ENGINE_OWNS_SCHEDULER=1 (ver api/main.py).

⚠️ NO PROBADO end-to-end todavía: requiere espejo local arriba (sports_container)
y config.py apuntando a la BD LOCAL. NUNCA correr contra el remoto sin permiso.

Uso:
    ENGINE_OWNS_SCHEDULER=1 env_sports/bin/python -m scripts.engine_runner
"""
import os
import sys
import glob
import json
import time
import signal
import threading
from datetime import datetime

# Ejecutado como `python -m scripts.engine_runner` desde la raíz del proyecto:
# el paquete `api` y los scripts de raíz (main2.py) son importables.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import api.services.scheduler as sched          # noqa: E402
import api.services.process_manager as pm        # noqa: E402

# ── Config ───────────────────────────────────────────────────────────────────
LOGS_DIR        = os.path.join(ROOT, 'logs')
TMP_DIR         = os.path.join(ROOT, 'tmp')
STATUS_PATH     = os.path.join(TMP_DIR, 'engine_status.json')
LIVE_CFG_PATH   = os.path.join(LOGS_DIR, 'run_sports_live.json')

HEARTBEAT_SEC   = int(os.environ.get('ENGINE_HEARTBEAT_SEC', '15'))
# El live se considera VIVO si su log se tocó hace menos de N s. Holgura amplia
# (3× intervalo + margen) para no relanzar por una pausa normal de ciclo.
def _live_stale_threshold(interval: int) -> int:
    return max(180, interval * 3 + 60)

_stop = threading.Event()


def log(msg: str):
    print(f"[engine {datetime.now():%H:%M:%S}] {msg}", flush=True)


# ── Live: supervisión por heartbeat (mtime del log) ──────────────────────────
def _read_live_cfg() -> dict:
    """Deportes + intervalo deseados para el live (hot-config compartido con main2)."""
    try:
        with open(LIVE_CFG_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _newest_live_log_mtime():
    logs = glob.glob(os.path.join(LOGS_DIR, 'live_*.log'))
    if not logs:
        return None
    newest = max(logs, key=os.path.getmtime)
    return os.path.getmtime(newest)


def _live_alive(interval: int) -> bool:
    """Vivo si tmp/live_driver.json existe y el log se actualizó recientemente."""
    if not os.path.exists(os.path.join(TMP_DIR, 'live_driver.json')):
        return False
    mtime = _newest_live_log_mtime()
    if mtime is None:
        return False
    return (time.time() - mtime) < _live_stale_threshold(interval)


def _supervise_live():
    cfg      = _read_live_cfg()
    interval = int(cfg.get('interval', 60))
    sports   = cfg.get('sports') or ['FOOTBALL']
    if _live_alive(interval):
        return {'live': 'alive', 'sports': sports, 'interval': interval}
    # No da señales → (re)lanzar con el MISMO comando del panel (build_command).
    log(f"LIVE sin heartbeat → relanzando (sports={sports}, interval={interval}s)")
    res = pm.start_process('live', {'sports': sports, 'interval': interval})
    return {'live': 'relaunched', 'sports': sports, 'interval': interval,
            'launch': res}


# ── Estado para el panel ─────────────────────────────────────────────────────
def _write_status(extra: dict):
    os.makedirs(TMP_DIR, exist_ok=True)
    payload = {
        'heartbeat':  datetime.now().isoformat(),
        'pid':        os.getpid(),
        'scheduler':  sched.get_status(),
        **extra,
    }
    tmp = STATUS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(payload, f)
    os.replace(tmp, STATUS_PATH)   # rename atómico (R5 de la spec)


# ── Ciclo de vida ────────────────────────────────────────────────────────────
def _handle_signal(signum, _frame):
    log(f"señal {signum} recibida → apagando engine (el LIVE sigue vivo).")
    _stop.set()


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log("arrancando motor: scheduler + supervisión de LIVE.")
    # 1) Scheduler (su propio daemon thread; reusa pm.start_process, que es
    #    engine-safe: _broadcast se omite si no hay event loop asyncio).
    sched.start_scheduler()

    # 2) Loop de supervisión + heartbeat.
    try:
        while not _stop.is_set():
            try:
                live = _supervise_live()
                _write_status({'supervise': live})
            except Exception as e:                       # nunca tumbar el engine
                log(f"error en supervisión: {e}")
                try:
                    _write_status({'supervise': {'error': str(e)}})
                except Exception:
                    pass
            _stop.wait(HEARTBEAT_SEC)
    finally:
        # NO se detiene el live (debe sobrevivir al engine). Solo el scheduler.
        sched.stop_scheduler()
        log("scheduler detenido. Engine apagado.")


if __name__ == '__main__':
    main()
