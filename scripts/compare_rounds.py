"""
compare_rounds.py
-----------------
Compara el número de partidos en la DB vs los archivos de ronda pendientes
para cada liga habilitada en leagues_info.json.

Los archivos de ronda almacenan matches incompletos. Al completarse el
procesamiento de una liga, los archivos se eliminan. Si existen → pendiente.

Uso:
    python scripts/compare_rounds.py results
    python scripts/compare_rounds.py fixtures
    python scripts/compare_rounds.py results --sport FOOTBALL
    python scripts/compare_rounds.py results --fix-status   # actualiza status en leagues_info
"""

import sys
import os
import json
import glob
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from common_functions import load_check_point, save_check_point
import psycopg2

# ── Configuración ──────────────────────────────────────────────────────────────
LEAGUES_INFO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'check_points', 'leagues_info.json')
CHECKPOINTS  = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'check_points')
SUPPORTED    = {'FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY'}

# ── DB ─────────────────────────────────────────────────────────────────────────
def get_db_matches(cur, league_id):
    cur.execute("""
        SELECT COUNT(m.match_id)
        FROM match m
        JOIN season s ON m.season_id = s.season_id
        WHERE s.league_id = %s
    """, (league_id,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


def get_db_teams(cur, league_id):
    cur.execute("""
        SELECT COUNT(lt.team_id)
        FROM league_team lt
        JOIN season s ON lt.league_id = s.league_id
        WHERE s.league_id = %s
    """, (league_id,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


# ── Round files ─────────────────────────────────────────────────────────────────
def count_round_matches(section, league_name):
    """Cuenta matches en archivos de ronda pendientes para una liga."""
    folder = os.path.join(CHECKPOINTS, section, league_name)
    if not os.path.isdir(folder):
        return 0, []
    files = glob.glob(os.path.join(folder, '*.json'))
    total = 0
    file_names = []
    for f in sorted(files):
        try:
            with open(f) as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                total += len(data)
            elif isinstance(data, list):
                total += len(data)
            file_names.append(os.path.basename(f))
        except Exception:
            pass
    return total, file_names


# ── Fix status ──────────────────────────────────────────────────────────────────
def resolve_status(db_matches, db_teams, has_rounds):
    """
    Determina el status de una liga según el estado actual:
      - Sin equipos en DB                        → 'pending'
      - Matches > 0 y sin archivos de ronda      → 'completed'
      - Cualquier otro caso                      → None (no modificar)
    """
    if db_teams == 0:
        return 'pending'
    if db_matches > 0 and not has_rounds:
        return 'completed'
    return None


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('section', nargs='?', default='results', choices=['results', 'fixtures'])
    parser.add_argument('--sport', default=None, help='Filtrar por deporte (ej: FOOTBALL)')
    parser.add_argument('--fix-status', action='store_true',
                        help='Actualiza el campo status en leagues_info.json según estado actual')
    args = parser.parse_args()

    section     = args.section
    extract_key = 'extract_results' if section == 'results' else 'extract_fixtures'

    leagues_info = load_check_point(LEAGUES_INFO)
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()

    rows        = []
    status_changes = []

    for sport, leagues in leagues_info.items():
        if sport not in SUPPORTED:
            continue
        if args.sport and sport != args.sport.upper():
            continue
        for league_name, info in leagues.items():
            league_id   = info.get('league_id', '')
            db_matches  = get_db_matches(cur, league_id)
            db_teams    = get_db_teams(cur, league_id)
            rnd_matches, rnd_files = count_round_matches(section, league_name)
            has_rounds  = len(rnd_files) > 0
            current_status = info.get(extract_key, {}).get('status', '—')
            enabled     = info.get(extract_key, {}).get('extract', False)

            new_status = None
            if args.fix_status:
                new_status = resolve_status(db_matches, db_teams, has_rounds)
                if new_status and new_status != current_status:
                    if extract_key not in info:
                        info[extract_key] = {}
                    info[extract_key]['status'] = new_status
                    # Limpiar claves temporales si existen
                    for k in ('sport_name', 'sport_id', 'league_name'):
                        info.pop(k, None)
                    status_changes.append((sport, league_name, current_status, new_status))

            rows.append({
                'sport':          sport,
                'league':         league_name,
                'enabled':        enabled,
                'db':             db_matches,
                'teams':          db_teams,
                'pending':        rnd_matches,
                'has_rounds':     has_rounds,
                'status':         new_status if new_status else current_status,
            })

    cur.close()

    if args.fix_status and status_changes:
        save_check_point(LEAGUES_INFO, leagues_info)
        print(f'\n  ✔ {len(status_changes)} status actualizados en leagues_info.json')
        for sport, league, old, new in status_changes:
            print(f'    {sport}/{league}: {old} → {new}')

    con.close()

    # ── Imprimir tabla ─────────────────────────────────────────────────────────
    W = 95
    SEP = '─' * W
    print(f'\n{"═"*W}')
    print(f'  COMPARACIÓN DB vs RONDAS PENDIENTES  [{section.upper()}]')
    print(f'{"═"*W}')
    print(f'  {"DEPORTE":<15} {"LIGA":<33} {"EQUIPOS":>7} {"DB":>6}  {"RONDAS":>7}  {"ESTADO":<12}  {"PEND."}')
    print(SEP)

    total_db = total_pending = 0
    for r in sorted(rows, key=lambda x: (x['sport'], x['league'])):
        flag      = '⚠ ' if r['has_rounds'] else '✔ '
        pend_flag = '● PENDIENTE' if r['has_rounds'] else '—'
        print(f"  {flag}{r['sport']:<13} {r['league']:<33} {r['teams']:>7} {r['db']:>6}  {r['pending']:>7}  {r['status']:<12}  {pend_flag}")
        total_db      += r['db']
        total_pending += r['pending']

    print(SEP)
    print(f'  {"TOTAL":<55} {total_db:>6}  {total_pending:>7}')
    print(f'{"═"*W}\n')

    if total_pending > 0:
        print(f'  ⚠  {total_pending} matches en archivos de ronda pendientes de completar.')
    else:
        print(f'  ✔  No hay archivos de ronda pendientes — todas las ligas procesadas.')
    print()


if __name__ == '__main__':
    main()
