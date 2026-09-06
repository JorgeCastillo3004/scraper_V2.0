"""
Process Manager
---------------
Gestiona el ciclo de vida de los procesos del scraper (una instancia por sección).
Captura stdout via PIPE y lo distribuye a clientes WebSocket via asyncio.Queue.
"""

import asyncio
import glob
import json
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from typing import Optional

from api.config import PROJECT_ROOT, LOGS_DIR, LEAGUES_INFO_PATH

# Intérprete con el que se lanzan los scripts del scraper. Venv DEDICADO del
# proyecto (`sports_env`), separado del venv del panel/API. Si por algún motivo no
# existe, cae al intérprete que corre la API. Antes era 'python3' literal → caía al
# Python del sistema sin dependencias (ModuleNotFoundError: psycopg2).
_SPORTS_ENV_PY = os.path.join(PROJECT_ROOT, 'sports_env', 'bin', 'python')
PYTHON = _SPORTS_ENV_PY if os.path.exists(_SPORTS_ENV_PY) else sys.executable

# ── Estado global ────────────────────────────────────────────────────────────

class _SectionState:
    def __init__(self):
        self.proc:       Optional[subprocess.Popen] = None
        self.status:     str  = 'stopped'   # stopped | running | paused
        self.started_at: Optional[str] = None
        self.log_buffer: deque = deque(maxlen=500)
        self.clients:    list  = []         # list of asyncio.Queue

_states: dict[str, _SectionState] = {}
_event_loop: Optional[asyncio.AbstractEventLoop] = None   # seteado en startup de FastAPI


def get_state(section: str) -> _SectionState:
    if section not in _states:
        _states[section] = _SectionState()
    return _states[section]


def _build_selected_leagues_dict(selected: list[dict]) -> dict:
    with open(LEAGUES_INFO_PATH, encoding='utf-8') as f:
        leagues_info = json.load(f)

    result = {}
    for item in selected:
        sport = item['sport'].upper()
        key = item['key']
        if sport not in leagues_info or key not in leagues_info[sport]:
            raise ValueError(f'Liga no encontrada en leagues_info.json: {sport}/{key}')
        result.setdefault(sport, {})[key] = leagues_info[sport][key]
    return result


def _write_selection_file(section: str, params: dict) -> str | None:
    selected = params.get('leagues', [])
    if not selected:
        return None

    selection_dict = _build_selected_leagues_dict(selected)
    os.makedirs(os.path.join(PROJECT_ROOT, 'tmp'), exist_ok=True)
    path = os.path.join(
        PROJECT_ROOT,
        'tmp',
        f'{section}_selection_{datetime.now():%Y%m%d_%H%M%S_%f}.json',
    )
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(selection_dict, f, ensure_ascii=False, indent=2)
    return path


# ── Comandos por sección ─────────────────────────────────────────────────────

