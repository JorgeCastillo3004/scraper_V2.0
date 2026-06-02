"""
paralel_players.py
------------------
Extracción paralela de jugadores (milestone6).

Distribuye equipos pendientes entre N workers usando round-robin.
Cada worker mantiene un driver Firefox independiente y procesa su lista
de equipos secuencialmente. El checkpoint se guarda por equipo dentro
de leagues_season/{sport}/{league}.json con lock por archivo para evitar
corrupción cuando dos workers procesan la misma liga.

Uso:
    python paralel_players.py <n_workers> [--sport FOOTBALL] [--no-confirm]

Ejemplos:
    python paralel_players.py 4
    python paralel_players.py 3 --sport FOOTBALL BASKETBALL
    python paralel_players.py 2 --sport BASKETBALL --no-confirm
"""

import sys
import os
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import milestone6
import common_functions
from common_functions import launch_navigator, load_check_point, save_check_point, wait_update_page, login
from selenium.webdriver.common.by import By
from config import FS_EMAIL, FS_PASSWORD


# ─────────────────────────────────────────────────────────────────────────────
#  LOCK GRANULAR POR ARCHIVO + MONKEY-PATCH DE SAVE
# ─────────────────────────────────────────────────────────────────────────────

_file_locks  = {}               # path → threading.Lock()
_locks_mutex = threading.Lock() # protege el dict _file_locks
_thread_local = threading.local()  # .current_team — equipo activo por thread
_orig_save    = save_check_point   # referencia original antes del patch


def get_file_lock(path: str) -> threading.Lock:
    """Devuelve (creando si hace falta) el lock asociado a un path de archivo."""
    with _locks_mutex:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def _locked_save(path: str, data: dict):
    """
    Reemplaza a save_check_point en milestone6 y common_functions.

    En lugar de sobrescribir el archivo completo, lee el estado fresco,
    actualiza SOLO la entrada del equipo que está procesando este thread
    (_thread_local.current_team) y escribe de vuelta — todo bajo el lock
    del archivo.  Así dos workers que procesen equipos distintos de la misma
    liga no se sobreescriben mutuamente.

    Fallback: si no hay current_team o el archivo no existe, hace write normal.
    """
    team_name = getattr(_thread_local, 'current_team', None)
    lock = get_file_lock(path)

    with lock:
        if team_name and data and team_name in data and os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    current = json.load(f)
                current[team_name] = data[team_name]
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(current, f, indent=2, ensure_ascii=False)
                return
            except Exception:
                pass
        # Fallback: escritura completa
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# Aplicar patch a los módulos que lo usan
common_functions.save_check_point = _locked_save
milestone6.save_check_point       = _locked_save


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

LEAGUES_INFO_FILE  = 'check_points/leagues_info.json'
BASE_SEASON_DIR    = 'check_points/leagues_season'
WORKER_COLORS      = ['cyan', 'yellow', 'green', 'magenta', 'blue', 'red', 'white', 'bright_cyan']
MAX_LINES          = 18
MAX_WORKER_RETRIES = 5

LOGS_DIR          = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
STATUS_FILE       = os.path.join(LOGS_DIR, 'run_status_players.json')
CONTROL_FILE      = os.path.join(LOGS_DIR, 'run_control_players.json')
SCREENSHOTS_DIR   = os.path.join(LOGS_DIR, 'parallel', 'screenshots')


# ─────────────────────────────────────────────────────────────────────────────
#  ESTADO COMPARTIDO (dashboard)
# ─────────────────────────────────────────────────────────────────────────────

_state_lock    = threading.Lock()
_thread_map    = {}   # thread ident → worker_id
_worker_lines  = {}   # worker_id → list[str]
_worker_status = {}   # worker_id → 'running'|'done'|'error'|'retrying'
_worker_league = {}   # worker_id → str "SPORT / liga / equipo"

_stop_event    = threading.Event()
_pause_event   = threading.Event()
_n_workers_global = 0


# ─────────────────────────────────────────────────────────────────────────────
#  STATUS / CONTROL FILES
# ─────────────────────────────────────────────────────────────────────────────

