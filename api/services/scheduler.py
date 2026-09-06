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
from api.services import driver_manager
from api.services.database import (
    get_sports_from_db, get_inconsistencias_summary, get_pending_minus_one_leagues,
)

_CHECK_INTERVAL = 30          # segundos entre revisiones del reloj
_STATE_PATH = os.path.join(LOGS_DIR, 'scheduler_news_state.json')
_FIX_STATE_PATH = os.path.join(LOGS_DIR, 'scheduler_fix_state.json')

# Categorías de inconsistencia que repara fix_null_team_ids (sección fix_results).
_FIX_CATEGORIES = ('fk_roto_team', 'detail_no_score')

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_state = {
    'last_run':   None,       # ISO str de la última ejecución disparada
    'next_run':   None,       # ISO str estimado de la próxima
    'last_error': None,       # último error al disparar (si lo hubo)
}

# Estado del trigger diario de corrección de team_id inexistente (Inconsistencias).
_fix_state = {
    'last_run':      None,    # ISO str de la última corrida disparada
    'next_run':      None,    # ISO str estimado de la próxima
    'last_error':    None,    # último error al disparar (si lo hubo)
    'last_leagues':  None,    # nº de ligas resueltas en la última corrida
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


def _load_fix_state():
    try:
        with open(_FIX_STATE_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get('last_run'):
            _fix_state['last_run'] = data['last_run']
    except Exception:
        pass


def _save_fix_state():
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(_FIX_STATE_PATH, 'w') as f:
            json.dump({'last_run': _fix_state['last_run']}, f)
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


# ── Corrección diaria de team_id inexistente (Inconsistencias) ───────────────
#
# Bloque FIX_TEAM_IDS de CONFIG.json (editable desde el panel, sin reiniciar):
#   ENABLED   : bool      → activa el disparo diario
#   AT_HOUR   : "HH:MM"    → hora local del disparo (1×/día)
#   APPLY     : bool       → escribe en BD (false = dry-run, recomendado al probar)
#   EXCLUDE   : ["SPORT/KEY", ...]  → ligas a saltar (opcional)
#
# Modo SIEMPRE dinámico: a la hora del disparo consulta el resumen de
# inconsistencias y ataca TODAS las ligas mapeables con team_id inexistente.
# Reusa el driver de CORRECCIÓN (tmp/driver_session.json) — NUNCA toca el de live.

def _read_fix_cfg() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        return cfg.get('FIX_TEAM_IDS', {}) or {}
    except Exception:
        return {}


def _resolve_fix_leagues(cfg: dict) -> list:
    """Modo dinámico: ligas mapeables con team_id inexistente, según el resumen.

    Devuelve [{'sport': sport_key, 'key': league_key}, ...] sin duplicados y
    excluyendo las de cfg['EXCLUDE'] (formato 'SPORT/KEY')."""
    exclude = set(cfg.get('EXCLUDE') or [])
    summary = get_inconsistencias_summary(fresh=True)
    by_league = summary.get('by_league', {}) or {}
    seen, leagues = set(), []
    for cat in _FIX_CATEGORIES:
        for r in by_league.get(cat, []) or []:
            if not r.get('mappable'):
                continue
            sk, lk = r.get('sport_key'), r.get('league_key')
            if not (sk and lk):
                continue
            spec = f'{sk}/{lk}'
            if spec in exclude or (sk, lk) in seen:
                continue
            seen.add((sk, lk))
            leagues.append({'sport': sk, 'key': lk})
    return leagues


def _ensure_correction_driver(timeout: float = 90.0) -> bool:
    """Garantiza un driver de corrección vivo (headless según FIX_HEADLESS).

    Si no hay, lo lanza vía driver_manager (NO toca el de live) y espera a que
    la sesión esté lista. Devuelve True si quedó vivo."""
    st = driver_manager.correction.status()
    if st.get('alive'):
        return True
    driver_manager.correction.start()
    waited = 0.0
    while waited < timeout and not _stop.is_set():
        if driver_manager.correction.status().get('alive'):
            return True
        _stop.wait(2.0)
        waited += 2.0
    return driver_manager.correction.status().get('alive', False)


def _run_fix(cfg: dict) -> dict:
    """Resuelve ligas, asegura driver y dispara fix_results (no solapa)."""
    if pm.get_status('fix_results').get('status') == 'running':
        return {'ok': False, 'error': 'fix_results ya está corriendo'}

    # Marcar la corrida del día ANTES de trabajar: aunque no haya nada que hacer
    # o falle, no se reintenta en bucle el mismo día.
    _fix_state['last_run'] = datetime.now().isoformat()
    _save_fix_state()

    try:
        leagues = _resolve_fix_leagues(cfg)
    except Exception as e:
        _fix_state['last_error'] = f'resolviendo ligas: {e}'
        _fix_state['last_leagues'] = 0
        return {'ok': False, 'error': _fix_state['last_error']}

    _fix_state['last_leagues'] = len(leagues)
    if not leagues:
        _fix_state['last_error'] = None
        return {'ok': True, 'note': 'sin ligas con team_id inexistente; nada que hacer'}

    if not _ensure_correction_driver():
        _fix_state['last_error'] = 'no se pudo levantar el driver de corrección'
        return {'ok': False, 'error': _fix_state['last_error']}

    params = {'leagues': leagues, 'apply': bool(cfg.get('APPLY'))}
    result = pm.start_process('fix_results', params)
    if result.get('ok'):
        _fix_state['last_error'] = None
    else:
        _fix_state['last_error'] = result.get('error')
    return result


def _fix_due(cfg: dict, now: datetime) -> bool:
    """True si toca disparar hoy: hora alcanzada y no se corrió aún hoy."""
    try:
        hh, mm = (cfg.get('AT_HOUR') or '04:00').split(':')
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, TypeError):
        return False
    if now < target:
        return False
    last = _fix_state['last_run']
    if last:
        try:
            if datetime.fromisoformat(last).date() >= now.date():
                return False   # ya se corrió hoy
        except ValueError:
            pass
    return True


def _next_fix_run(cfg: dict, now: datetime) -> Optional[str]:
    try:
        hh, mm = (cfg.get('AT_HOUR') or '04:00').split(':')
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    except (ValueError, TypeError):
        return None
    ran_today = False
    last = _fix_state['last_run']
    if last:
        try:
            ran_today = datetime.fromisoformat(last).date() >= now.date()
        except ValueError:
            pass
    if now >= target or ran_today:
        target = target + timedelta(days=1)
    return target.isoformat()


def _fix_tick(now: datetime):
    cfg = _read_fix_cfg()
    if not bool(cfg.get('ENABLED')):
        _fix_state['next_run'] = None
        return
    _fix_state['next_run'] = _next_fix_run(cfg, now)
    if _fix_due(cfg, now):
        _run_fix(cfg)


# ── Auto-reparación de inconsistencias del LIVE (live-missing) ────────────────
# El live escribe en check_points/live_missing_leagues.json las ligas que ve en vivo
# pero NO están en la BD (DB-SKIP). Si LIVE_MISSING_REPAIR está ENABLED, este tick
# cada EVERY_MINUTES corre crear_fixtures --today para las ligas pendientes que YA
# están en leagues_info → crea los partidos faltantes del día. Una sección
# extract_fixtures por corrida (un deporte); rota entre deportes en sucesivas corridas.
_LM_STATE_PATH = os.path.join(LOGS_DIR, 'scheduler_lm_state.json')
_lm_state = {'last_run': None, 'next_run': None, 'last_error': None, 'last_leagues': 0}


def _load_lm_state():
    try:
        with open(_LM_STATE_PATH) as f:
            _lm_state['last_run'] = json.load(f).get('last_run')
    except Exception:
        pass


def _save_lm_state():
    try:
        with open(_LM_STATE_PATH, 'w') as f:
            json.dump({'last_run': _lm_state['last_run']}, f)
    except Exception:
        pass


def _read_lm_cfg() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f).get('LIVE_MISSING_REPAIR', {}) or {}
    except Exception:
        return {}


