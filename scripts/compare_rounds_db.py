"""
compare_rounds_db.py
====================
Compara los partidos almacenados en la base de datos contra los archivos round.json
generados por el scraper para cada liga, mostrando results (COMPLETED) y fixtures
(SCHEDULED) en una misma tabla, e indica cuáles ligas están completas o pendientes.

LÓGICA DE COMPARACIÓN
---------------------
  Para cada liga y sección (results / fixtures):

    expected  = suma de matches en todos los archivos *.json dentro de
                check_points/results/{liga}/   o   check_points/fixtures/{liga}/

    db_count  = COUNT(*) de la tabla `match` filtrado por:
                  league_id  y  status = 'COMPLETED'  (para results)
                  league_id  y  status = 'SCHEDULED'  (para fixtures)

    Resultado:
      'sin rounds'  → No existen archivos round para esa sección (aún no se
                      han generado con milestone1).
      'completed'   → db_count >= expected  (extracción completa).
      'pending'     → db_count  < expected  (faltan partidos por extraer).

HABILITACIÓN DE EXTRACCIÓN
--------------------------
  Tras mostrar la tabla, el script pregunta cómo habilitar las ligas pendientes
  modificando extract_results.extract / extract_fixtures.extract en
  check_points/leagues_info.json:

    [1] Habilitar TODAS (results + fixtures pendientes)
    [2] Habilitar solo results pendientes
    [3] Habilitar solo fixtures pendientes
    [4] Habilitar una a una (pregunta liga por liga)
    [0] Salir sin cambios

USO
---
    python scripts/compare_rounds_db.py

REQUISITOS
----------
    - config.py con DB_HOST, DB_NAME, DB_USER, DB_PASS
    - check_points/leagues_info.json
    - check_points/results/{COUNTRY_League}/*.json  (generados por milestone1)
    - check_points/fixtures/{COUNTRY_League}/*.json (generados por milestone1)
    - Librerías: psycopg2, rich
"""

import json
import os
import glob
import sys

import psycopg2
from rich.console import Console
from rich.table import Table
from rich import box

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

console = Console()

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEAGUES_INFO = os.path.join(BASE_DIR, 'check_points', 'leagues_info.json')
CP_RESULTS   = os.path.join(BASE_DIR, 'check_points', 'results')
CP_FIXTURES  = os.path.join(BASE_DIR, 'check_points', 'fixtures')


# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db_counts(league_ids: list) -> dict:
    """
    Devuelve { league_id: {'COMPLETED': N, 'SCHEDULED': N} } en una sola query.
    """
    if not league_ids:
        return {}
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute("""
        SELECT league_id, status, COUNT(*)
        FROM match
        WHERE league_id = ANY(%s)
          AND status IN ('COMPLETED', 'SCHEDULED')
        GROUP BY league_id, status
    """, (league_ids,))
    rows = cur.fetchall()
    cur.close()
    con.close()

    result = {lid: {'COMPLETED': 0, 'SCHEDULED': 0} for lid in league_ids}
    for league_id, status, count in rows:
        if league_id in result:
            result[league_id][status] = count
    return result


# ── Round files ─────────────────────────────────────────────────────────────────
def count_round_matches(base_cp: str, league_key: str) -> int:
    """Suma todos los matches en los *.json de la carpeta de una liga."""
    folder = os.path.join(base_cp, league_key)
    if not os.path.isdir(folder):
        return 0
    total = 0
    for fpath in glob.glob(os.path.join(folder, '*.json')):
        try:
            with open(fpath, encoding='utf-8') as f:
                data = json.load(f)
            total += len(data) if isinstance(data, (dict, list)) else 0
        except Exception:
            pass
    return total


# ── Status helpers ──────────────────────────────────────────────────────────────
def calc_status(db_count: int, expected: int) -> str:
    if expected == 0:
        return 'sin rounds'
    return 'completed' if db_count >= expected else 'pending'


STATUS_STYLE = {
    'completed':  ('green',  '✔'),
    'pending':    ('yellow', '●'),
    'sin rounds': ('dim',    '—'),
}


