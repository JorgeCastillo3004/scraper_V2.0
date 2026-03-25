"""
dashboard/app.py
────────────────
Dashboard web para control y monitorización del scraper.

Uso (en el servidor):
    cd /root/scraper_v3
    source <env>/bin/activate
    python dashboard/app.py

Acceso desde el navegador:
    http://<SERVER_IP>:8502
"""

import flet as ft
import json
import os
import re
import sys
import subprocess
import threading
import time
import psycopg2
from datetime import datetime

# ── Rutas ──────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUES_FILE = os.path.join(BASE_DIR, 'check_points', 'leagues_info.json')
LAST_NEWS    = os.path.join(BASE_DIR, 'check_points', 'last_saved_news.json')

sys.path.insert(0, BASE_DIR)
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

SUPPORTED_SPORTS = ['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY']

# ── Credenciales del dashboard ─────────────────────────────────────────────────
DASH_USER         = os.environ.get('DASH_USER', 'admin')
DASH_PASS         = os.environ.get('DASH_PASS', 'scraper2026')
DASH_DEV_SKIP_AUTH = os.environ.get('DASH_DEV_SKIP_AUTH', 'false').lower() == 'true'
SPORT_ICONS      = {
    'FOOTBALL': '⚽', 'BASKETBALL': '🏀', 'BASEBALL': '⚾',
    'AM._FOOTBALL': '🏈', 'HOCKEY': '🏒',
}
MAX_LOG_LINES = 300


# ═══════════════════════════════════════════════════════════════════════════════
#  PROCESS MANAGER — controla subprocesos del scraper
# ═══════════════════════════════════════════════════════════════════════════════

class ProcessManager:
    def __init__(self):
        self._procs: dict = {}
        self._lock  = threading.Lock()

    def start(self, key: str, cmd: list, stdin_input: str = None):
        with self._lock:
            if self.is_running(key):
                return None
            proc = subprocess.Popen(
                cmd, cwd=BASE_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if stdin_input else None,
                text=True, bufsize=1,
            )
            if stdin_input:
                try:
                    proc.stdin.write(stdin_input)
                    proc.stdin.flush()
                    proc.stdin.close()
                except Exception:
                    pass
            self._procs[key] = proc
            return proc

    def stop(self, key: str) -> bool:
        with self._lock:
            proc = self._procs.get(key)
            if proc and proc.poll() is None:
                proc.terminate()
                return True
            return False

    def is_running(self, key: str) -> bool:
        proc = self._procs.get(key)
        return proc is not None and proc.poll() is None


PM = ProcessManager()


# ═══════════════════════════════════════════════════════════════════════════════
#  DB STATS
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_db_stats() -> dict:
    try:
        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
            connect_timeout=5, options="-c statement_timeout=5000",
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM match"); m = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM team");  t = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM news");  n = cur.fetchone()[0]
        cur.close(); conn.close()
        return dict(matches=m, teams=t, news=n, ok=True)
    except Exception as ex:
        return dict(matches='?', teams='?', news='?', ok=False, error=str(ex))


# ═══════════════════════════════════════════════════════════════════════════════
#  LOG VIEWER — widget reutilizable con streaming de stdout
# ═══════════════════════════════════════════════════════════════════════════════

def make_log_viewer():
    """Devuelve (ListView, append_fn). append_fn(line, page) inserta línea y hace scroll."""
    lv = ft.ListView(expand=True, spacing=1, auto_scroll=True)

    def append(line: str, page: ft.Page, flush: bool = True):
        clean = re.sub(r'\x1b\[[0-9;?]*[mKlhJH]', '', line).rstrip()  # ANSI + bracketed paste
        if not clean:
            return
        if len(lv.controls) >= MAX_LOG_LINES:
            lv.controls.pop(0)
        color = (
            ft.Colors.RED_300    if any(w in clean for w in ('[ERROR]', 'Error', 'Traceback')) else
            ft.Colors.YELLOW_300 if any(w in clean for w in ('[WARN]',  'WARNING')) else
            ft.Colors.GREEN_300  if any(w in clean for w in ('[OK ]',   '✔', 'completado')) else
            ft.Colors.BLUE_200   if '[LIGA]' in clean else
            ft.Colors.GREY_300
        )
        lv.controls.append(
            ft.Text(clean, size=11, color=color, selectable=True,
                    font_family='Courier New')
        )
        if flush:
            try:
                page.update()  # flush directo — el caller puede usar _safe_update en su lugar
            except Exception:
                pass

    return lv, append


def stream_process(proc, append_fn, page: ft.Page, on_done=None):
    """Lee stdout en un hilo con batching cada 250ms para no saturar page.update()."""
    _buf = []
    _lock = threading.Lock()

    def _reader():
        for line in proc.stdout:
            with _lock:
                _buf.append(line)
        proc.wait()
        # Vaciar buffer restante
        with _lock:
            remaining = _buf[:]
            _buf.clear()
        for l in remaining:
            append_fn(l, page, flush=True)
        if on_done:
            on_done(proc.returncode, page)

    def _flusher():
        while proc.poll() is None:
            time.sleep(0.25)
            with _lock:
                lines = _buf[:]
                _buf.clear()
            if lines:
                for l in lines:
                    append_fn(l, page, flush=False)
                try:
                    page.update()
                except Exception:
                    pass

    threading.Thread(target=_reader,  daemon=True).start()
    threading.Thread(target=_flusher, daemon=True).start()