def _lm_due(cfg: dict, now: datetime) -> bool:
    try:
        every = int(cfg.get('EVERY_MINUTES') or 60)
    except (TypeError, ValueError):
        every = 60
    if every <= 0:
        return False
    last = _lm_state['last_run']
    if not last:
        return True
    try:
        return (now - datetime.fromisoformat(last)).total_seconds() >= every * 60
    except ValueError:
        return True


def _next_lm_run(cfg: dict, now: datetime) -> Optional[str]:
    try:
        every = int(cfg.get('EVERY_MINUTES') or 60)
    except (TypeError, ValueError):
        every = 60
    base = now
    if _lm_state['last_run']:
        try:
            base = datetime.fromisoformat(_lm_state['last_run'])
        except ValueError:
            base = now
    return (base + timedelta(minutes=max(1, every))).isoformat()


def _run_lm_repair(cfg: dict) -> dict:
    """Crea los partidos faltantes del día para las ligas PENDIENTES del live (solo
    las ya registradas en leagues_info). Una corrida = un deporte (extract_fixtures
    es single-instance). No solapa; reusa el driver de corrección. NUNCA DELETE."""
    from api.services import live_missing as lm
    if pm.get_status('extract_fixtures').get('status') == 'running':
        return {'ok': False, 'error': 'extract_fixtures ya está corriendo'}
    _lm_state['last_run'] = datetime.now().isoformat()
    _save_lm_state()
    try:
        items = lm.get_live_missing().get('items', [])
    except Exception as e:
        _lm_state['last_error'] = f'leyendo live-missing: {e}'
        return {'ok': False, 'error': _lm_state['last_error']}
    pend = [it for it in items
            if it.get('status') == 'pending' and it.get('in_leagues_info')
            and it.get('sport_key') and it.get('league_key')]
    if not pend:
        _lm_state['last_error'] = None
        _lm_state['last_leagues'] = 0
        return {'ok': True, 'note': 'sin live-missing pendientes (in_leagues_info)'}
    by_sport: dict = {}
    for it in pend:
        by_sport.setdefault(it['sport_key'], []).append(
            {'sport': it['sport_key'], 'key': it['league_key']})
    sport = next(iter(by_sport))
    leagues = by_sport[sport]
    if not _ensure_correction_driver():
        _lm_state['last_error'] = 'no se pudo levantar el driver de corrección'
        return {'ok': False, 'error': _lm_state['last_error']}
    _lm_state['last_leagues'] = len(leagues)
    result = pm.start_process('extract_fixtures',
                              {'leagues': leagues, 'today': True,
                               'apply': bool(cfg.get('APPLY', True))})
    _lm_state['last_error'] = None if result.get('ok') else result.get('error')
    return result