def build_command(section: str, params: dict) -> list[str]:
    workers  = str(params.get('workers', 2))
    sports   = params.get('sports', [])
    days     = str(params.get('days', 31))
    selection_file = _write_selection_file(section, params)
    sport_args = ['--sport', sports[0]] if len(sports) == 1 else []
    selection_args = ['--selection-file', selection_file] if selection_file else []

    cmds = {
        'news':     [PYTHON,'scripts/run_news.py',
                     '--sports', ','.join(sports) if sports else 'FOOTBALL',
                     '--days', days],
        'leagues':  [PYTHON,'scripts/run_leagues.py',
                     '--sports', ','.join(sports) if sports else 'FOOTBALL'],
        'teams':    [PYTHON,'paralel_teams.py', workers, '--no-confirm'] + sport_args + selection_args,
        'results':  [PYTHON,'paralel_execution.py', workers, 'results', '--no-confirm'],
        'fixtures': [PYTHON,'paralel_execution.py', workers, 'fixtures', '--no-confirm'],
        'players':  [PYTHON,'paralel_players.py', workers, '--no-confirm'] + sport_args,
        'live':     [PYTHON,'main2.py',
                     '--interval', str(params.get('interval', 60))]
                    + (['--sports'] + sports if sports else []),
        # Corrección de resultados por liga (panel Inconsistencias).
        # Sin --apply = DRY-RUN (solo navega y muestra qué corregiría); con --apply
        # escribe en la BD (crea teams faltantes + repara score_entity).
        # Cada liga seleccionada se pasa como --league SPORT_KEY/LEAGUE_KEY.
        # fix_null_team_ids reusa el driver vivo (tmp/driver_session.json).
        'fix_results': [PYTHON,'scripts/fix_null_team_ids.py']
                       + (['--apply'] if params.get('apply') else [])
                       + [a for sel in params.get('leagues', [])
                          for a in ('--league', f"{sel['sport']}/{sel['key']}")],
        # Completar partidos pendientes (fecha<hoy: LIVE o score=-1) reusando el
        # driver vivo. mode rapido/completo + solo_sin_stats (backfill). Sin
        # --apply = DRY-RUN (solo muestra qué escribiría). Una liga por --league.
        'update_matches': [PYTHON,'scripts/update_pending_matches.py',
                           '--mode', params.get('mode', 'completo')]
                          + (['--solo-sin-stats'] if params.get('solo_sin_stats') else [])
                          + (['--apply'] if params.get('apply') else [])
                          + [a for sel in params.get('leagues', [])
                             for a in ('--league', f"{sel['sport']}/{sel['key']}")],
        # Extracción COMPLETA de una liga desde fixtures (panel Inconsistencias →
        # ligas detectadas por live): navega fixtures, expande "mostrar más",
        # recorre cada match, crea teams/stadium faltantes y el match + score.
        # Una sola liga por corrida (sport + key). Sin --apply = DRY-RUN.
        # Por defecto reusa el driver de corrección (mismo driver); con
        # own_driver=True lanza un driver PROPIO (si el de corrección está ocupado).
        # --from-pin: barre TODAS las pineadas de los deportes seleccionados (sin
        # --leagues, multi-deporte vía --sports); si no, extrae las ligas de --leagues.
        'extract_fixtures': [PYTHON,'crear_fixtures_ligas.py']
                            + (['--from-pin', '--sports'] + (params.get('sports') or ['FOOTBALL'])
                               if params.get('from_pin')
                               else ['--sport', (params.get('leagues') or [{}])[0].get('sport', 'FOOTBALL'),
                                     '--leagues'] + [s['key'] for s in params.get('leagues', [])])
                            + (['--today'] if params.get('today') else [])
                            + (['--apply'] if params.get('apply') else [])
                            + (['--no-reuse', '--session-file',
                                os.path.join('tmp', 'extract_fixtures_driver.json')]
                               if params.get('own_driver') else []),
    }
    if section not in cmds:
        raise ValueError(f"Sección desconocida: {section}")
    return cmds[section]


# ── Selección de deportes del live (editable en caliente) ────────────────────

_LIVE_CFG_PATH = lambda: os.path.join(LOGS_DIR, 'run_sports_live.json')