def write_status(state: str):
    os.makedirs(LOGS_DIR, exist_ok=True)
    data = {
        'section':    'players',
        'n_workers':  _n_workers_global,
        'state':      state,
        'updated_at': datetime.now().isoformat(),
        'workers': {
            str(i): {
                'status': _worker_status.get(i, 'idle'),
                'team':   _worker_league.get(i, '—'),
                'lines':  _worker_lines.get(i, []),
            }
            for i in range(_n_workers_global)
        },
    }
    try:
        with open(STATUS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def read_control() -> str:
    try:
        with open(CONTROL_FILE, encoding='utf-8') as f:
            return json.load(f).get('command', 'none')
    except Exception:
        return 'none'


def write_control(command: str):
    os.makedirs(LOGS_DIR, exist_ok=True)
    try:
        with open(CONTROL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'command': command}, f)
    except Exception:
        pass


def _check_control_cmd():
    if _stop_event.is_set():
        raise SystemExit('Stop solicitado')
    cmd = read_control()
    if cmd == 'stop':
        _stop_event.set()
        raise SystemExit('Stop solicitado via archivo de control')
    elif cmd == 'pause':
        _pause_event.set()
        write_status('paused')
        wlog('[yellow]⏸  Worker pausado — esperando reanudación...[/yellow]')
        while _pause_event.is_set() and not _stop_event.is_set():
            time.sleep(1)
            cmd = read_control()
            if cmd == 'resume':
                _pause_event.clear()
                write_control('none')
                write_status('running')
                wlog('[green]▶  Worker reanudado[/green]')
            elif cmd == 'stop':
                _stop_event.set()
                raise SystemExit('Stop solicitado durante pausa')


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS DE ESTADO POR WORKER
# ─────────────────────────────────────────────────────────────────────────────

def _register_thread(worker_id: int):
    with _state_lock:
        _thread_map[threading.current_thread().ident] = worker_id
        _worker_lines[worker_id]  = []
        _worker_status[worker_id] = 'running'
        _worker_league[worker_id] = 'Iniciando...'


def wlog(msg: str):
    ident = threading.current_thread().ident
    with _state_lock:
        wid = _thread_map.get(ident, 0)
        ts  = datetime.now().strftime('%H:%M:%S')
        _worker_lines[wid].append(f"[dim]{ts}[/dim] {msg}")
        if len(_worker_lines[wid]) > MAX_LINES:
            _worker_lines[wid].pop(0)


# ─────────────────────────────────────────────────────────────────────────────
#  DASHBOARD RICH
# ─────────────────────────────────────────────────────────────────────────────

def _build_layout(n_workers: int) -> Layout:
    layout = Layout()
    layout.split_row(*[Layout(name=f'w{i}') for i in range(n_workers)])
    return layout


def _render_layout(layout: Layout, n_workers: int):
    for i in range(n_workers):
        color  = WORKER_COLORS[i % len(WORKER_COLORS)]
        status = _worker_status.get(i, 'running')
        lines  = _worker_lines.get(i, [])
        team   = _worker_league.get(i, '—')

        icon  = {'running': '●', 'done': '✔', 'error': '✘', 'retrying': '↺'}.get(status, '●')
        title = f"[{color}]{icon} WORKER {i}  [PLAYERS][/{color}]"

        header    = f"[bold {color}]▶ {team}[/bold {color}]"
        sep       = f"[dim]{'─' * 40}[/dim]"
        body      = Text.from_markup('\n'.join([header, sep] + lines))
        layout[f'w{i}'].update(Panel(body, title=title, border_style=color))