def _lm_tick(now: datetime):
    cfg = _read_lm_cfg()
    if not bool(cfg.get('ENABLED')):
        _lm_state['next_run'] = None
        return
    _lm_state['next_run'] = _next_lm_run(cfg, now)
    if _lm_due(cfg, now):
        _run_lm_repair(cfg)


# ── Auto-completación de partidos en score=-1 (residuo del LIVE) ──────────────
# El LIVE completa el score de lo que ve en su ciclo (~60s), pero si un partido
# termina ENTRE dos ciclos y FlashScore lo saca de la vista live, queda con
# score=-1 y fecha pasada. Esos "pasados con -1" son justo lo que el live no
# alcanzó a cerrar. Si PENDING_COMPLETE está ENABLED, este tick cada EVERY_MINUTES
# corre update_pending_matches (--mode rapido) sobre TODAS las ligas mapeables con
# -1, leyendo el resultado final de la página de results de cada liga. Reusa el
# driver de corrección (independiente del de Live), single-instance, sin solapar.
# NUNCA DELETE (solo UPDATE score+status). Default OFF; APPLY configurable.
_PC_STATE_PATH = os.path.join(LOGS_DIR, 'scheduler_pc_state.json')
_pc_state = {'last_run': None, 'next_run': None, 'last_error': None, 'last_leagues': 0}


def _load_pc_state():
    try:
        with open(_PC_STATE_PATH) as f:
            _pc_state['last_run'] = json.load(f).get('last_run')
    except Exception:
        pass


def _save_pc_state():
    try:
        with open(_PC_STATE_PATH, 'w') as f:
            json.dump({'last_run': _pc_state['last_run']}, f)
    except Exception:
        pass


def _read_pc_cfg() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f).get('PENDING_COMPLETE', {}) or {}
    except Exception:
        return {}


def _pc_due(cfg: dict, now: datetime) -> bool:
    try:
        every = int(cfg.get('EVERY_MINUTES') or 60)
    except (TypeError, ValueError):
        every = 60
    if every <= 0:
        return False
    last = _pc_state['last_run']
    if not last:
        return True
    try:
        return (now - datetime.fromisoformat(last)).total_seconds() >= every * 60
    except ValueError:
        return True


def _next_pc_run(cfg: dict, now: datetime) -> Optional[str]:
    try:
        every = int(cfg.get('EVERY_MINUTES') or 60)
    except (TypeError, ValueError):
        every = 60
    base = now
    if _pc_state['last_run']:
        try:
            base = datetime.fromisoformat(_pc_state['last_run'])
        except ValueError:
            base = now
    return (base + timedelta(minutes=max(1, every))).isoformat()