def log_container(lv: ft.ListView) -> ft.Container:
    return ft.Container(
        content=lv,
        bgcolor='#0d1117',
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=6,
        padding=8,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  HEADER — stats de DB + hora
# ═══════════════════════════════════════════════════════════════════════════════

def build_header(page: ft.Page) -> ft.Container:
    s = fetch_db_stats()

    def fmt(key, icon, label):
        v = s[key]
        return ft.Text(f"{icon} {label}: {v:,}" if isinstance(v, int) else f"{icon} {label}: {v}",
                       size=13, weight=ft.FontWeight.W_500)

    lbl_m    = fmt('matches', '⚽', 'Partidos')
    lbl_t    = fmt('teams',   '👥', 'Equipos')
    lbl_n    = fmt('news',    '📰', 'Noticias')
    lbl_time = ft.Text(datetime.now().strftime('%H:%M'), size=11, color=ft.Colors.GREY_400)
    dot      = ft.Icon(ft.Icons.CIRCLE, size=10,
                       color=ft.Colors.GREEN_400 if s['ok'] else ft.Colors.RED_400)

    def on_refresh(e):
        s2 = fetch_db_stats()
        for lbl, key, icon, label in [(lbl_m,'matches','⚽','Partidos'),
                                       (lbl_t,'teams',  '👥','Equipos'),
                                       (lbl_n,'news',   '📰','Noticias')]:
            v = s2[key]
            lbl.value = f"{icon} {label}: {v:,}" if isinstance(v, int) else f"{icon} {label}: {v}"
        lbl_time.value = datetime.now().strftime('%H:%M')
        dot.color      = ft.Colors.GREEN_400 if s2['ok'] else ft.Colors.RED_400
        page.update()

    return ft.Container(
        content=ft.Row([
            ft.Text('🕷  Scraper Dashboard', size=16, weight=ft.FontWeight.BOLD),
            ft.Container(width=1, height=24, bgcolor=ft.Colors.OUTLINE_VARIANT),
            dot, lbl_m, lbl_t, lbl_n,
            ft.Container(width=1, height=24, bgcolor=ft.Colors.OUTLINE_VARIANT),
            lbl_time,
            ft.IconButton(ft.Icons.REFRESH_ROUNDED, on_click=on_refresh,
                          tooltip='Actualizar stats DB', icon_size=18),
        ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
        padding=ft.Padding.symmetric(horizontal=20, vertical=10),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: LIGAS
# ═══════════════════════════════════════════════════════════════════════════════

def build_ligas_tab(page: ft.Page) -> ft.Control:
    leagues_data: dict = {}   # sport → {league → {results, fixtures, season_id, league_id}}
    data_tables:  dict = {}   # sport → ft.DataTable (para rebuild de rows en apply_stats)

    # ── 1. Carga ──────────────────────────────────────────────────────────────
    def load_data():
        nonlocal leagues_data
        with open(LEAGUES_FILE, encoding='utf-8') as f:
            raw = json.load(f)
        leagues_data = {}
        for sport in SUPPORTED_SPORTS:
            if sport not in raw:
                continue
            leagues_data[sport] = {}
            for league, info in raw[sport].items():
                leagues_data[sport][league] = {
                    'results':   info.get('extract_results',  {}).get('extract', False),
                    'fixtures':  info.get('extract_fixtures', {}).get('extract', False),
                    'season_id': info.get('season_id', ''),
                    'league_id': info.get('league_id', ''),
                }

    # ── 2. Guardado ───────────────────────────────────────────────────────────
    def save_data(e=None):
        with open(LEAGUES_FILE, encoding='utf-8') as f:
            raw = json.load(f)
        for sport, leagues in leagues_data.items():
            for league, vals in leagues.items():
                if sport in raw and league in raw[sport]:
                    raw[sport][league].setdefault('extract_results',  {})['extract'] = vals['results']
                    raw[sport][league].setdefault('extract_fixtures', {})['extract'] = vals['fixtures']
        with open(LEAGUES_FILE, 'w', encoding='utf-8') as f:
            json.dump(raw, f, ensure_ascii=False, indent=4)
        page.snack_bar = ft.SnackBar(
            ft.Text('✔  leagues_info.json guardado correctamente'),
            bgcolor=ft.Colors.GREEN_800)
        page.snack_bar.open = True
        page.update()

    # ── 3. Stats DB ───────────────────────────────────────────────────────────
    def fetch_league_stats() -> dict:
        """Retorna {(sport, league): {teams, completed, scheduled, live}}"""
        league_id_map = {}
        for sport, leagues in leagues_data.items():
            for lg, info in leagues.items():
                lid = info.get('league_id')
                if lid:
                    league_id_map[lid] = (sport, lg)

        if not league_id_map:
            return {}

        league_ids = list(league_id_map.keys())
        result = {}
        try:
            conn = psycopg2.connect(
                host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
                connect_timeout=5, options="-c statement_timeout=10000",
            )
            cur = conn.cursor()

            # Partidos por status agrupados por league_id
            cur.execute("""
                SELECT league_id,
                    COUNT(*) FILTER (WHERE status = 'COMPLETED')    AS completed,
                    COUNT(*) FILTER (WHERE status = 'SCHEDULED')    AS scheduled,
                    COUNT(*) FILTER (WHERE status = 'IN PROGRESS')  AS live
                FROM match
                WHERE league_id = ANY(%s)
                GROUP BY league_id
            """, (league_ids,))
            for lid, completed, scheduled, live in cur.fetchall():
                key = league_id_map.get(lid)
                if key:
                    result[key] = {'teams': 0, 'completed': completed,
                                   'scheduled': scheduled, 'live': live}

            # Equipos por league_id (merge league_team + team)
            cur.execute("""
                SELECT lt.league_id, COUNT(DISTINCT lt.team_id) AS teams
                FROM league_team lt
                JOIN team t ON lt.team_id = t.team_id
                WHERE lt.league_id = ANY(%s)
                GROUP BY lt.league_id
            """, (league_ids,))
            for lid, teams in cur.fetchall():
                key = league_id_map.get(lid)
                if key:
                    result.setdefault(key, {'completed': 0, 'scheduled': 0, 'live': 0})
                    result[key]['teams'] = teams

            cur.close()
            conn.close()
        except Exception:
            pass
        return result

    def apply_stats(stats: dict):
        for sport, dt in data_tables.items():
            dt.rows = build_sport_rows(sport, stats)
        page.update()

    def save_stats_to_leagues_info(stats: dict):
        """Actualiza teams y matches en leagues_info.json con los datos obtenidos de DB."""
        try:
            with open(LEAGUES_FILE, encoding='utf-8') as f:
                raw = json.load(f)
            changed = False
            for (sp, lg), data in stats.items():
                if sp in raw and lg in raw[sp]:
                    total_matches = data.get('completed', 0) + data.get('scheduled', 0) + data.get('live', 0)
                    raw[sp][lg]['teams']   = data.get('teams', 0)
                    raw[sp][lg]['matches'] = total_matches
                    changed = True
            if changed:
                with open(LEAGUES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(raw, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    # ── 4. Tabla por deporte ──────────────────────────────────────────────────
    def build_sport_rows(sport: str, stats: dict = None) -> list:
        rows = []
        for league in sorted(leagues_data.get(sport, {})):
            vals = leagues_data[sport][league]

            def make_switch(sp, lg, key, current_val):
                sw = ft.Switch(
                    value=current_val,
                    active_color=ft.Colors.GREEN_400,
                    inactive_thumb_color=ft.Colors.GREY_600,
                    scale=0.85,
                )
                def on_change(e, _sp=sp, _lg=lg, _k=key):
                    leagues_data[_sp][_lg][_k] = e.control.value
                sw.on_change = on_change
                return sw

            if stats is not None:
                data    = stats.get((sport, league), {})
                s_teams = str(data.get('teams',     0))
                s_comp  = str(data.get('completed', 0))
                s_sched = str(data.get('scheduled', 0))
                s_live  = str(data.get('live',      0))
            else:
                s_teams = s_comp = s_sched = s_live = '...'

            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(league, size=12)),
                ft.DataCell(ft.Text(s_teams, size=11, color=ft.Colors.GREY_400,  text_align=ft.TextAlign.RIGHT)),
                ft.DataCell(ft.Text(s_comp,  size=11, color=ft.Colors.GREEN_300, text_align=ft.TextAlign.RIGHT)),
                ft.DataCell(ft.Text(s_sched, size=11, color=ft.Colors.BLUE_200,  text_align=ft.TextAlign.RIGHT)),
                ft.DataCell(ft.Text(s_live,  size=11, color=ft.Colors.RED_300,   text_align=ft.TextAlign.RIGHT)),
                ft.DataCell(make_switch(sport, league, 'results',  vals['results'])),
                ft.DataCell(make_switch(sport, league, 'fixtures', vals['fixtures'])),
            ]))
        return rows

    def build_data_table(sport: str) -> ft.DataTable:
        dt = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text('Liga',        size=12, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('Equipos',     size=12, weight=ft.FontWeight.BOLD), numeric=True),
                ft.DataColumn(ft.Text('Completados', size=12, weight=ft.FontWeight.BOLD), numeric=True),
                ft.DataColumn(ft.Text('Programados', size=12, weight=ft.FontWeight.BOLD), numeric=True),
                ft.DataColumn(ft.Text('En vivo',     size=12, weight=ft.FontWeight.BOLD), numeric=True),
                ft.DataColumn(ft.Text('Results',     size=12, weight=ft.FontWeight.BOLD)),
                ft.DataColumn(ft.Text('Fixtures',    size=12, weight=ft.FontWeight.BOLD)),
            ],
            rows=build_sport_rows(sport),
            column_spacing=20,
            data_row_max_height=42,
            heading_row_height=40,
        )
        data_tables[sport] = dt
        return dt

    # ── 5. Tabs por deporte ───────────────────────────────────────────────────
    load_data()

    loading_row = ft.Row([
        ft.ProgressRing(width=14, height=14, stroke_width=2, color=ft.Colors.PRIMARY),
        ft.Text('Cargando stats de DB...', size=11, color=ft.Colors.GREY_400),
    ], visible=False, spacing=8)

    def make_sport_tabs():
        data_tables.clear()
        sports = [s for s in SUPPORTED_SPORTS if s in leagues_data]
        tab_bar  = ft.TabBar(
            tabs=[ft.Tab(label=f"{SPORT_ICONS.get(s, '🏅')} {s}") for s in sports],
            tab_alignment=ft.TabAlignment.START,
        )
        tab_view = ft.TabBarView(
            controls=[
                ft.Container(
                    content=ft.Column(
                        [build_data_table(s)],
                        scroll=ft.ScrollMode.AUTO, expand=True,
                    ),
                    padding=ft.Padding.only(top=12),
                    expand=True,
                )
                for s in sports
            ],
            expand=True,
        )
        return ft.Tabs(
            content=ft.Column([tab_bar, tab_view], expand=True, spacing=0),
            length=len(sports),
            selected_index=0,
            expand=True,
        )

    tabs_holder = ft.Container(content=make_sport_tabs(), expand=True)

    def refresh_stats(e=None):
        loading_row.visible = True
        page.update()
        def _fetch():
            stats = fetch_league_stats()
            apply_stats(stats)
            save_stats_to_leagues_info(stats)
            loading_row.visible = False
            n = len(stats)
            page.snack_bar = ft.SnackBar(
                ft.Text(f'✔  Stats actualizadas — {n} ligas'),
                bgcolor=ft.Colors.TEAL_800)
            page.snack_bar.open = True
            page.update()
        threading.Thread(target=_fetch, daemon=True).start()

    def on_reload(e):
        load_data()
        tabs_holder.content = make_sport_tabs()
        page.update()
        refresh_stats()

    # Contadores de ligas activas
    def count_active() -> str:
        r = sum(1 for sp in leagues_data.values() for v in sp.values() if v['results'])
        f = sum(1 for sp in leagues_data.values() for v in sp.values() if v['fixtures'])
        return f"Results activas: {r}  ·  Fixtures activas: {f}"

    lbl_count = ft.Text(count_active(), size=11, color=ft.Colors.GREY_400)

    def on_save(e):
        save_data()
        lbl_count.value = count_active()
        page.update()

    toolbar = ft.Row([
        ft.Button('💾 Guardar', on_click=on_save,
                          bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE),
        ft.OutlinedButton('🔄 Recargar', on_click=on_reload),
        ft.OutlinedButton('🔄 Actualizar desde DB', on_click=refresh_stats),
        ft.Container(expand=True),
        loading_row,
        lbl_count,
    ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Carga stats al arrancar
    refresh_stats()

    return ft.Container(
        content=ft.Column([
            toolbar,
            ft.Divider(height=8),
            tabs_holder,
        ], expand=True),
        padding=16,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: NOTICIAS
# ═══════════════════════════════════════════════════════════════════════════════

def build_noticias_tab(page: ft.Page) -> ft.Control:
    log_view, log_append = make_log_viewer()

    btn_start  = ft.Button('▶  Iniciar', bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE)
    btn_stop   = ft.Button('■  Detener', bgcolor=ft.Colors.RED_800,   color=ft.Colors.WHITE,
                                   disabled=True)
    lbl_status = ft.Text('Estado: inactivo', size=12, color=ft.Colors.GREY_400)

    def read_last_news() -> str:
        try:
            with open(LAST_NEWS, encoding='utf-8') as f:
                data = json.load(f)
            lines = []
            for sport, val in data.items():
                if isinstance(val, dict):
                    date   = val.get('last_date', '?')
                    phase2 = '  ⚠ FASE 2 pendiente' if 'phase2' in val else ''
                else:
                    date, phase2 = val, ''
                lines.append(f"  {sport}: {date}{phase2}")
            return '\n'.join(lines) or '  Sin datos'
        except Exception:
            return '  Archivo no encontrado'

    info_text = ft.Text(read_last_news(), size=12, color=ft.Colors.BLUE_200,
                        font_family='Courier New')

    def on_done(returncode, p):
        btn_start.disabled = False
        btn_stop.disabled  = True
        lbl_status.value   = f'Estado: finalizado (código {returncode})'
        lbl_status.color   = ft.Colors.GREEN_400 if returncode == 0 else ft.Colors.RED_400
        info_text.value    = read_last_news()
        p.update()

    def on_start(e):
        proc = PM.start('noticias', ['python3', 'main_manual_adjust.py'])
        if proc is None:
            log_append('⚠  Ya hay una extracción de noticias en curso', page)
            return
        btn_start.disabled = True
        btn_stop.disabled  = False
        lbl_status.value   = 'Estado: ejecutando...'
        lbl_status.color   = ft.Colors.YELLOW_400
        page.update()
        stream_process(proc, log_append, page, on_done=on_done)

    def on_stop(e):
        PM.stop('noticias')
        btn_stop.disabled  = True
        btn_start.disabled = False
        lbl_status.value   = 'Estado: detenido por usuario'
        lbl_status.color   = ft.Colors.ORANGE_400
        page.update()

    btn_start.on_click = on_start
    btn_stop.on_click  = on_stop

    return ft.Container(
        content=ft.Column([
            # ── Info checkpoint ────────────────────────────────────────────
            ft.Container(
                content=ft.Column([
                    ft.Text('Últimas fechas guardadas (last_saved_news.json):',
                            size=12, weight=ft.FontWeight.BOLD),
                    info_text,
                ]),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                padding=12, border_radius=8,
            ),
            ft.Divider(height=10),
            # ── Controles ─────────────────────────────────────────────────
            ft.Row([btn_start, btn_stop, lbl_status], spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=6),
            # ── Log ───────────────────────────────────────────────────────
            ft.Text('Log de ejecución:', size=12, weight=ft.FontWeight.BOLD),
            log_container(log_view),
        ], expand=True),
        padding=16,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: PARTIDOS — panel por sección con control de archivo
# ═══════════════════════════════════════════════════════════════════════════════

LOGS_DIR          = os.path.join(BASE_DIR, 'logs')
STATUS_FILE_TMPL  = os.path.join(LOGS_DIR, 'run_status_{section}.json')
CONTROL_FILE_TMPL = os.path.join(LOGS_DIR, 'run_control_{section}.json')

SECTION_COLORS = {'results': ft.Colors.GREEN_400, 'fixtures': ft.Colors.BLUE_400}
WORKER_STATUS_COLORS = {
    'running':  ft.Colors.YELLOW_300,
    'done':     ft.Colors.GREEN_300,
    'error':    ft.Colors.RED_300,
    'retrying': ft.Colors.ORANGE_300,
    'stopped':  ft.Colors.GREY_400,
    'idle':     ft.Colors.GREY_600,
}


def _read_status(section: str) -> dict:
    try:
        with open(STATUS_FILE_TMPL.format(section=section), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_control(section: str, command: str):
    os.makedirs(LOGS_DIR, exist_ok=True)
    try:
        with open(CONTROL_FILE_TMPL.format(section=section), 'w', encoding='utf-8') as f:
            json.dump({'command': command}, f)
    except Exception:
        pass


def _get_league_distribution(section: str, n_workers: int) -> list[dict]:
    """
    Lee leagues_info.json y devuelve la misma distribución que haría
    paralel_execution.py: lista de n_workers dicts {sport: [leagues]}.
    """
    extract_key = 'extract_results' if section == 'results' else 'extract_fixtures'
    try:
        with open(LEAGUES_FILE, encoding='utf-8') as f:
            raw = json.load(f)
    except Exception:
        return []
    enabled = []
    for sport in SUPPORTED_SPORTS:
        for lg, info in raw.get(sport, {}).items():
            if info.get(extract_key, {}).get('extract', False):
                enabled.append((sport, lg))
    dicts = [{} for _ in range(max(n_workers, 1))]
    for i, (sport, lg) in enumerate(enabled):
        dicts[i % n_workers].setdefault(sport, []).append(lg)
    return dicts


def _build_distribution_dialog(page: ft.Page, section: str, n_workers: int,
                                on_confirm) -> ft.AlertDialog:
    """Diálogo que muestra la distribución de ligas y pide confirmación."""
    dist = _get_league_distribution(section, n_workers)
    worker_colors = [
        ft.Colors.CYAN_300, ft.Colors.YELLOW_300, ft.Colors.GREEN_300,
        ft.Colors.PURPLE_200, ft.Colors.BLUE_300, ft.Colors.RED_300,
        ft.Colors.WHITE, ft.Colors.TEAL_300,
    ]
    rows = []
    for idx, d in enumerate(dist):
        color = worker_colors[idx % len(worker_colors)]
        n_l   = sum(len(v) for v in d.values())
        leagues_flat = [f"{s} / {lg}" for s, lgs in d.items() for lg in lgs]
        rows.append(ft.DataRow(cells=[
            ft.DataCell(ft.Text(f'W{idx}', size=11, color=color, weight=ft.FontWeight.BOLD)),
            ft.DataCell(ft.Text(str(n_l), size=11, color=color)),
            ft.DataCell(ft.Text('\n'.join(leagues_flat), size=10, color=ft.Colors.GREY_300)),
        ]))

    total = sum(sum(len(v) for v in d.values()) for d in dist)
    table = ft.DataTable(
        columns=[
            ft.DataColumn(ft.Text('Worker', size=11, weight=ft.FontWeight.BOLD)),
            ft.DataColumn(ft.Text('Ligas', size=11, weight=ft.FontWeight.BOLD), numeric=True),
            ft.DataColumn(ft.Text('Asignaciones', size=11, weight=ft.FontWeight.BOLD)),
        ],
        rows=rows,
        column_spacing=16,
        data_row_max_height=None,
        heading_row_height=36,
    )

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(f'Distribución de ligas — {section.upper()}  ({total} ligas)'),
        content=ft.Container(
            content=ft.Column([table], scroll=ft.ScrollMode.AUTO),
            width=540, height=380,
        ),
        actions=[
            ft.TextButton('Cancelar', on_click=lambda e: _close_dialog(page, dlg)),
            ft.FilledButton('▶  Iniciar', on_click=lambda e: (_close_dialog(page, dlg), on_confirm())),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg


def _close_dialog(page: ft.Page, dlg: ft.AlertDialog):
    dlg.open = False
    page.update()


def build_section_panel(page: ft.Page, section: str) -> ft.Control:
    """Panel de control para una sección (results o fixtures)."""
    color  = SECTION_COLORS.get(section, ft.Colors.PRIMARY)
    pm_key = f'partidos_{section}'

    dd_workers = ft.Dropdown(
        label='Workers', width=100, value='4',
        options=[ft.dropdown.Option(str(i)) for i in range(1, 9)],
    )

    lbl_state   = ft.Text('⬤  inactivo', size=12, color=ft.Colors.GREY_500)
    lbl_updated = ft.Text('', size=10, color=ft.Colors.GREY_600)

    btn_start  = ft.Button('▶  Iniciar',  bgcolor=ft.Colors.GREEN_800, color=ft.Colors.WHITE)
    btn_stop   = ft.Button('■  Detener',  bgcolor=ft.Colors.RED_800,   color=ft.Colors.WHITE, disabled=True)
    btn_pause  = ft.Button('⏸  Pausar',   bgcolor=ft.Colors.ORANGE_800, color=ft.Colors.WHITE, disabled=True)
    btn_resume = ft.Button('▶  Reanudar', bgcolor=ft.Colors.BLUE_800,  color=ft.Colors.WHITE, disabled=True, visible=False)

    # Contenedor de cards de workers (se reconstruye al recibir status)
    workers_row = ft.Row([], spacing=8, wrap=True)

    def _make_worker_card(wid: str, wdata: dict) -> ft.Container:
        status = wdata.get('status', 'idle')
        league = wdata.get('league', '—')
        lines  = wdata.get('lines', [])
        wcolor = WORKER_STATUS_COLORS.get(status, ft.Colors.GREY_400)

        status_icons = {'running': '●', 'done': '✔', 'error': '✘',
                        'retrying': '↺', 'stopped': '■', 'idle': '○'}
        icon = status_icons.get(status, '●')

        log_texts = [
            ft.Text(re.sub(r'\[/?[^\]]+\]', '', ln), size=10,
                    color=ft.Colors.GREY_400, font_family='Courier New')
            for ln in lines[-8:]
        ]

        return ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(f'{icon} WORKER {wid}', size=12,
                            weight=ft.FontWeight.BOLD, color=wcolor),
                ]),
                ft.Text(league, size=11, color=wcolor,
                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                ft.Divider(height=4, color=ft.Colors.OUTLINE_VARIANT),
                ft.Column(log_texts, spacing=1),
            ], spacing=4),
            bgcolor='#0d1117',
            border=ft.Border.all(1, wcolor),
            border_radius=6,
            padding=8,
            width=240,
            expand=False,
        )

    def _update_ui_from_status(status: dict):
        state     = status.get('state', '')
        updated   = status.get('updated_at', '')[:19].replace('T', ' ')

        # Labels
        state_colors = {
            'running':   ft.Colors.YELLOW_400,
            'paused':    ft.Colors.ORANGE_400,
            'completed': ft.Colors.GREEN_400,
            'stopped':   ft.Colors.GREY_400,
            'starting':  ft.Colors.BLUE_400,
        }
        state_icons = {
            'running': '▶', 'paused': '⏸', 'completed': '✔',
            'stopped': '■', 'starting': '…',
        }
        lbl_state.value = f"{state_icons.get(state, '⬤')}  {state or 'inactivo'}"
        lbl_state.color = state_colors.get(state, ft.Colors.GREY_500)
        lbl_updated.value = f'actualizado: {updated}' if updated else ''

        # Botones
        is_running = state in ('running', 'starting')
        is_paused  = state == 'paused'
        is_idle    = state in ('', 'completed', 'stopped')

        btn_start.disabled  = not is_idle
        btn_stop.disabled   = is_idle
        btn_pause.disabled  = not is_running
        btn_pause.visible   = not is_paused
        btn_resume.disabled = not is_paused
        btn_resume.visible  = is_paused

        # Worker cards
        workers_row.controls.clear()
        workers = status.get('workers', {})
        for wid in sorted(workers.keys(), key=lambda x: int(x)):
            workers_row.controls.append(_make_worker_card(wid, workers[wid]))
        if not workers_row.controls:
            workers_row.controls.append(
                ft.Text('Sin workers activos', size=11, color=ft.Colors.GREY_600)
            )

    def _poll_status():
        while True:
            time.sleep(2)
            try:
                status = _read_status(section)
                if status:
                    _update_ui_from_status(status)
                    page.update()
                # Si el proceso terminó, actualizar botones
                if not PM.is_running(pm_key):
                    status = _read_status(section)
                    if status.get('state') not in ('running', 'paused', 'starting'):
                        btn_start.disabled = False
                        btn_stop.disabled  = True
                        btn_pause.disabled = True
                        btn_pause.visible  = True
                        btn_resume.visible = False
                        page.update()
            except Exception:
                pass

    # Iniciar hilo de polling
    threading.Thread(target=_poll_status, daemon=True).start()

    # Leer estado inicial si existe
    initial = _read_status(section)
    if initial:
        _update_ui_from_status(initial)

    def _do_start():
        n = dd_workers.value or '4'
        proc = PM.start(pm_key, [
            'python3', 'paralel_execution.py', n, section, '--no-confirm'
        ])
        if proc is None:
            page.snack_bar = ft.SnackBar(
                ft.Text(f'⚠  Ya hay una ejecución de {section} en curso'),
                bgcolor=ft.Colors.ORANGE_800)
            page.snack_bar.open = True
            page.update()
            return
        btn_start.disabled  = True
        btn_stop.disabled   = False
        btn_pause.disabled  = False
        lbl_state.value     = '▶  iniciando...'
        lbl_state.color     = ft.Colors.BLUE_400
        page.update()
        # Consumir stdout para evitar bloqueo de buffer
        def _drain():
            try:
                for _ in proc.stdout:
                    pass
            except Exception:
                pass
        threading.Thread(target=_drain, daemon=True).start()

    def on_start(e):
        n = int(dd_workers.value or '4')
        dlg = _build_distribution_dialog(page, section, n, _do_start)
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def on_stop(e):
        _write_control(section, 'stop')
        # Dar tiempo al proceso para leer el comando y terminar limpiamente
        def _force_kill():
            time.sleep(8)
            PM.stop(pm_key)
        threading.Thread(target=_force_kill, daemon=True).start()
        lbl_state.value = '■  deteniendo...'
        lbl_state.color = ft.Colors.ORANGE_400
        page.update()

    def on_pause(e):
        _write_control(section, 'pause')
        lbl_state.value = '⏸  pausando...'
        lbl_state.color = ft.Colors.ORANGE_400
        page.update()

    def on_resume(e):
        _write_control(section, 'resume')
        lbl_state.value = '▶  reanudando...'
        lbl_state.color = ft.Colors.YELLOW_400
        page.update()

    btn_start.on_click  = on_start
    btn_stop.on_click   = on_stop
    btn_pause.on_click  = on_pause
    btn_resume.on_click = on_resume

    icon = '⚽' if section == 'results' else '📅'
    return ft.Container(
        content=ft.Column([
            # ── Header ──────────────────────────────────────────────────
            ft.Row([
                ft.Text(f'{icon}  {section.upper()}', size=14,
                        weight=ft.FontWeight.BOLD, color=color),
                ft.Container(expand=True),
                lbl_state,
                lbl_updated,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=6),
            # ── Controles ───────────────────────────────────────────────
            ft.Row([
                dd_workers,
                ft.Container(width=4),
                btn_start, btn_stop, btn_pause, btn_resume,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6),
            ft.Divider(height=8),
            # ── Worker cards ─────────────────────────────────────────────
            workers_row,
        ], spacing=6),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        padding=12,
        expand=True,
    )


def build_partidos_tab(page: ft.Page) -> ft.Control:
    panel_results  = build_section_panel(page, 'results')
    panel_fixtures = build_section_panel(page, 'fixtures')

    return ft.Container(
        content=ft.Column([
            ft.Text('Ejecuciones paralelas — Results y Fixtures pueden correr simultáneamente',
                    size=11, color=ft.Colors.GREY_500),
            ft.Divider(height=6),
            ft.Row([panel_results, panel_fixtures],
                   spacing=12, expand=True,
                   vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True),
        padding=16,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: JUGADORES
# ═══════════════════════════════════════════════════════════════════════════════

def build_jugadores_tab(page: ft.Page) -> ft.Control:
    """Panel de control para extracción de jugadores (milestone6 vía main_manual_adjust.py)."""
    log_view, log_append = make_log_viewer()
    lbl_status = ft.Text('Estado: inactivo', size=12, color=ft.Colors.GREY_400)
    btn_start  = ft.Button('▶  Iniciar extracción', bgcolor=ft.Colors.GREEN_800,
                                   color=ft.Colors.WHITE)
    btn_stop   = ft.Button('■  Detener', bgcolor=ft.Colors.RED_800,
                                   color=ft.Colors.WHITE, disabled=True)

    # Stats de jugadores en DB
    lbl_stats = ft.Text('', size=12, color=ft.Colors.BLUE_200, font_family='Courier New')

    def load_player_stats():
        try:
            conn = psycopg2.connect(
                host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
                connect_timeout=5, options="-c statement_timeout=5000",
            )
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM player")
            n_players = cur.fetchone()[0]
            cur.execute("""
                SELECT l.league_name, COUNT(DISTINCT tp.player_id) AS n
                FROM team_players_entity tp
                JOIN league_team lt ON lt.team_id = tp.team_id
                JOIN league l ON l.league_id = lt.league_id
                GROUP BY l.league_name
                ORDER BY n DESC
                LIMIT 10
            """)
            rows = cur.fetchall()
            cur.close(); conn.close()
            lines = [f'  Total jugadores: {n_players}', '', '  Top 10 ligas por jugadores:']
            for league, n in rows:
                lines.append(f'    {league:<35} {n:>5}')
            lbl_stats.value = '\n'.join(lines)
        except Exception as ex:
            lbl_stats.value = f'  Error consultando DB: {ex}'
        page.update()

    def on_done(returncode, p):
        btn_start.disabled = False
        btn_stop.disabled  = True
        lbl_status.value   = f'Estado: finalizado (código {returncode})'
        lbl_status.color   = ft.Colors.GREEN_400 if returncode == 0 else ft.Colors.RED_400
        load_player_stats()
        p.update()

    def on_start(e):
        proc = PM.start('jugadores', ['python3', 'main_manual_adjust.py', '--players-only'])
        if proc is None:
            log_append('⚠  Ya hay una extracción de jugadores en curso', page)
            return
        btn_start.disabled = True
        btn_stop.disabled  = False
        lbl_status.value   = 'Estado: ejecutando...'
        lbl_status.color   = ft.Colors.YELLOW_400
        page.update()
        stream_process(proc, log_append, page, on_done=on_done)

    def on_stop(e):
        PM.stop('jugadores')
        btn_stop.disabled  = True
        btn_start.disabled = False
        lbl_status.value   = 'Estado: detenido por usuario'
        lbl_status.color   = ft.Colors.ORANGE_400
        page.update()

    btn_start.on_click = on_start
    btn_stop.on_click  = on_stop

    # Carga stats al abrir
    threading.Thread(target=load_player_stats, daemon=True).start()

    return ft.Container(
        content=ft.Column([
            ft.Text('👤  Extracción de Jugadores', size=14, weight=ft.FontWeight.BOLD,
                    color=ft.Colors.PURPLE_300),
            ft.Divider(height=6),
            ft.Container(
                content=ft.Column([
                    ft.Text('Jugadores en DB:', size=12, weight=ft.FontWeight.BOLD),
                    lbl_stats,
                ]),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                padding=12, border_radius=8,
            ),
            ft.Divider(height=8),
            ft.Row([btn_start, btn_stop, lbl_status], spacing=12,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=6),
            ft.Text('Log de ejecución:', size=12, weight=ft.FontWeight.BOLD),
            log_container(log_view),
        ], expand=True),
        padding=16,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  TAB: EN VIVO
# ═══════════════════════════════════════════════════════════════════════════════

def build_envivo_tab(page: ft.Page) -> ft.Control:
    """Panel de control para el scraper en vivo via sesión tmux 'live'."""
    log_view, log_append = make_log_viewer()
    lbl_status = ft.Text('Estado: inactivo', size=12, color=ft.Colors.GREY_400)
    lbl_tmux   = ft.Text('🔴 tmux:live no existe', size=11, color=ft.Colors.RED_400)

    # Lock + evento de desconexión — evita RuntimeError y WebSocketDisconnect
    _ui_lock      = threading.Lock()
    _disconnected = threading.Event()

    def _safe_update():
        if _disconnected.is_set():
            return
        with _ui_lock:
            try:
                page.update()
            except Exception:
                _disconnected.set()   # cualquier error = cliente desconectado, parar

    def _on_disconnect(e=None):
        _disconnected.set()

    page.on_disconnect = _on_disconnect

    TMUX_SESSION      = 'live'
    LIVE_LOG_FILE     = os.path.join(BASE_DIR, 'dashboard', 'live_output.log')
    LIVE_CONTROL_FILE = os.path.join(LOGS_DIR, 'run_control_live.json')
    LIVE_STATUS_FILE  = os.path.join(LOGS_DIR, 'run_status_live.json')
    VENV_PYTHON       = '/home/you/env/sports_env/bin/python'
    VENV_ACTIVATE     = 'source /home/you/env/sports_env/bin/activate'

    # ── Helpers tmux ──────────────────────────────────────────────────────────
    def _tmux_run(args: list) -> bool:
        try:
            r = subprocess.run(['tmux'] + args, capture_output=True, text=True)
            return r.returncode == 0
        except Exception:
            return False

    def _tmux_session_exists() -> bool:
        return _tmux_run(['has-session', '-t', TMUX_SESSION])

    def _tmux_ensure_session():
        """Crea la sesión si no existe con venv activado y pipe-pane al log file."""
        if not _tmux_session_exists():
            _tmux_run(['new-session', '-d', '-s', TMUX_SESSION])
            time.sleep(0.4)
            _tmux_run(['send-keys', '-t', TMUX_SESSION, VENV_ACTIVATE, 'Enter'])
            time.sleep(0.6)
        # Reiniciar pipe-pane de forma idempotente:
        # 1) Detener cualquier pipe-pane activo (sin arg = stop; no-op si no había)
        _tmux_run(['pipe-pane', '-t', TMUX_SESSION])
        time.sleep(0.1)
        # 2) Iniciar sin -o para que SIEMPRE se active (no condicional)
        _tmux_run(['pipe-pane', '-t', TMUX_SESSION,
                   f'cat >> {LIVE_LOG_FILE}'])

    def _tmux_send(keys: str):
        _tmux_run(['send-keys', '-t', TMUX_SESSION, keys, 'Enter'])

    def _tmux_interrupt():
        """Envía Ctrl+C a la sesión tmux."""
        _tmux_run(['send-keys', '-t', TMUX_SESSION, 'C-c'])

    # ── Control JSON ──────────────────────────────────────────────────────────
    def _write_live_control(command: str):
        os.makedirs(LOGS_DIR, exist_ok=True)
        try:
            with open(LIVE_CONTROL_FILE, 'w', encoding='utf-8') as f:
                json.dump({'command': command}, f)
        except Exception:
            pass

    def _read_live_status() -> dict:
        try:
            with open(LIVE_STATUS_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _is_process_running() -> bool:
        return _read_live_status().get('state') in ('running', 'paused')

    # ── Widgets ───────────────────────────────────────────────────────────────
    sport_checks = {s: ft.Checkbox(label=f'{SPORT_ICONS.get(s,"")} {s}', value=(s == 'FOOTBALL'))
                    for s in SUPPORTED_SPORTS}

    INTERVAL_OPTIONS = [
        ('30 seg',  '30'),
        ('1 min',   '60'),
        ('2 min',  '120'),
        ('5 min',  '300'),
        ('10 min', '600'),
    ]
    dd_interval = ft.Dropdown(
        label='Intervalo entre ciclos', width=180, value='60',
        options=[ft.dropdown.Option(key=v, text=lbl) for lbl, v in INTERVAL_OPTIONS],
    )

    spinner    = ft.ProgressRing(width=16, height=16, stroke_width=2,
                                  color=ft.Colors.RED_400, visible=False)
    btn_toggle = ft.Button('▶  Iniciar', bgcolor=ft.Colors.RED_800, color=ft.Colors.WHITE)
    btn_stop   = ft.Button('■  Detener', bgcolor=ft.Colors.GREY_800, color=ft.Colors.WHITE, disabled=True)

    # Estado del proceso: 'stopped' | 'running' | 'paused'
    _state      = ['stopped']
    _state_lock = threading.Lock()

    def _set_state(val: str):
        with _state_lock:
            _state[0] = val

    def _get_state() -> str:
        with _state_lock:
            return _state[0]

    def _apply_toggle_look():
        s = _get_state()
        if s in ('stopped', 'stopping'):
            btn_toggle.text    = '▶  Iniciar'
            btn_toggle.bgcolor = ft.Colors.RED_800
            btn_stop.disabled  = True
        elif s == 'running':
            btn_toggle.text    = '⏸  Pausar'
            btn_toggle.bgcolor = ft.Colors.ORANGE_700
            btn_stop.disabled  = False
        elif s == 'paused':
            btn_toggle.text    = '▶  Reanudar'
            btn_toggle.bgcolor = ft.Colors.GREEN_700
            btn_stop.disabled  = False

    # ── Tail del log file — siempre activo ────────────────────────────────────
    _ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\r')

    def _tail_log():
        """Sigue LIVE_LOG_FILE desde que se abre el tab. Para al desconectar."""
        while not _disconnected.is_set() and not os.path.exists(LIVE_LOG_FILE):
            time.sleep(1)
        if _disconnected.is_set():
            return

        def _open_at_end():
            fh = open(LIVE_LOG_FILE, 'r', encoding='utf-8', errors='replace')
            fh.seek(0, 2)
            return fh, os.fstat(fh.fileno()).st_ino

        f, current_inode = _open_at_end()
        try:
            while not _disconnected.is_set():
                line = f.readline()
                if line:
                    clean = _ANSI_RE.sub('', line).strip()
                    if clean:
                        log_append(clean, page, flush=False)
                        _safe_update()
                else:
                    time.sleep(0.3)
                    try:
                        if os.stat(LIVE_LOG_FILE).st_ino != current_inode:
                            f.close()
                            f, current_inode = _open_at_end()
                            log_append('[INFO] log file recreado — reconectado', page, flush=False)
                            _safe_update()
                    except FileNotFoundError:
                        pass
        finally:
            f.close()

    threading.Thread(target=_tail_log, daemon=True).start()

    # ── Pipe-pane init — activar desde el arranque del tab ────────────────────
    def _init_pipe():
        """Activa pipe-pane si la sesión ya existe al abrir el tab."""
        time.sleep(1)
        if _tmux_session_exists():
            _tmux_run(['pipe-pane', '-t', TMUX_SESSION])
            time.sleep(0.1)
            _tmux_run(['pipe-pane', '-t', TMUX_SESSION, '-o', f'cat >> {LIVE_LOG_FILE}'])

    threading.Thread(target=_init_pipe, daemon=True).start()

    # ── Polling de estado via status JSON ─────────────────────────────────────
    def _poll_status():
        last_state = ''
        while not _disconnected.is_set():
            time.sleep(2)
            if _disconnected.is_set():
                break

            # Indicador sesión tmux
            tmux_ok        = _tmux_session_exists()
            lbl_tmux.value = '🟢 tmux:live activa' if tmux_ok else '🔴 tmux:live no existe'
            lbl_tmux.color = ft.Colors.GREEN_400    if tmux_ok else ft.Colors.RED_400

            # Sincronizar estado desde status JSON
            # Si la UI está en 'stopping', no sobreescribir con 'running' del JSON
            # (el proceso aún no procesó el comando stop)
            st    = _read_live_status()
            state = st.get('state', '')
            if state != last_state:
                last_state = state
                if state == 'running' and _get_state() == 'stopping':
                    pass  # esperar a que main2.py confirme el stop
                elif state == 'running':
                    sports_active    = ', '.join(st.get('sports', []))
                    lbl_status.value = f'Estado: ejecutando — {sports_active}'
                    lbl_status.color = ft.Colors.RED_400
                    spinner.visible  = False
                    _set_state('running')
                    _apply_toggle_look()
                elif state == 'paused':
                    lbl_status.value = 'Estado: pausado'
                    lbl_status.color = ft.Colors.ORANGE_400
                    spinner.visible  = False
                    _set_state('paused')
                    _apply_toggle_look()
                elif state in ('stopped', 'error'):
                    lbl_status.value = 'Estado: detenido' if state == 'stopped' else 'Estado: error'
                    lbl_status.color = ft.Colors.GREY_400 if state == 'stopped' else ft.Colors.RED_400
                    spinner.visible  = False
                    _set_state('stopped')
                    _apply_toggle_look()
            _safe_update()

    threading.Thread(target=_poll_status, daemon=True).start()

    # ── Handler botón toggle (Iniciar / Pausar / Reanudar) ───────────────────
    def on_toggle(e):
        s = _get_state()

        if s == 'stopped':
            selected = [sp for sp, cb in sport_checks.items() if cb.value]
            if not selected:
                log_append('⚠  Selecciona al menos un deporte', page, flush=False)
                _safe_update()
                return
            interval_val = dd_interval.value or '60'
            _set_state('running')
            spinner.visible  = True
            lbl_status.value = f'Estado: iniciando — {", ".join(selected)}  |  intervalo: {interval_val}s'
            lbl_status.color = ft.Colors.RED_400
            _apply_toggle_look()
            log_append(f'[INFO] Iniciando — deportes: {", ".join(selected)}  intervalo: {interval_val}s', page, flush=False)
            _safe_update()

            def _start_bg():
                _write_live_control('none')
                _tmux_ensure_session()
                sports_arg = ' '.join(selected)
                cmd = f'cd {BASE_DIR} && {VENV_PYTHON} main2.py --interval {interval_val} --sports {sports_arg}'
                _tmux_send(cmd)
                log_append(f'[INFO] Comando enviado: {cmd}', page, flush=False)
                _safe_update()
            threading.Thread(target=_start_bg, daemon=True).start()

        elif s == 'running':
            _set_state('paused')
            lbl_status.value = 'Estado: pausando...'
            lbl_status.color = ft.Colors.ORANGE_300
            _apply_toggle_look()
            log_append('[INFO] Comando pause enviado', page, flush=False)
            _safe_update()
            threading.Thread(target=_write_live_control, args=('pause',), daemon=True).start()

        elif s == 'paused':
            _set_state('running')
            lbl_status.value = 'Estado: reanudando...'
            lbl_status.color = ft.Colors.RED_400
            _apply_toggle_look()
            log_append('[INFO] Comando resume enviado', page, flush=False)
            _safe_update()
            threading.Thread(target=_write_live_control, args=('resume',), daemon=True).start()

    # ── Handler botón Detener ─────────────────────────────────────────────────
    def on_stop(e):
        _set_state('stopping')   # estado intermedio: bloquea el poll de sobreescribir
        spinner.visible  = False
        lbl_status.value = 'Estado: deteniendo...'
        lbl_status.color = ft.Colors.ORANGE_400
        _apply_toggle_look()
        log_append('[INFO] Comando stop enviado', page, flush=False)
        _safe_update()

        def _stop_bg():
            _write_live_control('stop')
            time.sleep(4)
            _tmux_interrupt()
        threading.Thread(target=_stop_bg, daemon=True).start()

    # ── Botón Ver sesión tmux ────────────────────────────────────────────────
    dlg_tmux = ft.AlertDialog(
        title=ft.Text('Conectar a sesión tmux'),
        content=ft.Column([
            ft.Text('Ejecuta este comando en una terminal del servidor:',
                    size=12, color=ft.Colors.GREY_400),
            ft.Container(
                content=ft.Text(f'tmux attach -t live', size=13,
                                font_family='monospace', selectable=True,
                                color=ft.Colors.GREEN_300),
                bgcolor=ft.Colors.with_opacity(0.12, ft.Colors.PRIMARY),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                border_radius=6,
            ),
            ft.Text('Para desconectarte sin matar la sesión: Ctrl+B  D',
                    size=11, color=ft.Colors.GREY_500),
        ], tight=True, spacing=10),
        actions=[ft.TextButton('Cerrar', on_click=lambda e: setattr(dlg_tmux, 'open', False) or page.update())],
    )

    def on_ver_tmux(e):
        page.overlay.append(dlg_tmux)
        dlg_tmux.open = True
        page.update()

    btn_ver_tmux = ft.OutlinedButton('🖥  Ver sesión tmux', on_click=on_ver_tmux)

    btn_toggle.on_click = on_toggle
    btn_stop.on_click   = on_stop

    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text('🔴  En Vivo — tmux:live', size=14, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.RED_400),
                lbl_tmux,
            ], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=6),
            # ── Selector de deportes + intervalo ──────────────────────
            ft.Container(
                content=ft.Column([
                    ft.Text('Deportes activos:', size=12, weight=ft.FontWeight.BOLD),
                    ft.Row(list(sport_checks.values()), spacing=16, wrap=True),
                    ft.Divider(height=8),
                    ft.Row([dd_interval], spacing=12),
                ]),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.PRIMARY),
                padding=12, border_radius=8,
            ),
            ft.Divider(height=8),
            # ── Controles ─────────────────────────────────────────────
            ft.Row([btn_toggle, btn_stop, btn_ver_tmux], spacing=8),
            ft.Row([spinner, lbl_status], spacing=10,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(height=6),
            ft.Text('Output tmux live:', size=12, weight=ft.FontWeight.BOLD),
            log_container(log_view),
        ], expand=True),
        padding=16,
        expand=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGIN
# ═══════════════════════════════════════════════════════════════════════════════

def build_login_view(page: ft.Page, on_success):
    txt_user = ft.TextField(label='Usuario', width=280, autofocus=True,
                            border_color=ft.Colors.OUTLINE_VARIANT)
    txt_pass = ft.TextField(label='Contraseña', width=280, password=True,
                            can_reveal_password=True,
                            border_color=ft.Colors.OUTLINE_VARIANT)
    lbl_err  = ft.Text('', color=ft.Colors.RED_400, size=12)

    def attempt_login(e=None):
        if txt_user.value == DASH_USER and txt_pass.value == DASH_PASS:
            page.session.store.set('authenticated', True)
            on_success()
        else:
            lbl_err.value = '  Usuario o contraseña incorrectos'
            txt_pass.value = ''
            page.update()

    txt_pass.on_submit = attempt_login

    return ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.LOCK_ROUNDED, size=48, color=ft.Colors.PRIMARY),
            ft.Text('Scraper Dashboard', size=20, weight=ft.FontWeight.BOLD),
            ft.Text('Acceso restringido', size=12, color=ft.Colors.GREY_500),
            ft.Divider(height=20, color=ft.Colors.TRANSPARENT),
            txt_user,
            txt_pass,
            lbl_err,
            ft.Divider(height=8, color=ft.Colors.TRANSPARENT),
            ft.FilledButton('Entrar', width=280, on_click=attempt_login,
                            icon=ft.Icons.LOGIN_ROUNDED),
        ],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=10,
        ),
        alignment=ft.Alignment.CENTER,
        expand=True,
    )


def build_dashboard(page: ft.Page):
    page.controls.clear()

    header = build_header(page)

    tab_labels   = ['📰  Noticias', '🏆  Ligas', '⚽  Partidos', '👤  Jugadores', '🔴  En Vivo']
    tab_contents = [
        build_noticias_tab(page),
        build_ligas_tab(page),
        build_partidos_tab(page),
        build_jugadores_tab(page),
        build_envivo_tab(page),
    ]
    tab_bar  = ft.TabBar(tabs=[ft.Tab(label=lbl) for lbl in tab_labels])
    tab_view = ft.TabBarView(controls=tab_contents, expand=True)
    tabs = ft.Tabs(
        content=ft.Column([tab_bar, tab_view], expand=True, spacing=0),
        length=len(tab_labels),
        selected_index=0,
        expand=True,
    )

    # Botón cerrar sesión en la esquina
    def on_logout(e):
        page.session.store.clear()
        page.controls.clear()
        page.add(build_login_view(page, lambda: build_dashboard(page)))
        page.update()

    btn_logout = ft.IconButton(
        ft.Icons.LOGOUT_ROUNDED, tooltip='Cerrar sesión',
        icon_size=18, icon_color=ft.Colors.GREY_400,
        on_click=on_logout,
    )

    page.add(
        ft.Column([
            ft.Stack([
                header,
                ft.Container(content=btn_logout,
                             alignment=ft.Alignment.CENTER_RIGHT,
                             padding=ft.Padding.only(right=8)),
            ]),
            ft.Container(content=tabs, expand=True),
        ], expand=True, spacing=0)
    )
    page.update()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main(page: ft.Page):
    page.title      = 'Scraper Dashboard'
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor    = ft.Colors.SURFACE
    page.padding    = 0

    if DASH_DEV_SKIP_AUTH or page.session.store.contains_key('authenticated'):
        build_dashboard(page)
    else:
        page.add(build_login_view(page, lambda: build_dashboard(page)))


if __name__ == '__main__':
    # FLET_NO_BROWSER=1 → solo servidor web, sin abrir pestaña (usado por run_dev.py en reinicios)
    no_browser = os.environ.get('FLET_NO_BROWSER', '0') == '1'
    ft.run(main, view=None if no_browser else ft.AppView.WEB_BROWSER, port=8502)
