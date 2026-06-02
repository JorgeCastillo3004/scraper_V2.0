"""
Process Manager
---------------
Gestiona el ciclo de vida de los procesos del scraper (una instancia por sección).
Captura stdout via PIPE y lo distribuye a clientes WebSocket via asyncio.Queue.
"""

import asyncio
import json
import os
import subprocess
import threading
from collections import deque
from datetime import datetime
from typing import Optional

from api.config import PROJECT_ROOT, LOGS_DIR, LEAGUES_INFO_PATH

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
        'news':     ['python3', 'scripts/run_news.py',
                     '--sports', ','.join(sports) if sports else 'FOOTBALL',
                     '--days', days],
        'leagues':  ['python3', 'scripts/run_leagues.py',
                     '--sports', ','.join(sports) if sports else 'FOOTBALL'],
        'teams':    ['python3', 'paralel_teams.py', workers, '--no-confirm'] + sport_args + selection_args,
        'results':  ['python3', 'paralel_execution.py', workers, 'results', '--no-confirm'],
        'fixtures': ['python3', 'paralel_execution.py', workers, 'fixtures', '--no-confirm'],
        'players':  ['python3', 'paralel_players.py', workers, '--no-confirm'] + sport_args,
        'live':     ['python3', 'main2.py',
                     '--interval', str(params.get('interval', 60))]
                    + (['--sports'] + sports if sports else []),
        # Corrección de resultados por liga (panel Inconsistencias).
        # DRY-RUN: NO lleva --apply → solo navega y muestra qué actualizaría.
        # Cada liga seleccionada se pasa como --league SPORT_KEY/LEAGUE_KEY.
        # fix_null_team_ids reusa el driver vivo (tmp/driver_session.json).
        'fix_results': ['python3', 'scripts/fix_null_team_ids.py']
                       + [a for sel in params.get('leagues', [])
                          for a in ('--league', f"{sel['sport']}/{sel['key']}")],
        # Completar partidos pendientes (fecha<hoy: LIVE o score=-1) reusando el
        # driver vivo. mode rapido/completo + solo_sin_stats (backfill). Sin
        # --apply = DRY-RUN (solo muestra qué escribiría). Una liga por --league.
        'update_matches': ['python3', 'scripts/update_pending_matches.py',
                           '--mode', params.get('mode', 'completo')]
                          + (['--solo-sin-stats'] if params.get('solo_sin_stats') else [])
                          + (['--apply'] if params.get('apply') else [])
                          + [a for sel in params.get('leagues', [])
                             for a in ('--league', f"{sel['sport']}/{sel['key']}")],
    }
    if section not in cmds:
        raise ValueError(f"Sección desconocida: {section}")
    return cmds[section]


# ── Inicio de proceso ────────────────────────────────────────────────────────

def start_process(section: str, params: dict) -> dict:
    state = get_state(section)

    if state.proc and state.proc.poll() is None:
        return {'ok': False, 'error': f'{section} ya está corriendo (pid={state.proc.pid})'}

    try:
        cmd = build_command(section, params)
        log_path = os.path.join(LOGS_DIR, f'{section}_{datetime.now():%Y%m%d_%H%M%S}.log')

        log_file = open(log_path, 'w', buffering=1)
        env = {**os.environ, 'NO_RICH': '1', 'PYTHONUNBUFFERED': '1'}

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=PROJECT_ROOT,
            env=env,
        )
    except Exception as e:
        return {'ok': False, 'error': f'No se pudo iniciar {section}: {e}'}

    state.proc       = proc
    state.status     = 'running'
    state.started_at = datetime.now().isoformat()
    state.log_buffer.clear()

    _write_control(section, None)   # limpiar comando anterior

    t = threading.Thread(
        target=_reader_thread,
        args=(section, proc, log_file),
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
