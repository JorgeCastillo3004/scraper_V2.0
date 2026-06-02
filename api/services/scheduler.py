"""
News Scheduler (embebido en la API)
-----------------------------------
Hilo en segundo plano que ejecuta la **extracción de noticias cada N horas**,
según la configuración `EXTRACT_NEWS` de `check_points/CONFIG.json`. Se controla
100% desde el panel (pestaña Noticias): basta con guardar `ENABLED` + `EVERY_HOURS`.

Diseño:
  - Lee la config en CADA tick → los cambios desde el panel toman efecto sin
    reiniciar la API (en <= _CHECK_INTERVAL segundos).
  - Dispara el scraper reusando process_manager.start_process('news', ...),
    el MISMO camino que el botón "Start" del panel (escribe en la BD remota).
  - No corre si ENABLED=false, si EVERY_HOURS<=0, o si news ya está corriendo
    (no solapa ejecuciones).
  - Persiste last_run en logs/scheduler_news_state.json para que un reinicio de
    la API no reinicie el reloj (evita re-disparos en cada restart).
  - Al arrancar sin historial, la primera corrida se programa a futuro
    (N horas), no se dispara al instante.

Estado expuesto para la UI vía get_status(): enabled, every_hours, last_run,
next_run, last_error, news_running.
"""

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

from api.config import CONFIG_PATH, LOGS_DIR
from api.services import process_manager as pm
from api.services.database import get_sports_from_db

_CHECK_INTERVAL = 30          # segundos entre revisiones del reloj
_STATE_PATH = os.path.join(LOGS_DIR, 'scheduler_news_state.json')

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_state = {
    'last_run':   None,       # ISO str de la última ejecución disparada
    'next_run':   None,       # ISO str estimado de la próxima
    'last_error': None,       # último error al disparar (si lo hubo)
}


# ── Persistencia de last_run ──────────────────────────────────────────────────

def _load_state():
    try:
        with open(_STATE_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('last_run'):
            _state['last_run'] = data['last_run']
    except Exception:
        pass


def _save_state():
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(_STATE_PATH, 'w') as f:
            json.dump({'last_run': _state['last_run']}, f)
    except Exception:
        pass


# ── Lectura de config ─────────────────────────────────────────────────────────

def _read_news_cfg() -> dict:
    """Devuelve el bloque EXTRACT_NEWS de CONFIG.json (o {} si no existe)."""
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg.get('EXTRACT_NEWS', {}) or {}
    except Exception:
        return {}


def _resolve_sports(cfg: dict) -> list:
    """Deportes a extraer: los configurados, o TODOS los de la BD por defecto."""
    sports = cfg.get('SPORTS') or []
    if sports:
        return sports
    try:
        return get_sports_from_db()
    except Exception:
        return []


# ── Disparo de la extracción ──────────────────────────────────────────────────

def _run_news(cfg: dict) -> dict:
    params = {
        'sports': _resolve_sports(cfg),
        'days':   int(cfg.get('MAX_OLDER_DATE_ALLOWED', 31) or 31),
    }
    result = pm.start_process('news', params)
    if result.get('ok'):
        _state['last_run'] = datetime.now().isoformat()
        _state['last_error'] = None
        _save_state()
    else:
        _state['last_error'] = result.get('error')
    return result


# ── Loop principal ────────────────────────────────────────────────────────────

def _loop():
    # Ancla para la primera corrida cuando aún no hay historial: a futuro, no ya.
    base = datetime.now()
    while not _stop.is_set():
        cfg = _read_news_cfg()
        enabled = bool(cfg.get('ENABLED'))
        try:
            hours = float(cfg.get('EVERY_HOURS', 0) or 0)
        except (TypeError, ValueError):
            hours = 0

        if enabled and hours > 0:
            last = _state['last_run']
            last_dt = datetime.fromisoformat(last) if last else base
            next_dt = last_dt + timedelta(hours=hours)
            _state['next_run'] = next_dt.isoformat()
            if datetime.now() >= next_dt:
                # No solapar si la sección news ya está corriendo.
                if pm.get_status('news').get('status') != 'running':
                    _run_news(cfg)
        else:
            _state['next_run'] = None

        _stop.wait(_CHECK_INTERVAL)


# ── API pública ───────────────────────────────────────────────────────────────

def start_scheduler():
    global _thread
    if _thread and _thread.is_alive():
        return
    _load_state()
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name='news-scheduler')
    _thread.start()


def stop_scheduler():
    _stop.set()


def get_status() -> dict:
    cfg = _read_news_cfg()
    return {
        'enabled':      bool(cfg.get('ENABLED')),
        'every_hours':  cfg.get('EVERY_HOURS', 0),
        'last_run':     _state['last_run'],
        'next_run':     _state['next_run'],
        'last_error':   _state['last_error'],
        'news_running': pm.get_status('news').get('status') == 'running',
    }