def _read_live_cfg() -> dict:
    try:
        with open(_LIVE_CFG_PATH(), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_live_cfg(**fields) -> dict:
    """Merge-write del hot-config del live (deportes + intervalo en el MISMO archivo).
    Preserva los campos que no se actualizan para no pisar deportes al cambiar el
    intervalo (y viceversa). main2 lee este archivo al inicio de cada ciclo."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    cfg = _read_live_cfg()
    cfg.update(fields)
    cfg['updated_at'] = datetime.now().isoformat()
    with open(_LIVE_CFG_PATH(), 'w', encoding='utf-8') as f:
        json.dump(cfg, f)
    return cfg


def update_live_sports(sports: list) -> dict:
    """Escribe la selección de deportes deseada para el live EN CURSO. main2 la lee
    al inicio de cada ciclo y aplica los cambios sin reiniciar el script."""
    _write_live_cfg(sports=sports)
    return {'ok': True, 'sports': sports}


def update_live_interval(interval: int) -> dict:
    """Escribe el intervalo (segundos) deseado para el live EN CURSO. main2 lo lee
    al inicio de cada ciclo y lo aplica a la pausa del fin de ciclo, sin reiniciar."""
    _write_live_cfg(interval=int(interval))
    return {'ok': True, 'interval': int(interval)}


# ── Inicio de proceso ────────────────────────────────────────────────────────

def start_process(section: str, params: dict) -> dict:
    state = get_state(section)

    if state.proc and state.proc.poll() is None:
        return {'ok': False, 'error': f'{section} ya está corriendo (pid={state.proc.pid})'}

    try:
        cmd = build_command(section, params)
        log_path = os.path.join(LOGS_DIR, f'{section}_{datetime.now():%Y%m%d_%H%M%S}.log')
        env = {**os.environ, 'NO_RICH': '1', 'PYTHONUNBUFFERED': '1'}

        # `start_new_session=True` (setsid): el proceso queda en su PROPIA sesión/grupo,
        # así NO muere cuando se reinicia/mata la API (regla: el live jamás se detiene).
        if section == 'live':
            # LIVE 100% independiente de la API: stdout a ARCHIVO (no PIPE) → si la API
            # muere, main2 NO recibe SIGPIPE. main2 escribe su propio live_*.log; el panel
            # lo lee por heartbeat (mtime). No hay reader_thread (no hace falta el pipe).
            log_file = open(log_path, 'w', buffering=1)
            proc = subprocess.Popen(
                cmd, stdout=log_file, stderr=subprocess.STDOUT,
                text=True, cwd=PROJECT_ROOT, env=env, start_new_session=True,
            )
            reader = None
        else:
            log_file = open(log_path, 'w', buffering=1)
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=PROJECT_ROOT, env=env, start_new_session=True,
            )
            reader = log_file
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo iniciar {section}: {e}'}

    state.proc       = proc
    state.status     = 'running'
    state.started_at = datetime.now().isoformat()
    state.log_buffer.clear()

    _write_control(section, None)   # limpiar comando anterior

    if reader is not None:
        t = threading.Thread(
            target=_reader_thread,
            args=(section, proc, reader),
            daemon=True,
            name=f'reader-{section}',
        )
        t.start()

    return {'ok': True, 'pid': proc.pid, 'cmd': ' '.join(cmd)}


# ── Parar / pausar / reanudar ────────────────────────────────────────────────

def stop_process(section: str):
    state = get_state(section)

    # update_matches: Detener = KILL inmediato del proceso de extracción.
    # El driver es un proceso aparte (Firefox detached) → queda disponible para
    # re-ejecutar. No usamos el stop cooperativo (que espera hasta 30s).
    if section == 'update_matches':
        if state.proc and state.proc.poll() is None:
            try:
                state.proc.terminate()
                try:
                    state.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    state.proc.kill()
            except Exception:
                pass
        _write_control(section, None)
        state.status = 'stopped'
        return

    # Resto de secciones: stop cooperativo (el script lee run_control y cierra limpio).
    _write_control(section, 'stop')
    if state.proc:
        try:
            state.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            state.proc.terminate()
    state.status = 'stopped'


def pause_process(section: str):
    _write_control(section, 'pause')
    get_state(section).status = 'paused'


def resume_process(section: str):
    _write_control(section, 'resume')
    get_state(section).status = 'running'


def _write_control(section: str, command: Optional[str]):
    path = os.path.join(LOGS_DIR, f'run_control_{section}.json')
    with open(path, 'w') as f:
        json.dump({'command': command}, f)


# ── Status ────────────────────────────────────────────────────────────────────

def get_status(section: str) -> dict:
    state = get_state(section)

    # Si el proceso terminó por sí solo, actualizamos el estado
    if state.proc and state.proc.poll() is not None and state.status != 'stopped':
        state.status = 'stopped'

    base = {
        'section':    section,
        'status':     state.status,
        'pid':        state.proc.pid if state.proc and state.proc.poll() is None else None,
        'started_at': state.started_at,
    }

    # Enriquecer con run_status si existe
    status_path = os.path.join(LOGS_DIR, f'run_status_{section}.json')
    if os.path.isfile(status_path):
        try:
            with open(status_path) as f:
                base['run_status'] = json.load(f)
        except Exception:
            pass

    # ── Re-enganche del live tras reinicio de la API ──────────────────────────
    # El 'live' sobrevive a reinicios de la API (regla del proyecto): el proceso
    # main2 queda colgando de la instancia que lo lanzó. La instancia que ahora
    # sirve el panel NO tiene su Popen → reportaría 'stopped' y el panel ofrecería
    # "Iniciar", lanzando un SEGUNDO live. Para evitarlo lo adoptamos por archivo:
    #   • estado deseado: run_status_live.json (main2 lo pone 'running' al arrancar
    #     y 'stopped' al parar limpio) → distingue "corriendo" de "parado".
    #   • latido real: mtime del log live_*.log. main2 entra a un loop bloqueante en
    #     live_games(), así que NO refresca run_status por ciclo, pero SÍ escribe en
    #     el log en cada deporte/ciclo → el mtime es el latido fiable. Si el proceso
    #     muere, el log deja de crecer y la ventana de frescura lo marca 'stopped'.
    if section == 'live' and base['status'] != 'running':
        rs = base.get('run_status')
        if rs and rs.get('state') == 'running':
            try:
                logs = glob.glob(os.path.join(LOGS_DIR, 'live_*.log'))
                if logs:
                    last_mtime = max(os.path.getmtime(p) for p in logs)
                    interval = rs.get('interval') or 60
                    # Un ciclo recorre todos los deportes + pausa del intervalo:
                    # puede tardar varios minutos. Ventana generosa para no matar
                    # un live sano a mitad de ciclo.
                    fresh_window = max(interval * 5, 600)
                    if (datetime.now().timestamp() - last_mtime) < fresh_window:
                        base['status'] = 'running'
                        base['adopted'] = True
                        if rs.get('pid'):
                            base['pid'] = rs['pid']
            except Exception:
                pass

    return base


# ── Hilo lector ──────────────────────────────────────────────────────────────

def _reader_thread(section: str, proc: subprocess.Popen, log_file):
    state = get_state(section)
    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip('\n')
            log_file.write(raw_line)
            state.log_buffer.append(line)
            _broadcast(section, line)
    finally:
        log_file.close()
        proc.stdout.close()
        state.status = 'stopped'
        _broadcast(section, '__DONE__')
        # Al terminar la extracción → tomar un snapshot de db_history (consulta remota,
        # solo SELECT). En hilo aparte para no bloquear el cierre del reader.
        if section == 'update_matches':
            def _snap():
                try:
                    from api.services import history
                    history.take_snapshot()
                    _broadcast(section, '[db_history] snapshot tomado al terminar la extracción.')
                except Exception as e:
                    _broadcast(section, '[db_history] no se pudo tomar snapshot: %s' % e)
            threading.Thread(target=_snap, daemon=True).start()


def _broadcast(section: str, line: str):
    if _event_loop is None:
        return
    state = get_state(section)
    for queue in list(state.clients):
        asyncio.run_coroutine_threadsafe(queue.put(line), _event_loop)


# ── Registro de clientes WebSocket ───────────────────────────────────────────

def add_client(section: str) -> asyncio.Queue:
    q = asyncio.Queue()
    get_state(section).clients.append(q)
    return q


def remove_client(section: str, q: asyncio.Queue):
    try:
        get_state(section).clients.remove(q)
    except ValueError:
        pass
