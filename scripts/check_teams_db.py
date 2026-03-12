"""
check_teams_db.py
-----------------
Actualiza leagues_info.json con los conteos reales de equipos y partidos
desde la base de datos, y habilita la extracción para ligas que tienen
equipos pero pocos partidos.

Lógica de habilitación:
    teams > 0  AND  matches < MATCH_THRESHOLD
    → extract_results.extract  = True
    → extract_fixtures.extract = True

Uso:
    source /home/you/env/sports_env/bin/activate
    python check_teams_db.py
"""

import sys
import os
import json
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
from common_functions import load_check_point, save_check_point

# ─── Configuración ────────────────────────────────────────────────────────────

LI_FILE        = 'check_points/leagues_info.json'
MATCH_THRESHOLD = 20   # ligas con menos de este número de partidos se habilitan


# ─── Conexión ─────────────────────────────────────────────────────────────────

def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


# ─── Queries ──────────────────────────────────────────────────────────────────

def count_teams_by_league(cur, league_id):
    cur.execute(
        "SELECT COUNT(DISTINCT team_id) FROM league_team WHERE league_id = %s;",
        (league_id,)
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def count_matches_by_league(cur, league_id):
    cur.execute(
        "SELECT COUNT(*) FROM match WHERE league_id = %s;",
        (league_id,)
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    leagues_info = load_check_point(LI_FILE)

    print("Conectando a la base de datos...")
    con = get_connection()
    cur = con.cursor()

    enabled  = []
    updated  = 0
    skipped  = 0

    for sport_name, leagues in leagues_info.items():
        for league_key, league_info in leagues.items():
            league_id = league_info.get('league_id', '')
            if not league_id:
                skipped += 1
                continue

            teams   = count_teams_by_league(cur, league_id)
            matches = count_matches_by_league(cur, league_id)

            league_info['teams']   = teams
            league_info['matches'] = matches
            updated += 1

            # Habilitar si tiene equipos y pocos partidos
            if teams > 0 and matches < MATCH_THRESHOLD:
                league_info.setdefault('extract_results',  {})['extract'] = True
                league_info.setdefault('extract_fixtures', {})['extract'] = True
                enabled.append(f'{sport_name} / {league_key}  (teams={teams}, matches={matches})')

            print(f'  {sport_name} / {league_key}: {teams} equipos, {matches} partidos')

    cur.close()
    con.close()

    save_check_point(LI_FILE, leagues_info)

    print()
    print('=' * 60)
    print(f'  Ligas actualizadas : {updated}')
    print(f'  Ligas habilitadas  : {len(enabled)}')
    print(f'  Sin league_id      : {skipped}')
    print('=' * 60)
    if enabled:
        print('\nHabilitadas para extracción:')
        for e in enabled:
            print(f'  + {e}')
