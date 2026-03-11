"""
paralel_execution.py

Lanza N drivers en paralelo, distribuyendo las ligas habilitadas en
leagues_info.json entre ellos y ejecutando extraction_by_dict por worker.

Uso:
    python paralel_execution.py <n_sessions> <name_section>

Ejemplos:
    python paralel_execution.py 3 results
    python paralel_execution.py 2 fixtures
"""

import sys
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

import milestone4
import common_functions
from common_functions import launch_navigator, load_check_point
from milestone4 import extraction_by_dict


# ─────────────────────────────────────────────
#  LOCK GLOBAL — protege escrituras en leagues_info.json
# ─────────────────────────────────────────────
_file_lock = threading.Lock()
_original_save = common_functions.save_check_point


def _locked_save(*args, **kwargs):
    with _file_lock:
        _original_save(*args, **kwargs)


# Monkey-patch en ambos módulos que llaman a save_check_point
milestone4.save_check_point      = _locked_save
common_functions.save_check_point = _locked_save


# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────
LEAGUES_INFO_FILE = 'check_points/leagues_info.json'
SUPPORTED_SPORTS  = ['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY']
SCREENSHOTS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'parallel', 'screenshots')

WORKER_COLORS = ['cyan', 'yellow', 'green', 'magenta', 'blue', 'red', 'white', 'bright_cyan']

MAX_LINES = 18  # líneas visibles por panel de worker


# ─────────────────────────────────────────────
#  ESTADO COMPARTIDO POR WORKERS (dashboard)
# ─────────────────────────────────────────────
_state_lock   = threading.Lock()
_thread_map   = {}   # thread ident → worker_id
_worker_lines = {}   # worker_id → list of str (últimas MAX_LINES líneas)
_worker_status = {}  # worker_id → 'running' | 'done' | 'error'
_live_handle  = None


def _register_thread(worker_id):
    with _state_lock:
        _thread_map[threading.current_thread().ident] = worker_id
        _worker_lines[worker_id] = []
        _worker_status[worker_id] = 'running'


def wlog(msg):
    """Registra un mensaje en el panel del worker actual."""
    ident = threading.current_thread().ident
    with _state_lock:
        wid = _thread_map.get(ident, 0)
        ts  = datetime.now().strftime('%H:%M:%S')
        _worker_lines[wid].append(f"[dim]{ts}[/dim] {msg}")
        if len(_worker_lines[wid]) > MAX_LINES:
            _worker_lines[wid].pop(0)


def _build_layout(n_workers):
    layout = Layout()
    cols = [Layout(name=f'w{i}') for i in range(n_workers)]
    layout.split_row(*cols)
    return layout


def _render_layout(layout, n_workers, name_section):
    for i in range(n_workers):
        color  = WORKER_COLORS[i % len(WORKER_COLORS)]
        status = _worker_status.get(i, 'running')
        lines  = _worker_lines.get(i, [])

        status_icon = {'running': '●', 'done': '✔', 'error': '✘'}.get(status, '●')
        title = f"[{color}]{status_icon} WORKER {i}  [{name_section.upper()}][/{color}]"

        body = Text.from_markup('\n'.join(lines) if lines else '[dim]Iniciando...[/dim]')
        layout[f'w{i}'].update(Panel(body, title=title, border_style=color))


# ─────────────────────────────────────────────
#  MONKEY-PATCH DE PRINTS EN MILESTONE4
# ─────────────────────────────────────────────
_original_print = __builtins__['print'] if isinstance(__builtins__, dict) else print

def _patched_print(*args, **kwargs):
    msg = ' '.join(str(a) for a in args)
    # Solo capturar mensajes clave; el resto se descarta
    keywords = ('[RONDAS]', '[INFO]', '[OK ]', '[DUP]', '[WARN]', '[ERROR]')
    if any(msg.startswith(k) for k in keywords):
        wlog(msg)

import builtins
builtins.print = _patched_print


# ─────────────────────────────────────────────
#  FUNCIONES DE DISTRIBUCIÓN
# ─────────────────────────────────────────────