def _save_screenshot(driver, worker_id: int, reason: str):
    try:
        os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
        ts     = datetime.now().strftime('%Y%m%d_%H%M%S')
        prefix = os.path.join(SCREENSHOTS_DIR, f'w{worker_id}_{reason}_{ts}')
        driver.save_screenshot(f'{prefix}.png')
        with open(f'{prefix}_source.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTRUCCIÓN DE TASKS Y DISTRIBUCIÓN
# ─────────────────────────────────────────────────────────────────────────────

def get_all_pending_teams(sport_filter: str = None) -> list:
    """
    Lee todos los archivos leagues_season/{sport}/{liga}.json y devuelve
    una lista plana de dicts — uno por equipo pendiente:

        {
            'sport':     'FOOTBALL',
            'league':    'ARGENTINA_Liga Profesional',
            'team_name': 'Velez Sarsfield',
            'team_id':   'uuid...',
            'season_id': 'uuid...',
            'path':      'check_points/leagues_season/FOOTBALL/ARGENTINA_Liga Profesional.json'
        }

    Se excluyen equipos cuyo last_processed == 'completed'.
    Se excluyen equipos sin team_url y sin url_players (nada que procesar).
    """
    leagues_info = load_check_point(LEAGUES_INFO_FILE)
    tasks = []

    for sport in sorted(os.listdir(BASE_SEASON_DIR)):
        if sport_filter and sport.upper() != sport_filter.upper():
            continue
        sport_dir = os.path.join(BASE_SEASON_DIR, sport)
        if not os.path.isdir(sport_dir):
            continue

        for filename in sorted(os.listdir(sport_dir)):
            if not filename.endswith('.json'):
                continue
            league = filename[:-5]
            path   = os.path.join(sport_dir, filename)

            try:
                dict_league_season = load_check_point(path)
            except Exception:
                continue

            league_info = leagues_info.get(sport, {}).get(league, {})
            season_id   = league_info.get('season_id')

            for team_name, team_info in dict_league_season.items():
                lp = team_info.get('last_processed')

                if lp == 'completed':
                    continue

                has_url      = bool(team_info.get('team_url'))
                has_players  = bool(team_info.get('url_players'))
                if not has_url and not has_players:
                    continue  # nada que hacer

                tasks.append({
                    'sport':     sport,
                    'league':    league,
                    'team_name': team_name,
                    'team_id':   team_info.get('team_id'),
                    'season_id': season_id,
                    'path':      path,
                })

    return tasks


def split_into_workers(tasks: list, n_workers: int) -> list:
    """
    Distribución round-robin: equipo 0 → worker 0, equipo 1 → worker 1, ...
    Garantiza que cada worker tenga una muestra representativa de sports/ligas.

        tasks = [t0, t1, t2, t3, t4, t5]  con n_workers=3
        worker 0 → [t0, t3]
        worker 1 → [t1, t4]
        worker 2 → [t2, t5]
    """
    buckets = [[] for _ in range(n_workers)]
    for i, task in enumerate(tasks):
        buckets[i % n_workers].append(task)
    return buckets


# ─────────────────────────────────────────────────────────────────────────────
#  WORKER
# ─────────────────────────────────────────────────────────────────────────────

def worker(worker_id: int, tasks: list):
    """
    Procesa la lista de tasks asignados a este worker.

    Flujo por equipo:
        1. Leer checkpoint fresco (con lock de archivo)
        2. Skip si ya completado
        3. Phase 1: obtener url_players via get_squad_list() si no existe
        4. Phase 2: iterar jugadores con navigate_through_players()
              └─ cada jugador guardado actualiza SOLO esta entrada en el JSON
                 gracias al monkey-patch de _locked_save + _thread_local.current_team
        5. Si excepción → reset claim, reinicio de driver con backoff
    """
    _register_thread(worker_id)
    color = WORKER_COLORS[worker_id % len(WORKER_COLORS)]
    wlog(f'[{color}]Worker {worker_id} — {len(tasks)} equipos asignados[/{color}]')

    driver      = None
    task_idx    = 0
    retry_count = 0

    while task_idx < len(tasks):
        if _stop_event.is_set():
            break

        # ── Iniciar / reiniciar driver ────────────────────────────
        if driver is None:
            with _state_lock:
                _worker_status[worker_id] = 'retrying' if retry_count > 0 else 'running'
                _worker_league[worker_id] = 'Iniciando driver...'

            try:
                driver = launch_navigator('https://www.flashscore.com', headless=True)
                login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
                retry_count = 0
                wlog(f'[{color}]Driver + login OK[/{color}]')
                with _state_lock:
                    _worker_status[worker_id] = 'running'
            except Exception as e:
                wlog(f'[red]Login fallido (intento {retry_count+1}): {e}[/red]')
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                retry_count += 1
                if retry_count > MAX_WORKER_RETRIES:
                    wlog(f'[red]Worker {worker_id} abortado tras {retry_count} fallos de login[/red]')
                    break
                delay = min(30 * retry_count, 180)
                wlog(f'[yellow]Reintentando en {delay}s...[/yellow]')
                time.sleep(delay)
                continue

        # ── Task actual ───────────────────────────────────────────
        task      = tasks[task_idx]
        sport     = task['sport']
        league    = task['league']
        team_name = task['team_name']
        path      = task['path']
        file_lock = get_file_lock(path)

        with _state_lock:
            _worker_league[worker_id] = f'{sport} / {league} / {team_name}'

        _check_control_cmd()

        # ── Leer checkpoint fresco ────────────────────────────────
        with file_lock:
            try:
                dict_ls   = load_check_point(path)
            except Exception as e:
                wlog(f'[red]Error leyendo {path}: {e}[/red]')
                task_idx += 1
                continue

            team_info = dict_ls.get(team_name, {})
            lp = team_info.get('last_processed')

            if lp == 'completed':
                wlog(f'  [SKIP] {team_name} ya completado')
                task_idx += 1
                continue

        # ── Registrar equipo activo en thread-local ───────────────
        _thread_local.current_team = team_name

        # ── Leer league_info para season_id ──────────────────────
        leagues_info = load_check_point(LEAGUES_INFO_FILE)
        league_info  = leagues_info.get(sport, {}).get(league, {})
        season_id    = league_info.get('season_id') or task.get('season_id')

        try:
            # ── Phase 1: obtener squad si url_players ausente ─────
            if not team_info.get('url_players'):

                if not team_info.get('team_url'):
                    wlog(f'  [WARN] team_url vacío para {team_name} — saltando equipo')
                    task_idx += 1
                    continue

                wait_update_page(driver, team_info['team_url'], 'container__heading')

                squad_url = None
                try:
                    btn = driver.find_element(By.CLASS_NAME, 'tabs__tab.squad')
                    squad_url = btn.get_attribute('href')
                except Exception:
                    try:
                        btn = driver.find_element(By.XPATH, '//a[@title="Squad"]')
                        squad_url = btn.get_attribute('href')
                    except Exception:
                        wlog(f'  [WARN] Squad button no encontrado: {team_name} ({team_info.get("team_url","")}) — saltando equipo')
                        task_idx += 1
                        continue

                wait_update_page(driver, squad_url, 'heading')
                url_players = milestone6.get_squad_list(driver, sport_id=sport)
                wlog(f'  [INFO] {len(url_players)} jugadores para {team_name}')

                # Guardar url_players con lock (usa el patch: solo actualiza team_name)
                with file_lock:
                    dict_ls = load_check_point(path)
                    dict_ls[team_name]['url_players']    = url_players
                    dict_ls[team_name]['last_processed'] = -1
                    _orig_save(path, dict_ls)  # write directo con lock ya adquirido

                # Refrescar team_info en memoria
                team_info = dict_ls[team_name]

            # ── Releer fresco antes de navigate ──────────────────
            with file_lock:
                dict_ls   = load_check_point(path)
                team_info = dict_ls[team_name]

            # ── Phase 2: iterar jugadores ─────────────────────────
            wlog(f'  [RUN] {team_name} — {len(team_info.get("url_players", []))} jugadores')

            milestone6.navigate_through_players(
                driver,
                league,
                team_name,
                season_id,
                team_info['team_id'],
                team_info,
                path,
                dict_ls,
                sport,
            )

            wlog(f'  [OK] {team_name} completado')
            task_idx  += 1
            retry_count = 0

        except SystemExit:
            break

        except Exception as e:
            wlog(f'  [ERROR] {team_name}: {type(e).__name__}: {e}')
            _save_screenshot(driver, worker_id, f'err_t{task_idx}')

            # Reset: si last_processed quedó en 'in_progress' lo dejamos como -1
            try:
                with file_lock:
                    d = load_check_point(path)
                    if d[team_name].get('last_processed') == 'in_progress':
                        d[team_name]['last_processed'] = -1
                        _orig_save(path, d)
            except Exception:
                pass

            # Reiniciar driver
            try:
                driver.quit()
            except Exception:
                pass
            driver = None

            retry_count += 1
            if retry_count > MAX_WORKER_RETRIES:
                wlog(f'[red]Worker {worker_id} abortado tras {retry_count} errores consecutivos[/red]')
                break

            delay = min(30 * retry_count, 300)
            with _state_lock:
                _worker_status[worker_id] = 'retrying'
                _worker_league[worker_id] = f'Reintentando #{retry_count}/{MAX_WORKER_RETRIES}...'
            wlog(f'[yellow]Reiniciando driver en {delay}s...[/yellow]')
            time.sleep(delay)

    # ── Cleanup ───────────────────────────────────────────────────
    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    with _state_lock:
        _worker_status[worker_id] = 'done' if not _stop_event.is_set() else 'stopped'
        _worker_league[worker_id] = 'Completado ✔' if not _stop_event.is_set() else 'Detenido'

    wlog(f'[{color}]Worker {worker_id} finalizado[/{color}]')


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIRMACIÓN DE DISTRIBUCIÓN
# ─────────────────────────────────────────────────────────────────────────────

def _show_distribution(buckets: list, console: Console) -> bool:
    table = Table(title='Distribución de equipos — [PLAYERS]', show_header=True)
    table.add_column('Worker',   style='bold', justify='center')
    table.add_column('Deportes', justify='left')
    table.add_column('Equipos',  justify='right')

    for idx, tasks in enumerate(buckets):
        color = WORKER_COLORS[idx % len(WORKER_COLORS)]

        # Resumen: cuántos equipos por deporte
        sport_counts: dict = {}
        for t in tasks:
            sport_counts[t['sport']] = sport_counts.get(t['sport'], 0) + 1
        sports_str = '  '.join(f"{s}:{n}" for s, n in sorted(sport_counts.items()))

        table.add_row(
            f'[{color}]W{idx}[/{color}]',
            sports_str,
            str(len(tasks)),
        )

    console.print()
    console.print(table)
    total = sum(len(b) for b in buckets)
    console.print(f'\n  Total equipos pendientes: [bold]{total}[/bold]\n')

    resp = input('  ¿Continuar con la ejecución? [s/N]: ').strip().lower()
    return resp == 's'


# ─────────────────────────────────────────────────────────────────────────────
#  ENTRADA PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def run_parallel(n_workers: int, sport_filter: str = None, confirm: bool = True):
    global _n_workers_global
    _n_workers_global = n_workers

    _stop_event.clear()
    _pause_event.clear()
    write_control('none')
    write_status('starting')

    console = Console()

    tasks   = get_all_pending_teams(sport_filter=sport_filter)
    if not tasks:
        console.print('\n[green]✔ No hay equipos pendientes.[/green]\n')
        return

    buckets = split_into_workers(tasks, n_workers)

    if confirm:
        if not _show_distribution(buckets, console):
            console.print('[yellow]  Ejecución cancelada.[/yellow]')
            write_status('stopped')
            return
    else:
        sport_label = f' [{sport_filter.upper()}]' if sport_filter else ''
        console.print(f'[dim]  Iniciando {n_workers} workers — {len(tasks)} equipos pendientes{sport_label}[/dim]')

    # Inicializar estado de cada worker
    for i in range(n_workers):
        _worker_lines[i]  = []
        _worker_status[i] = 'running'
        _worker_league[i] = 'Iniciando...'

    layout = _build_layout(n_workers)
    write_status('running')

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(worker, idx, bucket): idx
                for idx, bucket in enumerate(buckets)
            }
            while futures:
                done = {f for f in futures if f.done()}
                for f in done:
                    idx = futures.pop(f)
                    try:
                        f.result()
                    except Exception:
                        with _state_lock:
                            _worker_status[idx] = 'error'
                _render_layout(layout, n_workers)
                write_status('running')
                if futures:
                    time.sleep(0.25)

        _render_layout(layout, n_workers)

    final_state = 'stopped' if _stop_event.is_set() else 'completed'
    write_status(final_state)
    write_control('none')

    # ── Resumen final ─────────────────────────────────────────────
    console.print()
    table = Table(title='Resumen de ejecución', show_header=True)
    table.add_column('Worker', style='bold')
    table.add_column('Estado')
    table.add_column('Equipos asignados')
    for i in range(n_workers):
        status = _worker_status.get(i, '?')
        color  = 'green' if status == 'done' else ('red' if status == 'error' else 'yellow')
        table.add_row(f'Worker {i}', f'[{color}]{status}[/{color}]', str(len(buckets[i])))
    console.print(table)


if __name__ == '__main__':
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    confirm   = '--no-confirm' not in sys.argv

    sport_filter = None
    for i, arg in enumerate(sys.argv):
        if arg == '--sport' and i + 1 < len(sys.argv):
            sport_filter = sys.argv[i + 1].upper()
            break

    run_parallel(n_workers, sport_filter=sport_filter, confirm=confirm)
