"""
paralel_teams.py

Lanza N workers en paralelo para ejecutar teams_creation sobre las ligas de
leagues_info.json que tienen teams > 0.

Lógica de skip automático:
  - Si check_points/leagues_season/<SPORT>/<LEAGUE>.json existe y tiene
    >= leagues_info["teams"] entradas → liga ya completa → se omite.
  - Si el archivo existe pero tiene menos entradas → resume desde
    leagues_info["teams_creation"]["last_team_created"].
  - Si el archivo no existe → procesar desde el principio.

Cada worker guarda su asignación en tmp/worker_N_assignment.json antes de
iniciar (útil para depuración y validación).

Uso:
    python paralel_teams.py [n_workers=1] [--sport SPORT] [--no-confirm] [--check_url]

Ejemplos:
    python paralel_teams.py 3
    python paralel_teams.py 2 --sport FOOTBALL
    python paralel_teams.py 1 --no-confirm
    python paralel_teams.py 3 --check_url
    python paralel_teams.py 2 --check_url --sport FOOTBALL

Modo --check_url:
  Recorre los archivos leagues_season/ existentes, detecta equipos con
  team_url vacío y los completa navegando a la página de standings de
  cada liga afectada (get_teams_info_part1). No crea equipos nuevos.
"""

import sys
import os
import json
import threading
import time
import builtins
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.console import Console
from rich.table import Table

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

import milestone3
import common_functions
from common_functions import launch_navigator, load_check_point, wait_update_page
from milestone3 import (
    get_teams_info_part1,
    get_teams_info_part2,
    get_all_teams_from_standings,
    create_team_in_db,
    add_league_info,
)
import data_base
from data_base import (
    get_dict_sport_id,
    get_dict_league_ready,
    get_country_id,
    insert_country,
    get_season_id_by_league,
    get_teams_by_league_id,
)


# ─────────────────────────────────────────────
#  LOCK 1 — protege escrituras en leagues_info.json
# ─────────────────────────────────────────────
_file_lock     = threading.Lock()
_original_save = common_functions.save_check_point


def _locked_save(*args, **kwargs):
    with _file_lock:
        _original_save(*args, **kwargs)


milestone3.save_check_point       = _locked_save
common_functions.save_check_point = _locked_save


# ─────────────────────────────────────────────
#  LOCK 2 — serializa todas las operaciones DB
#
#  psycopg2 no es thread-safe: data_base.py usa una conexión global (con)
#  compartida entre todos los threads. Este lock garantiza que solo un
#  thread ejecute cualquier función DB en un momento dado.
#  El cuello de botella real es Selenium, por lo que el impacto es mínimo.
# ─────────────────────────────────────────────
_db_lock = threading.Lock()

_db_functions_to_wrap = [
    'save_team_info', 'save_league_team_entity',
    'get_list_id_teams', 'get_dict_league_ready',
    'get_country_id', 'insert_country',
    'get_season_id_by_league', 'get_dict_sport_id',
    'check_team_season_duplicates', 'get_teams_by_league_id',
    # ensure_connection NO se wrapea: es llamada internamente por cada función
    # arriba. Wrapearla con el mismo lock causaría deadlock (lock no reentrant).
]

for _fn_name in _db_functions_to_wrap:
    _orig_fn = getattr(data_base, _fn_name)
    def _make_locked(fn):
        def _locked_fn(*args, **kwargs):
            with _db_lock:
                return fn(*args, **kwargs)
        _locked_fn.__name__ = fn.__name__
        return _locked_fn
    setattr(data_base, _fn_name, _make_locked(_orig_fn))

# Sincronizar referencias locales con las versiones wrapped
get_dict_sport_id      = data_base.get_dict_sport_id
get_dict_league_ready  = data_base.get_dict_league_ready
get_country_id         = data_base.get_country_id
insert_country         = data_base.insert_country
get_season_id_by_league  = data_base.get_season_id_by_league
get_teams_by_league_id   = data_base.get_teams_by_league_id


# ─────────────────────────────────────────────
#  LOCK 3 — evita duplicados en check-then-insert
#
#  Race condition: dos workers procesan el mismo equipo en ligas distintas.
#  Ambos pasan Layer1 (dict stale) y Layer2 (query real-time) antes de que
#  alguno haga el INSERT, resultando en dos filas para el mismo equipo.
#  Este lock serializa el bloque completo "verificar → insertar".
# ─────────────────────────────────────────────
_team_create_lock = threading.Lock()


# ─────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────
LEAGUES_INFO_FILE  = 'check_points/leagues_info.json'
LEAGUES_SEASON_DIR = 'check_points/leagues_season'
TMP_DIR            = 'tmp'
LOGS_DIR           = 'logs'
TEAMS_SCREENSHOTS_DIR = os.path.join(LOGS_DIR, 'screenshots', 'teams')
TEAMS_SCREENSHOTS_LATEST_DIR = os.path.join(TEAMS_SCREENSHOTS_DIR, 'latest')
TEAMS_SCREENSHOTS_HISTORY_DIR = os.path.join(TEAMS_SCREENSHOTS_DIR, 'history')