def _run_pc_complete(cfg: dict) -> dict:
    """Completa los partidos pasados en score=-1 de TODAS las ligas mapeables, en
    una sola corrida de update_pending_matches (--mode rapido). Reusa el driver de
    corrección. No solapa con NINGUNA sección que use ese mismo driver
    (update_matches / fix_results / extract_fixtures). NUNCA DELETE."""
    busy = next((s for s in ('update_matches', 'fix_results', 'extract_fixtures')
                 if pm.get_status(s).get('status') == 'running'), None)
    if busy:
        return {'ok': False, 'error': f'{busy} ya está corriendo (driver de corrección ocupado)'}
    _pc_state['last_run'] = datetime.now().isoformat()
    _save_pc_state()
    try:
        leagues = get_pending_minus_one_leagues()
    except Exception as e:
        _pc_state['last_error'] = f'leyendo pendientes -1: {e}'
        return {'ok': False, 'error': _pc_state['last_error']}
    if not leagues:
        _pc_state['last_error'] = None
        _pc_state['last_leagues'] = 0
        return {'ok': True, 'note': 'sin pendientes -1 mapeables'}
    if not _ensure_correction_driver():
        _pc_state['last_error'] = 'no se pudo levantar el driver de corrección'
        return {'ok': False, 'error': _pc_state['last_error']}
    _pc_state['last_leagues'] = len(leagues)
    result = pm.start_process('update_matches',
                              {'leagues': [{'sport': lg['sport'], 'key': lg['key']}
                                           for lg in leagues],
                               'mode': 'rapido',
                               'apply': bool(cfg.get('APPLY', False))})
    _pc_state['last_error'] = None if result.get('ok') else result.get('error')
    return result


def _pc_tick(now: datetime):
    cfg = _read_pc_cfg()
    if not bool(cfg.get('ENABLED')):
        _pc_state['next_run'] = None
        return
    _pc_state['next_run'] = _next_pc_run(cfg, now)
    if _pc_due(cfg, now):
        _run_pc_complete(cfg)


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

        # Trigger diario de corrección de team_id inexistente (independiente de news).
        try:
            _fix_tick(datetime.now())
        except Exception as e:
            _fix_state['last_error'] = f'tick error: {e}'

        # Auto-reparación por intervalo de las inconsistencias del live (live-missing).
        try:
            _lm_tick(datetime.now())
        except Exception as e:
            _lm_state['last_error'] = f'tick error: {e}'

        # Auto-completación por intervalo de los partidos en score=-1 (residuo live).
        # Va DESPUÉS de _lm_tick: si esa corrida acaba de tomar el driver de
        # corrección, _run_pc_complete lo detecta ocupado y se salta este tick.
        try:
            _pc_tick(datetime.now())
        except Exception as e:
            _pc_state['last_error'] = f'tick error: {e}'

        _stop.wait(_CHECK_INTERVAL)


# ── API pública ───────────────────────────────────────────────────────────────

def start_scheduler():
    global _thread
    if _thread and _thread.is_alive():
        return
    _load_state()
    _load_fix_state()
    _load_lm_state()
    _load_pc_state()
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name='news-scheduler')
    _thread.start()


def stop_scheduler():
    _stop.set()


def get_fix_status() -> dict:
    """Estado del trigger diario de corrección de team_id inexistente."""
    cfg = _read_fix_cfg()
    return {
        'enabled':      bool(cfg.get('ENABLED')),
        'at_hour':      cfg.get('AT_HOUR', '04:00'),
        'apply':        bool(cfg.get('APPLY')),
        'exclude':      cfg.get('EXCLUDE') or [],
        'last_run':     _fix_state['last_run'],
        'next_run':     _fix_state['next_run'],
        'last_error':   _fix_state['last_error'],
        'last_leagues': _fix_state['last_leagues'],
        'running':      pm.get_status('fix_results').get('status') == 'running',
        'driver_alive': driver_manager.correction.status().get('alive', False),
    }


def run_fix_now() -> dict:
    """Dispara la corrección AHORA (manual, para probar sin esperar la hora).

    Respeta el no-solape; usa el bloque FIX_TEAM_IDS para apply/exclude."""
    return _run_fix(_read_fix_cfg())


def get_pending_complete_status() -> dict:
    """Estado de la auto-completación de partidos en score=-1 (residuo del live)."""
    cfg = _read_pc_cfg()
    try:
        every = int(cfg.get('EVERY_MINUTES') or 60)
    except (TypeError, ValueError):
        every = 60
    return {
        'enabled':       bool(cfg.get('ENABLED')),
        'every_minutes': every,
        'apply':         bool(cfg.get('APPLY', False)),
        'last_run':      _pc_state['last_run'],
        'next_run':      _pc_state['next_run'],
        'last_error':    _pc_state['last_error'],
        'last_leagues':  _pc_state['last_leagues'],
        'running':       pm.get_status('update_matches').get('status') == 'running',
        'driver_alive':  driver_manager.correction.status().get('alive', False),
    }


def run_pending_complete_now() -> dict:
    """Dispara la auto-completación AHORA (manual, sin esperar EVERY_MINUTES).

    Respeta el no-solape del driver de corrección; usa el bloque PENDING_COMPLETE
    para APPLY (default dry-run si APPLY no está)."""
    return _run_pc_complete(_read_pc_cfg())


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