def rich_status(status: str, db: int, expected: int) -> str:
    color, icon = STATUS_STYLE.get(status, ('white', '?'))
    return f'[{color}]{icon} {status}[/{color}]\n[dim]{db}/{expected}[/dim]'


# ── leagues_info ────────────────────────────────────────────────────────────────
def load_leagues_info() -> dict:
    with open(LEAGUES_INFO, encoding='utf-8') as f:
        return json.load(f)


def save_leagues_info(data: dict):
    with open(LEAGUES_INFO, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def enable_section(leagues_info: dict, sport: str, league_key: str, section: str):
    """Setea extract_results.extract o extract_fixtures.extract = True."""
    key = f'extract_{section}'
    entry = leagues_info[sport][league_key]
    if key in entry:
        entry[key]['extract'] = True
    else:
        entry[key] = {'extract': True, 'round': '', 'match': ''}


# ── Report ──────────────────────────────────────────────────────────────────────
def build_report(leagues_info: dict) -> list:
    all_ids = []
    entries = []
    for sport, leagues in leagues_info.items():
        for league_key, meta in leagues.items():
            lid = meta.get('league_id', '')
            all_ids.append(lid)
            entries.append({'sport': sport, 'league_key': league_key,
                            'league_id': lid, 'meta': meta})

    db_counts = get_db_counts(all_ids)

    report = []
    for e in entries:
        lid  = e['league_id']
        meta = e['meta']
        db   = db_counts.get(lid, {'COMPLETED': 0, 'SCHEDULED': 0})

        exp_r = count_round_matches(CP_RESULTS,  e['league_key'])
        exp_f = count_round_matches(CP_FIXTURES, e['league_key'])

        db_r  = db['COMPLETED']
        db_f  = db['SCHEDULED']

        report.append({
            'sport':            e['sport'],
            'league_key':       e['league_key'],
            'league_id':        lid,
            'exp_results':      exp_r,
            'exp_fixtures':     exp_f,
            'db_results':       db_r,
            'db_fixtures':      db_f,
            'status_results':   calc_status(db_r, exp_r),
            'status_fixtures':  calc_status(db_f, exp_f),
            'enabled_results':  meta.get('extract_results',  {}).get('extract', False),
            'enabled_fixtures': meta.get('extract_fixtures', {}).get('extract', False),
        })
    return report


def print_table(report: list):
    table = Table(
        title='[bold cyan]Comparación rounds vs DB[/bold cyan]',
        box=box.ROUNDED,
        show_lines=True,
        header_style='bold cyan',
        min_width=110,
    )
    table.add_column('#',          style='dim',   width=4,  justify='right')
    table.add_column('Sport',      style='cyan',  width=14)
    table.add_column('Liga',                      width=32)
    table.add_column('Results\n[dim](COMPLETED)[/dim]',  width=22, justify='center')
    table.add_column('Fixtures\n[dim](SCHEDULED)[/dim]', width=22, justify='center')
    table.add_column('Extracción\nhabilitada',            width=18, justify='center')

    pending_r = pending_f = 0

    for i, row in enumerate(report, 1):
        r_str = rich_status(row['status_results'],  row['db_results'],  row['exp_results'])
        f_str = rich_status(row['status_fixtures'], row['db_fixtures'], row['exp_fixtures'])

        en_parts = []
        if row['enabled_results']:  en_parts.append('[green]✔ results[/green]')
        if row['enabled_fixtures']: en_parts.append('[green]✔ fixtures[/green]')
        enabled_str = '\n'.join(en_parts) or '[dim]—[/dim]'

        table.add_row(str(i), row['sport'], row['league_key'], r_str, f_str, enabled_str)

        if row['status_results']  == 'pending': pending_r += 1
        if row['status_fixtures'] == 'pending': pending_f += 1

    console.print(table)
    console.print(
        f'\n[yellow]Pendientes:[/yellow] '
        f'[bold]{pending_r}[/bold] results  ·  [bold]{pending_f}[/bold] fixtures\n'
    )


# ── Habilitación ────────────────────────────────────────────────────────────────
def ask_enable(report: list, leagues_info: dict, full_report: list = None):
    pending = [r for r in report
               if r['status_results'] == 'pending' or r['status_fixtures'] == 'pending']

    if not pending:
        console.print('[green]✔ No hay ligas pendientes.[/green]')
        return

    console.print('[bold]¿Qué ligas pendientes deseas habilitar para extracción?[/bold]\n')
    console.print('  [bold][1][/bold] Habilitar [bold]TODAS[/bold] (results + fixtures pendientes)')
    console.print('  [bold][2][/bold] Habilitar solo [bold]results[/bold] pendientes')
    console.print('  [bold][3][/bold] Habilitar solo [bold]fixtures[/bold] pendientes')
    console.print('  [bold][4][/bold] Habilitar [bold]una a una[/bold] (pregunta liga por liga)')
    console.print('  [bold][0][/bold] Salir sin cambios\n')

    choice = input('Opción: ').strip()

    if choice == '0':
        console.print('[dim]Sin cambios.[/dim]')
        return

    changed = 0

    if choice in ('1', '2', '3'):
        for row in pending:
            if choice in ('1', '2') and row['status_results'] == 'pending':
                enable_section(leagues_info, row['sport'], row['league_key'], 'results')
                changed += 1
            if choice in ('1', '3') and row['status_fixtures'] == 'pending':
                enable_section(leagues_info, row['sport'], row['league_key'], 'fixtures')
                changed += 1

    elif choice == '4':
        console.print('\n  [bold]¿Sobre qué ligas iterar?[/bold]')
        console.print('    [bold][a][/bold] a - Verificar una a una [bold]todas[/bold] las ligas')
        console.print('    [bold][b][/bold] b - Verificar una a una solo las [bold]pending[/bold]\n')
        sub = input('  Sub-opción: ').strip().lower()

        if sub == 'a':
            iterate_over = full_report or report
        elif sub == 'b':
            iterate_over = pending
        else:
            console.print('[red]Sub-opción no válida. Sin cambios.[/red]')
            return

        for row in iterate_over:
            st_r = row['status_results']
            st_f = row['status_fixtures']

            # En opción 4b solo preguntamos por secciones que están pending.
            # En opción 4a preguntamos por todas las secciones no habilitadas.
            ask_r = (st_r == 'pending') if sub == 'b' else (st_r != 'sin rounds')
            ask_f = (st_f == 'pending') if sub == 'b' else (st_f != 'sin rounds')

            if not ask_r and not ask_f:
                continue  # nada que preguntar para esta liga

            r_info = f'{st_r} ({row["db_results"]}/{row["exp_results"]})'
            f_info = f'{st_f} ({row["db_fixtures"]}/{row["exp_fixtures"]})'

            console.print(
                f'\n  [cyan]{row["league_key"]}[/cyan]  [dim]({row["sport"]})[/dim]\n'
                f'    results:  [{STATUS_STYLE.get(st_r, ("white",""))[0]}]{r_info}[/{STATUS_STYLE.get(st_r, ("white",""))[0]}]'
                f'  |  fixtures: [{STATUS_STYLE.get(st_f, ("white",""))[0]}]{f_info}[/{STATUS_STYLE.get(st_f, ("white",""))[0]}]'
            )

            if ask_r:
                ans = input('    ¿Habilitar results?  [s/N]: ').strip().lower()
                if ans == 's':
                    enable_section(leagues_info, row['sport'], row['league_key'], 'results')
                    changed += 1

            if ask_f:
                ans = input('    ¿Habilitar fixtures? [s/N]: ').strip().lower()
                if ans == 's':
                    enable_section(leagues_info, row['sport'], row['league_key'], 'fixtures')
                    changed += 1
    else:
        console.print('[red]Opción no válida. Sin cambios.[/red]')
        return

    if changed:
        save_leagues_info(leagues_info)
        console.print(
            f'\n[green]✔ {changed} sección(es) habilitadas.[/green] '
            f'[dim]leagues_info.json actualizado.[/dim]'
        )
    else:
        console.print('[dim]Sin cambios aplicados.[/dim]')


# ── Entry point ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    console.print('\n[bold cyan]═══ compare_rounds_db.py ═══[/bold cyan]\n')
    leagues_info = load_leagues_info()
    report       = build_report(leagues_info)
    print_table(report)
    ask_enable(report, leagues_info, full_report=report)
