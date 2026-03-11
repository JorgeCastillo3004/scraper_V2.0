"""
rebuild_leagues_season.py
Reconstruye los archivos faltantes en check_points/leagues_season/{sport}/{league}.json
usando datos de la base de datos.

Formato de cada archivo:
{
    "Team Name": {
        "team_id": "uuid",
        "team_url": "https://...",
        "stadium_id": "uuid"
    },
    ...
}
"""

import os
import sys
import json
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
os.chdir('/home/you/work_2026')

from common_functions import load_check_point, save_check_point

# ── Conexión DB ────────────────────────────────────────────────────────────────
con = psycopg2.connect(
    host="DB_HOST",
    user="DB_USER",
    password="DB_PASS",
    dbname='sports_db',
)
cur = con.cursor()

# ── Cargar leagues_info para obtener league_name, sport_name, league_id ───────
leagues_info = load_check_point('check_points/leagues_info.json')

created = []
skipped = []
errors  = []

for sport_name, leagues in leagues_info.items():
    sport_dir = os.path.join('check_points', 'leagues_season', sport_name)
    os.makedirs(sport_dir, exist_ok=True)

    for key, league_info in leagues.items():
        league_name = league_info.get('league_name', '')
        league_id   = league_info.get('league_id', '')

        if not league_name or not league_id:
            continue

        file_path = os.path.join(sport_dir, f'{key}.json')

        # Si ya existe, no sobreescribir
        if os.path.exists(file_path):
            skipped.append(f'{sport_name} / {key}')
            continue

        # ── Consultar equipos de esta liga en la DB ────────────────────────
        try:
            cur.execute("""
                SELECT t.team_name, t.team_id
                FROM league_team lt
                JOIN team t ON lt.team_id = t.team_id
                WHERE lt.league_id = %s
            """, (league_id,))
            rows = cur.fetchall()
        except Exception as e:
            errors.append(f'{sport_name} / {key}: DB error — {e}')
            con.rollback()
            continue

        if not rows:
            print(f'  [EMPTY]  {sport_name} / {key} — sin equipos en DB')
            continue

        # ── Construir dict y guardar ───────────────────────────────────────
        dict_league = {}
        for team_name, team_id in rows:
            dict_league[team_name] = {
                'team_id':    team_id,
                'team_url':   '',
                'stadium_id': '',
            }

        save_check_point(file_path, dict_league)
        created.append(f'{sport_name} / {key}  ({len(rows)} equipos)')
        print(f'  [OK]  {sport_name} / {key}  — {len(rows)} equipos → {file_path}')

con.close()

# ── Resumen ────────────────────────────────────────────────────────────────────
print()
print('=' * 60)
print(f'  Archivos creados  : {len(created)}')
print(f'  Ya existían       : {len(skipped)}')
print(f'  Errores           : {len(errors)}')
print('=' * 60)
if created:
    print('\nCreados:')
    for x in created:
        print(f'  + {x}')
if errors:
    print('\nErrores:')
    for x in errors:
        print(f'  ! {x}')