WORKER_COLORS      = ['cyan', 'yellow', 'green', 'magenta', 'blue', 'red', 'white', 'bright_cyan']
MAX_LINES          = 16
MAX_WORKER_RETRIES = 5

# Mapping DB (Title Case) → proyecto (UPPERCASE)
SPORT_NAME_MAP = {
    'Football':         'FOOTBALL',
    'Basketball':       'BASKETBALL',
    'Baseball':         'BASEBALL',
    'Hockey':           'HOCKEY',
    'Tennis':           'TENNIS',
    'Golf':             'GOLF',
    'Boxing':           'BOXING',
    'American Football':'AM._FOOTBALL',
}


# ─────────────────────────────────────────────
#  ESTADO COMPARTIDO POR WORKERS
# ─────────────────────────────────────────────
_state_lock    = threading.Lock()
_thread_map    = {}   # thread ident → worker_id
_worker_lines  = {}   # worker_id → list[str]
_worker_status = {}   # worker_id → 'running' | 'done' | 'error' | 'retrying' | 'stopped'
_worker_league = {}   # worker_id → str liga actual
_stop_event    = threading.Event()


# ─────────────────────────────────────────────
#  LOGGING / ESTADO
# ─────────────────────────────────────────────

def _register_thread(worker_id):
    with _state_lock:
        _thread_map[threading.current_thread().ident] = worker_id
        _worker_lines[worker_id]  = []
        _worker_status[worker_id] = 'running'
        _worker_league[worker_id] = 'Iniciando...'


def wlog(msg):
    ident = threading.current_thread().ident
    with _state_lock:
        wid = _thread_map.get(ident, 0)
        ts  = datetime.now().strftime('%H:%M:%S')
        _worker_lines[wid].append(f"[dim]{ts}[/dim] {msg}")
        if len(_worker_lines[wid]) > MAX_LINES:
            _worker_lines[wid].pop(0)


def _set_league(sport, league):
    ident = threading.current_thread().ident
    with _state_lock:
        wid = _thread_map.get(ident)
        if wid is not None:
            _worker_league[wid] = f'{sport}  /  {league}'


def _get_worker_id():
    ident = threading.current_thread().ident
    with _state_lock:
        return _thread_map.get(ident, 0)


def _slugify(value):
    cleaned = ''.join(ch if ch.isalnum() else '_' for ch in str(value).strip())
    return cleaned.strip('_')[:80] or 'snapshot'