def get_enabled_leagues(name_section='results'):
    extract_key  = 'extract_results' if name_section == 'results' else 'extract_fixtures'
    leagues_info = load_check_point(LEAGUES_INFO_FILE)
    enabled = []
    for sport, leagues in leagues_info.items():
        if sport not in SUPPORTED_SPORTS:
            continue
        for league_name, league_info in leagues.items():
            if league_info.get(extract_key, {}).get('extract', False):
                enabled.append((sport, league_name))
    return enabled


def split_into_dicts(enabled_leagues, n_sessions):
    dicts = [{} for _ in range(n_sessions)]
    for i, (sport, league) in enumerate(enabled_leagues):
        worker_idx = i % n_sessions
        dicts[worker_idx].setdefault(sport, []).append(league)
    return dicts


# ─────────────────────────────────────────────
#  SCREENSHOTS ON ERROR
# ─────────────────────────────────────────────

def _save_screenshots(driver, worker_id, reason):
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        ts     = datetime.now().strftime('%Y%m%d_%H%M%S')
        prefix = os.path.join(SCREENSHOTS_DIR, f'worker{worker_id}_{reason}_{ts}')
        driver.save_screenshot(f'{prefix}.png')
        with open(f'{prefix}_source.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        wlog(f'[yellow]Screenshot guardado: worker{worker_id}_{reason}_{ts}.png[/yellow]')
    except Exception as e:
        wlog(f'[red]No se pudo capturar screenshot: {e}[/red]')


# ─────────────────────────────────────────────
#  WORKER
# ─────────────────────────────────────────────

def worker(worker_id, sport_leagues_dict, name_section):
    _register_thread(worker_id)
    color = WORKER_COLORS[worker_id % len(WORKER_COLORS)]
    n_leagues = sum(len(v) for v in sport_leagues_dict.values())
    wlog(f'[{color}]Driver iniciado — {n_leagues} ligas asignadas[/{color}]')

    driver = launch_navigator('https://www.flashscore.com', headless=True)

    try:
        extraction_by_dict(driver, sport_leagues_dict, name_section=name_section)
        with _state_lock:
            _worker_status[worker_id] = 'done'
        wlog(f'[{color}]Extracción completada ✔[/{color}]')
    except Exception as e:
        with _state_lock:
            _worker_status[worker_id] = 'error'
        wlog(f'[red]ERROR: {e}[/red]')
        _save_screenshots(driver, worker_id, 'error')
        raise
    finally:
        driver.quit()


# ─────────────────────────────────────────────
#  ENTRADA PRINCIPAL
# ─────────────────────────────────────────────

def run_parallel(n_sessions, name_section='results'):
    enabled      = get_enabled_leagues(name_section)
    league_dicts = split_into_dicts(enabled, n_sessions)

    layout  = _build_layout(n_sessions)
    console = Console()

    # Inicializar estados vacíos antes de lanzar threads
    for i in range(n_sessions):
        _worker_lines[i]  = []
        _worker_status[i] = 'running'

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        with ThreadPoolExecutor(max_workers=n_sessions) as executor:
            futures = {
                executor.submit(worker, idx, d, name_section): idx
                for idx, d in enumerate(league_dicts)
            }
            while futures:
                done_futures = {f for f in futures if f.done()}
                for future in done_futures:
                    idx = futures.pop(future)
                    try:
                        future.result()
                    except Exception as e:
                        with _state_lock:
                            _worker_status[idx] = 'error'
                _render_layout(layout, n_sessions, name_section)
                if futures:
                    import time; time.sleep(0.25)

        _render_layout(layout, n_sessions, name_section)

    # Resumen final fuera del Live
    console.print()
    table = Table(title='Resumen de ejecución', show_header=True)
    table.add_column('Worker', style='bold')
    table.add_column('Estado')
    table.add_column('Ligas')
    for i in range(n_sessions):
        status = _worker_status.get(i, '?')
        color  = 'green' if status == 'done' else ('red' if status == 'error' else 'yellow')
        n_l    = sum(len(v) for v in league_dicts[i].values())
        table.add_row(f'Worker {i}', f'[{color}]{status}[/{color}]', str(n_l))
    console.print(table)


if __name__ == '__main__':
    n_sessions   = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    name_section = sys.argv[2]      if len(sys.argv) > 2 else 'results'
    run_parallel(n_sessions, name_section)