def _clear_latest_screenshots():
    os.makedirs(TEAMS_SCREENSHOTS_LATEST_DIR, exist_ok=True)
    for name in os.listdir(TEAMS_SCREENSHOTS_LATEST_DIR):
        path = os.path.join(TEAMS_SCREENSHOTS_LATEST_DIR, name)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _save_worker_screenshot(driver, label, keep_history=False):
    if driver is None:
        return

    worker_id = _get_worker_id()
    os.makedirs(TEAMS_SCREENSHOTS_LATEST_DIR, exist_ok=True)
    os.makedirs(TEAMS_SCREENSHOTS_HISTORY_DIR, exist_ok=True)

    captured_at = datetime.now().isoformat()
    safe_label = _slugify(label)
    latest_png = os.path.join(TEAMS_SCREENSHOTS_LATEST_DIR, f'worker_{worker_id}.png')
    latest_meta = os.path.join(TEAMS_SCREENSHOTS_LATEST_DIR, f'worker_{worker_id}.json')

    metadata = {
        'worker_id': worker_id,
        'label': label,
        'captured_at': captured_at,
        'league': _worker_league.get(worker_id, '—'),
        'url': getattr(driver, 'current_url', ''),
        'image_url': f'/artifacts/screenshots/teams/latest/worker_{worker_id}.png',
    }

    try:
        original_size = driver.get_window_size()
        try:
            total_height = driver.execute_script('return document.body.scrollHeight')
            driver.set_window_size(original_size['width'], max(total_height, original_size['height']))
            driver.save_screenshot(latest_png)
        finally:
            driver.set_window_size(original_size['width'], original_size['height'])
        with open(latest_meta, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        wlog(f'[dim]Screenshot worker {worker_id}: {label}[/dim]')

        if keep_history:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            history_png = os.path.join(
                TEAMS_SCREENSHOTS_HISTORY_DIR,
                f'worker_{worker_id}_{ts}_{safe_label}.png',
            )
            original_size2 = driver.get_window_size()
            try:
                total_height2 = driver.execute_script('return document.body.scrollHeight')
                driver.set_window_size(original_size2['width'], max(total_height2, original_size2['height']))
                driver.save_screenshot(history_png)
            finally:
                driver.set_window_size(original_size2['width'], original_size2['height'])
    except Exception as e:
        wlog(f'[red][WARN] No se pudo guardar screenshot: {e}[/red]')


def _should_use_headless():
    value = os.environ.get('TEAMS_HEADLESS')
    if value is not None:
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return not bool(os.environ.get('DISPLAY'))


# ─────────────────────────────────────────────
#  MONKEY-PATCH PRINTS — captura mensajes de milestone3
# ─────────────────────────────────────────────
_original_print = builtins.print

_LOG_KEYWORDS = (
    '[SKIP', '[RESUME]', '[WARN]', '[ERROR]', '[DIV]',
    'TEAM FOUND', "TEAM DON'T", 'TEAM CREATED', 'TEAM HAS BEEN',
    'LEAGUE_TEAM ENTITY',
)


def _patched_print(*args, **kwargs):
    msg = ' '.join(str(a) for a in args)
    if any(k in msg for k in _LOG_KEYWORDS):
        wlog(msg[:120])


builtins.print = _patched_print


# ─────────────────────────────────────────────
#  LAYOUT RICH
# ─────────────────────────────────────────────

def _build_layout(n_workers):
    layout = Layout()
    cols   = [Layout(name=f'w{i}') for i in range(n_workers)]
    layout.split_row(*cols)
    return layout


def _render_layout(layout, n_workers):
    for i in range(n_workers):
        color  = WORKER_COLORS[i % len(WORKER_COLORS)]
        status = _worker_status.get(i, 'running')
        lines  = _worker_lines.get(i, [])
        league = _worker_league.get(i, '—')

        icon  = {'running': '●', 'done': '✔', 'error': '✘', 'retrying': '↺'}.get(status, '●')
        title  = f"[{color}]{icon} WORKER {i}  [TEAMS][/{color}]"
        header = f"[bold {color}]▶ {league}[/bold {color}]"
        sep    = f"[dim]{'─' * 40}[/dim]"
        body   = Text.from_markup('\n'.join([header, sep] + lines))
        layout[f'w{i}'].update(Panel(body, title=title, border_style=color))


# ─────────────────────────────────────────────
#  SKIP LOGIC — cruza leagues_info con leagues_season/
# ─────────────────────────────────────────────

def _league_status(sport, league_name, expected_teams):
    """
    Compara leagues_info["teams"] contra el archivo leagues_season generado.

    Retorna:
        'completed' → archivo existe con >= expected_teams entradas → skip
        'partial'   → archivo existe pero incompleto               → resume
        'pending'   → archivo no existe                            → procesar
    """
    path = os.path.join(LEAGUES_SEASON_DIR, sport, f'{league_name}.json')
    if not os.path.exists(path):
        return 'pending'
    try:
        saved = json.load(open(path, encoding='utf-8'))
        return 'completed' if len(saved) >= expected_teams else 'partial'
    except Exception:
        return 'pending'


# ─────────────────────────────────────────────
#  DISTRIBUCIÓN DE LIGAS
# ─────────────────────────────────────────────

def get_pending_leagues(sport_filter=None):
    """
    Lee leagues_info.json y retorna:
      - pending: lista plana de (sport, league_name, league_info) con teams > 0
                 y que no estén ya completas en leagues_season/
      - skipped: conteo de ligas omitidas por estar completas
    """
    leagues_info = load_check_point(LEAGUES_INFO_FILE)
    pending  = []
    skipped  = 0

    for sport, leagues in leagues_info.items():
        if sport_filter and sport != sport_filter.upper():
            continue
        for league_name, league_info in leagues.items():
            expected = league_info.get('teams', 0)
            league_cp = league_info.get('teams_creation', {})
            if not league_cp.get('extract', False):
                continue
            if expected == 0:
                continue
            if _league_status(sport, league_name, expected) == 'completed':
                skipped += 1
                continue
            pending.append((sport, league_name, league_info))

    return pending, skipped


def get_pending_selected_leagues(selected_leagues_dict):
    """
    Procesa solo las ligas seleccionadas por frontend.
    selected_leagues_dict debe tener formato:
      { sport: { league_name: league_info } }

    No aplica filtros de teams==0 ni de estado completado: si el usuario
    seleccionó una liga explícitamente, se procesa sin importar el checkpoint.
    """
    pending = []
    for sport, leagues in selected_leagues_dict.items():
        for league_name, league_info in leagues.items():
            pending.append((sport, league_name, league_info))
    return pending, 0


def get_pending_url_check(sport_filter=None):
    """
    Escanea leagues_season/ y retorna ligas donde al menos un equipo
    tiene team_url vacío o ausente.

    Retorna:
      - pending: lista de (sport, league_name, league_info, n_missing)
      - skipped: ligas donde todas las URLs ya están completas
    """
    leagues_info = load_check_point(LEAGUES_INFO_FILE)
    pending  = []
    skipped  = 0

    for sport, leagues in leagues_info.items():
        if sport_filter and sport != sport_filter.upper():
            continue
        for league_name, league_info in leagues.items():
            ls_file = os.path.join(LEAGUES_SEASON_DIR, sport, f'{league_name}.json')
            if not os.path.exists(ls_file):
                continue  # sin archivo → no aplica check_url
            try:
                data = json.load(open(ls_file, encoding='utf-8'))
            except Exception:
                continue
            missing = [t for t, info in data.items() if not info.get('team_url', '')]
            if not missing:
                skipped += 1
                continue
            pending.append((sport, league_name, league_info, len(missing)))

    return pending, skipped


def split_into_workers(pending, n_workers):
    """
    Divide la lista plana en N dicts round-robin.
    Acepta tanto (sport, league_name, league_info) como
    (sport, league_name, league_info, extra) — el campo extra se ignora.
    Resultado por worker: { sport: { league_name: league_info } }
    """
    dicts = [{} for _ in range(n_workers)]
    for i, item in enumerate(pending):
        sport, league_name, league_info = item[0], item[1], item[2]
        wid = i % n_workers
        dicts[wid].setdefault(sport, {})[league_name] = league_info
    return dicts


def save_worker_assignments(league_dicts):
    """
    Guarda en tmp/worker_N_assignment.json la asignación de cada worker.
    Solo incluye campos relevantes para validación (no el dict completo).
    """
    os.makedirs(TMP_DIR, exist_ok=True)
    for idx, d in enumerate(league_dicts):
        summary = {
            sport: {
                league_name: {
                    'teams':     info.get('teams', 0),
                    'standings': info.get('standings', ''),
                    'status':    _league_status(sport, league_name, info.get('teams', 0)),
                }
                for league_name, info in leagues.items()
            }
            for sport, leagues in d.items()
        }
        path = os.path.join(TMP_DIR, f'worker_{idx}_assignment.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
#  CONFIRMACIÓN / TABLA DE DISTRIBUCIÓN
# ─────────────────────────────────────────────

def _show_distribution(league_dicts, console, skipped):
    table = Table(title='Distribución de ligas — [TEAMS CREATION]', show_header=True)
    table.add_column('Worker',   style='bold', justify='center')
    table.add_column('Deporte')
    table.add_column('Liga')
    table.add_column('Equipos',  justify='right')
    table.add_column('Estado')

    for idx, d in enumerate(league_dicts):
        color = WORKER_COLORS[idx % len(WORKER_COLORS)]
        first = True
        for sport, leagues in d.items():
            for league_name, info in leagues.items():
                worker_label = f'[{color}]W{idx}[/{color}]' if first else ''
                status       = _league_status(sport, league_name, info.get('teams', 0))
                status_fmt   = '[yellow]partial[/yellow]' if status == 'partial' else 'pending'
                table.add_row(
                    worker_label,
                    sport,
                    league_name,
                    str(info.get('teams', '?')),
                    status_fmt,
                )
                first = False

    console.print()
    console.print(table)
    if skipped:
        console.print(f'[dim]  {skipped} ligas ya completas en leagues_season/ → omitidas[/dim]')
    console.print(f'[dim]  Asignaciones guardadas en {TMP_DIR}/[/dim]')
    console.print()

    resp = input('  ¿Continuar con la ejecución? [s/N]: ').strip().lower()
    return resp == 's'


# ─────────────────────────────────────────────
#  LÓGICA DE EXTRACCIÓN POR WORKER
# ─────────────────────────────────────────────

def _teams_creation_worker(driver, sport_leagues_dict, leagues_info_json, dict_sport_id):
    """
    Itera sport → league → teams para el subconjunto asignado al worker.
    Replica la lógica de milestone3.teams_creation() acotada al dict recibido.
    """
    for sport_name, leagues in sport_leagues_dict.items():

        if sport_name not in dict_sport_id:
            wlog(f'[yellow][SKIP] {sport_name} — sin sport_id en DB[/yellow]')
            continue

        sport_id      = dict_sport_id[sport_name]
        dict_teams_db = get_dict_league_ready(sport_id=sport_id)

        for league_name, league_info in leagues.items():
            if _stop_event.is_set():
                return

            _set_league(sport_name, league_name)
            expected = league_info.get('teams', 0)

            # Enriquecer league_info con sport_name/sport_id/league_name
            add_league_info(sport_name, sport_id, league_name, league_info)

            # Sync season_id desde DB
            season_id_db = get_season_id_by_league(league_info['league_id'])
            if season_id_db:
                league_info['season_id'] = season_id_db

            # Crear carpeta leagues_season/<SPORT>/ si no existe
            ls_sport_dir = os.path.join(LEAGUES_SEASON_DIR, sport_name)
            os.makedirs(ls_sport_dir, exist_ok=True)

            # Navegar a standings (incluyendo divisiones via get_all_teams_from_standings)
            url = league_info.get('standings') or league_info.get('draw')
            if not url:
                wlog(f'[red][WARN] {league_name} — sin URL standings/draw[/red]')
                continue

            wlog(f'[cyan]▶ {league_name} ({expected} equipos)[/cyan]')
            _save_worker_screenshot(driver, f'league_{league_name}_before_standings')
            dict_teams_availables = get_all_teams_from_standings(driver, url)
            _save_worker_screenshot(driver, f'league_{league_name}_standings_loaded')

            if not dict_teams_availables:
                wlog(f'[yellow][WARN] {league_name} — 0 equipos en standings[/yellow]')
                continue
            wlog(f'[dim]  {len(dict_teams_availables)} equipos encontrados (todas las divisiones)[/dim]')

            # Cargar archivo leagues_season existente
            ls_file = os.path.join(ls_sport_dir, f'{league_name}.json')
            dict_country_league_season = {}
            if os.path.exists(ls_file):
                try:
                    dict_country_league_season = json.load(open(ls_file, encoding='utf-8'))
                except Exception:
                    dict_country_league_season = {}

            # Equipos ya en DB para esta liga (fuente autoritativa)
            league_id = league_info.get('league_id', '')
            db_team_names: set[str] = set()
            if league_id:
                try:
                    db_rows = get_teams_by_league_id(league_id, sport_id)
                    db_team_names = {row[1] for row in db_rows}
                    if db_team_names:
                        wlog(f'[dim]  {len(db_team_names)} equipos ya en DB[/dim]')
                except Exception:
                    pass

            # Equipos faltantes: no en checkpoint Y no en DB
            missing_teams = {
                k: v for k, v in dict_teams_availables.items()
                if k not in dict_country_league_season and k not in db_team_names
            }
            if not missing_teams:
                wlog(f'[dim][SKIP] {league_name} — todos los equipos ya existen[/dim]')
                continue
            wlog(f'[dim]  {len(missing_teams)} equipos nuevos de {len(dict_teams_availables)} en standings[/dim]')

            league_cp = league_info.setdefault('teams_creation', {})

            # ── Iterar solo equipos faltantes ────────────────────────────────
            for team_name, team_info_url in missing_teams.items():
                if _stop_event.is_set():
                    return

                wait_update_page(driver, team_info_url['team_url'], 'heading')
                _save_worker_screenshot(driver, f'team_{team_name}_page')
                dict_team = get_teams_info_part2(driver, league_info, team_info_url)

                # LOCK 3: serializa get_country_id + insert_country + create_team_in_db
                # Evita la race condition check-then-insert cuando dos workers
                # procesan el mismo equipo en ligas distintas simultáneamente.
                with _team_create_lock:
                    dict_team['country_id'] = (
                        get_country_id(dict_team['team_country']) or
                        insert_country(dict_team['team_country'])
                    )
                    team_id = create_team_in_db(dict_teams_db, sport_id, dict_team)
                dict_country_league_season[team_name] = {
                    'team_id':  team_id,
                    'team_url': team_info_url['team_url'],
                }

                # Checkpoint tras cada equipo
                league_cp['last_team_created'] = team_name
                _locked_save(LEAGUES_INFO_FILE, leagues_info_json)
                _locked_save(ls_file, dict_country_league_season)

            # Liga completada
            league_cp['last_team_created'] = ''
            league_cp['status']            = 'completed'
            _locked_save(LEAGUES_INFO_FILE, leagues_info_json)
            _locked_save(ls_file, dict_country_league_season)
            _save_worker_screenshot(driver, f'league_{league_name}_completed', keep_history=True)
            wlog(f'[green]✔ {league_name} — {len(dict_country_league_season)} equipos[/green]')


# ─────────────────────────────────────────────
#  TABLA DE DISTRIBUCIÓN — modo check_url
# ─────────────────────────────────────────────

def _show_distribution_check_url(league_dicts, pending_raw, console):
    """Tabla de distribución para --check_url mostrando URLs faltantes por liga."""
    # Índice rápido: (sport, league_name) → n_missing
    missing_index = {(s, l): n for s, l, _, n in pending_raw}

    table = Table(title='Distribución de ligas — [CHECK URL]', show_header=True)
    table.add_column('Worker',          style='bold', justify='center')
    table.add_column('Deporte')
    table.add_column('Liga')
    table.add_column('URLs faltantes',  justify='right')

    for idx, d in enumerate(league_dicts):
        color = WORKER_COLORS[idx % len(WORKER_COLORS)]
        first = True
        for sport, leagues in d.items():
            for league_name in leagues:
                worker_label = f'[{color}]W{idx}[/{color}]' if first else ''
                n_miss = missing_index.get((sport, league_name), '?')
                table.add_row(worker_label, sport, league_name, f'[yellow]{n_miss}[/yellow]')
                first = False

    console.print()
    console.print(table)
    console.print()
    resp = input('  ¿Continuar con la verificación? [s/N]: ').strip().lower()
    return resp == 's'


# ─────────────────────────────────────────────
#  LÓGICA DE VERIFICACIÓN DE URLs POR WORKER
# ─────────────────────────────────────────────

def _check_urls_worker(driver, sport_leagues_dict, dict_sport_id):
    """
    Para cada liga asignada:
      1. Carga el archivo leagues_season existente.
      2. Detecta equipos con team_url vacío e imprime la lista.
      3. Navega a standings con get_all_teams_from_standings (soporta divisiones).
      4. Por cada equipo faltante:
         - Si está en standings: completa team_url.
         - Verifica si existe en DB por team_id; si no, lo crea.
      5. Guarda el archivo actualizado.
    """
    for sport_name, leagues in sport_leagues_dict.items():
        for league_name, league_info in leagues.items():
            if _stop_event.is_set():
                return

            _set_league(sport_name, league_name)
            ls_file = os.path.join(LEAGUES_SEASON_DIR, sport_name, f'{league_name}.json')

            try:
                data = json.load(open(ls_file, encoding='utf-8'))
            except Exception as e:
                wlog(f'[red][ERROR] No se pudo leer {league_name}: {e}[/red]')
                continue

            missing = [t for t, info in data.items() if not info.get('team_url', '')]
            if not missing:
                wlog(f'[dim][SKIP] {league_name} — todas las URLs OK[/dim]')
                continue

            wlog(f'[cyan]▶ {league_name} — {len(missing)} equipos sin URL[/cyan]')
            wlog(f'[dim]  faltantes: {", ".join(missing)}[/dim]')

            # Verificación en DB: cuántos equipos tiene esta liga registrados
            not_in_db      = []
            sport_id_check = dict_sport_id.get(sport_name) if dict_sport_id else None
            league_id      = league_info.get('league_id', '')
            if sport_id_check and league_id:
                db_teams      = get_teams_by_league_id(league_id, sport_id_check)
                db_team_names = [row[1] for row in db_teams]
                wlog(f'[dim]  DB — {len(db_teams)} equipos en liga ({sport_name}): {", ".join(db_team_names)}[/dim]')
                # Detectar equipos del checkpoint que NO están en DB
                not_in_db = [t for t in data.keys() if t not in db_team_names]
                if not_in_db:
                    wlog(f'[yellow]  en checkpoint pero no en DB ({len(not_in_db)}): {", ".join(not_in_db)}[/yellow]')
                else:
                    wlog(f'[dim]  todos los equipos del checkpoint están en DB[/dim]')
            else:
                wlog(f'[yellow][WARN] no se puede verificar DB — league_id o sport_id faltante[/yellow]')

            url = league_info.get('standings') or league_info.get('draw')
            if not url:
                wlog(f'[red][WARN] {league_name} — sin URL standings/draw[/red]')
                continue

            # Navega a standings incluyendo divisiones
            wlog(f'[dim]  navegando a standings: {url}[/dim]')
            _save_worker_screenshot(driver, f'check_url_{league_name}_before_standings')
            dict_teams_scraped = get_all_teams_from_standings(driver, url)
            _save_worker_screenshot(driver, f'check_url_{league_name}_standings_loaded')

            if not dict_teams_scraped:
                wlog(f'[yellow][WARN] {league_name} — standings vacío[/yellow]')
                continue

            wlog(f'[dim]  standings: {len(dict_teams_scraped)} equipos encontrados: {", ".join(dict_teams_scraped.keys())}[/dim]')

            # sport_id y equipos en DB para crear si hace falta
            sport_id      = dict_sport_id.get(sport_name) if dict_sport_id else None
            dict_teams_db = get_dict_league_ready(sport_id=sport_id) if sport_id else {}

            # Unificar trabajo:
            #   missing   → necesitan URL  (fuente: checkpoint)
            #   not_in_db → necesitan creación en DB  (fuente: DB query — autoridad única)
            to_process = set(missing) | set(not_in_db)
            wlog(f'[dim]  a procesar: {len(to_process)} equipos '
                 f'(sin URL: {len(missing)} | no en DB: {len(not_in_db)})[/dim]')

            filled    = 0
            created   = 0
            not_found = []

            for team_name in to_process:
                wlog(f'[dim]  ── "{team_name}" '
                     f'[sin URL: {team_name in missing}] '
                     f'[no en DB: {team_name in not_in_db}][/dim]')

                # ── 1. Resolver URL ──────────────────────────────────────────
                # Prioridad: standings (fresco) → checkpoint (guardado)
                team_info_url = dict_teams_scraped.get(team_name)
                if team_info_url:
                    new_url = team_info_url.get('team_url', '')
                    wlog(f'[dim]     URL desde standings: {new_url}[/dim]')
                else:
                    new_url = data.get(team_name, {}).get('team_url', '')
                    if new_url:
                        wlog(f'[dim]     URL desde checkpoint: {new_url}[/dim]')
                    else:
                        wlog(f'[yellow][WARN] "{team_name}" — no en standings y sin URL en checkpoint[/yellow]')
                        not_found.append(team_name)
                        continue

                # ── 2. Completar URL en checkpoint si estaba vacía ───────────
                if team_name in missing:
                    data[team_name]['team_url'] = new_url
                    wlog(f'[green]     URL completada → {new_url}[/green]')
                    filled += 1

                # ── 3. Crear en DB si no existe (not_in_db es la autoridad) ──
                if team_name not in not_in_db:
                    wlog(f'[dim]     ya existe en DB — skip creación[/dim]')
                    continue

                wlog(f'[yellow]     no está en DB — creando...[/yellow]')
                if not sport_id:
                    wlog(f'[red][WARN] sin sport_id para {sport_name} — no se puede crear[/red]')
                    continue

                # Si no vino de standings construir dict mínimo para get_teams_info_part2
                if not team_info_url:
                    team_info_url = {'team_url': new_url}

                try:
                    wait_update_page(driver, new_url, 'heading')
                    _save_worker_screenshot(driver, f'check_url_team_{team_name}')
                    dict_team = get_teams_info_part2(driver, league_info, team_info_url)
                    wlog(f'[dim]     info: {dict_team.get("team_name")} | país: {dict_team.get("team_country")}[/dim]')
                    with _team_create_lock:
                        dict_team['country_id'] = (
                            get_country_id(dict_team['team_country']) or
                            insert_country(dict_team['team_country'])
                        )
                        team_id = create_team_in_db(dict_teams_db, sport_id, dict_team)
                    data[team_name]['team_id'] = team_id
                    wlog(f'[green]     TEAM CREATED: team_id={team_id}[/green]')
                    created += 1
                    driver.get(url)  # volver a standings para el siguiente equipo
                except Exception as e:
                    wlog(f'[red][ERROR] creando "{team_name}": {type(e).__name__}: {e}[/red]')

            _locked_save(ls_file, data)
            wlog(f'[dim]  archivo guardado: {os.path.basename(ls_file)}[/dim]')
            if not_found:
                wlog(f'[yellow]  sin URL ni en standings ({len(not_found)}): {", ".join(not_found)}[/yellow]')
            wlog(f'[green]✔ {league_name} — URLs completadas: {filled} | creados en DB: {created}[/green]')


# ─────────────────────────────────────────────
#  WORKER
# ─────────────────────────────────────────────

def worker(worker_id, sport_leagues_dict, leagues_info_json=None, dict_sport_id=None, mode='creation'):
    _register_thread(worker_id)
    color     = WORKER_COLORS[worker_id % len(WORKER_COLORS)]
    n_leagues = sum(len(v) for v in sport_leagues_dict.values())
    wlog(f'[{color}]Driver iniciado — {n_leagues} ligas asignadas[/{color}]')

    retry_count = 0
    while retry_count <= MAX_WORKER_RETRIES:
        if _stop_event.is_set():
            with _state_lock:
                _worker_status[worker_id] = 'stopped'
                _worker_league[worker_id] = 'Detenido'
            return

        driver = launch_navigator('https://www.flashscore.com', headless=_should_use_headless())
        try:
            _save_worker_screenshot(driver, 'driver_ready', keep_history=True)
            if mode == 'check_url':
                _check_urls_worker(driver, sport_leagues_dict, dict_sport_id)
            else:
                _teams_creation_worker(driver, sport_leagues_dict, leagues_info_json, dict_sport_id)
            with _state_lock:
                _worker_status[worker_id] = 'done'
                _worker_league[worker_id] = 'Completado ✔'
            _save_worker_screenshot(driver, 'worker_completed', keep_history=True)
            wlog(f'[{color}]Extracción completada ✔[/{color}]')
            return

        except SystemExit:
            with _state_lock:
                _worker_status[worker_id] = 'stopped'
                _worker_league[worker_id] = 'Detenido'
            return

        except Exception as e:
            retry_count += 1
            wlog(f'[red]ERROR (intento {retry_count}/{MAX_WORKER_RETRIES}): {type(e).__name__}: {e}[/red]')
            _save_worker_screenshot(driver, f'error_retry_{retry_count}', keep_history=True)
            if retry_count > MAX_WORKER_RETRIES:
                with _state_lock:
                    _worker_status[worker_id] = 'error'
                    _worker_league[worker_id] = 'Error permanente'
                wlog(f'[red]Worker {worker_id} detenido tras {retry_count} reintentos[/red]')
                return
            with _state_lock:
                _worker_status[worker_id] = 'retrying'
                _worker_league[worker_id] = f'Reintentando... (#{retry_count}/{MAX_WORKER_RETRIES})'
            delay = min(30 * retry_count, 180)
            wlog(f'[yellow]Reiniciando driver en {delay}s...[/yellow]')
            time.sleep(delay)

        finally:
            try:
                driver.quit()
            except Exception:
                pass


# ─────────────────────────────────────────────
#  ENTRADA PRINCIPAL
# ─────────────────────────────────────────────

def run_parallel_teams(n_workers, sport_filter=None, confirm=True, check_url=False, selected_leagues_dict=None):
    console = Console()
    sport_label = f' [{sport_filter.upper()}]' if sport_filter else ''
    _stop_event.clear()
    _clear_latest_screenshots()

    if check_url:
        # ── Modo verificación de URLs ────────────────────────────────────────
        pending_raw, skipped = get_pending_url_check(sport_filter)
        mode_label = 'CHECK URL'

        if not pending_raw:
            console.print('[green]✔ Todas las URLs están completas en leagues_season/.[/green]')
            if skipped:
                console.print(f'[dim]  ({skipped} ligas ya OK)[/dim]')
            return

        # pending para split_into_workers: (sport, league_name, league_info, n_missing)
        league_dicts = split_into_workers(pending_raw, n_workers)
        save_worker_assignments(league_dicts)

        console.print(
            f'\n[cyan]━━━ CHECK URL{sport_label} — '
            f'{len(pending_raw)} ligas con URLs faltantes — {n_workers} workers ━━━[/cyan]'
        )

        if confirm:
            if not _show_distribution_check_url(league_dicts, pending_raw, console):
                console.print('[yellow]  Verificación cancelada.[/yellow]')
                return
        else:
            console.print(f'[dim]  {skipped} ligas ya OK → omitidas[/dim]')

        futures_kwargs = {
            idx: dict(mode='check_url')
            for idx in range(len(league_dicts))
        }
        submit_fn = lambda idx, d: executor_ref.submit(
            worker, idx, d, mode='check_url'
        )

    else:
        # ── Modo creación de equipos ─────────────────────────────────────────
        pending, skipped = (
            get_pending_selected_leagues(selected_leagues_dict)
            if selected_leagues_dict is not None
            else get_pending_leagues(sport_filter)
        )
        mode_label = 'TEAMS CREATION'

        if not pending:
            console.print('[green]✔ No hay ligas pendientes para teams_creation.[/green]')
            if skipped:
                console.print(f'[dim]  ({skipped} ya completas en leagues_season/)[/dim]')
            return

        league_dicts = split_into_workers(pending, n_workers)
        save_worker_assignments(league_dicts)

        console.print(
            f'\n[cyan]━━━ TEAMS CREATION{sport_label} — '
            f'{len(pending)} ligas pendientes — {n_workers} workers ━━━[/cyan]'
        )

        if confirm:
            if not _show_distribution(league_dicts, console, skipped):
                console.print('[yellow]  Ejecución cancelada.[/yellow]')
                return
        else:
            if skipped:
                console.print(f'[dim]  {skipped} ligas ya completas → omitidas[/dim]')
            console.print(f'[dim]  Asignaciones guardadas en {TMP_DIR}/[/dim]')

    # Cargar datos compartidos (dict_sport_id necesario en ambos modos)
    leagues_info_json = load_check_point(LEAGUES_INFO_FILE) if not check_url else None
    dict_sport_id     = {SPORT_NAME_MAP.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}

    # Inicializar estado de workers
    for i in range(n_workers):
        _worker_lines[i]  = []
        _worker_status[i] = 'running'
        _worker_league[i] = 'Iniciando...'

    layout = _build_layout(n_workers)

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    worker, idx, d, leagues_info_json, dict_sport_id,
                    'check_url' if check_url else 'creation'
                ): idx
                for idx, d in enumerate(league_dicts)
            }
            while futures:
                done_futures = {f for f in futures if f.done()}
                for future in done_futures:
                    idx = futures.pop(future)
                    try:
                        future.result()
                    except Exception:
                        with _state_lock:
                            _worker_status[idx] = 'error'
                _render_layout(layout, n_workers)
                if futures:
                    time.sleep(0.25)
        _render_layout(layout, n_workers)

    # Resumen final
    console.print()
    table = Table(title=f'Resumen — {mode_label}', show_header=True)
    table.add_column('Worker', style='bold')
    table.add_column('Estado')
    table.add_column('Ligas asignadas', justify='right')
    for i in range(n_workers):
        status = _worker_status.get(i, '?')
        color  = 'green' if status == 'done' else ('red' if status == 'error' else 'yellow')
        n_l    = sum(len(v) for v in league_dicts[i].values())
        table.add_row(f'Worker {i}', f'[{color}]{status}[/{color}]', str(n_l))
    console.print(table)


if __name__ == '__main__':
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    confirm   = '--no-confirm' not in sys.argv
    check_url = '--check_url' in sys.argv

    sport_filter = None
    selection_file = None
    for i, arg in enumerate(sys.argv):
        if arg == '--sport' and i + 1 < len(sys.argv):
            sport_filter = sys.argv[i + 1].upper()
        if arg == '--selection-file' and i + 1 < len(sys.argv):
            selection_file = sys.argv[i + 1]

    selected_leagues_dict = None
    if selection_file:
        with open(selection_file, encoding='utf-8') as f:
            selected_leagues_dict = json.load(f)

    run_parallel_teams(
        n_workers,
        sport_filter=sport_filter,
        confirm=confirm,
        check_url=check_url,
        selected_leagues_dict=selected_leagues_dict,
    )
