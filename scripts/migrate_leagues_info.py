"""
migrate_leagues_info.py
Agrega a cada liga en leagues_info.json:
  - teams, matches   (desde teams_report.json)
  - teams_creation   {extract, last_team_created}
  - extract_results  {extract, round, match}
  - extract_fixtures {extract, match}

Idempotente: no sobreescribe keys que ya existan.
"""

import json
import os

os.chdir('/home/you/work_2026')

LEAGUES_INFO_PATH  = 'check_points/leagues_info.json'
TEAMS_REPORT_PATH  = 'check_points/teams_report.json'

# Mapeo de sport name en leagues_info → sport name en teams_report
SPORT_NAME_MAP = {
    'AM._FOOTBALL': 'AMERICAN FOOTBALL',
}

with open(LEAGUES_INFO_PATH, 'r', encoding='utf-8') as f:
    leagues_info = json.load(f)

with open(TEAMS_REPORT_PATH, 'r', encoding='utf-8') as f:
    teams_report = json.load(f)

added   = 0
skipped = 0

for sport_li, leagues in leagues_info.items():
    # Nombre equivalente en teams_report
    sport_tr = SPORT_NAME_MAP.get(sport_li, sport_li)
    tr_sport  = teams_report.get(sport_tr, {})

    for league_key, league_data in leagues.items():
        tr_league = tr_sport.get(league_key, {})

        # ── teams y matches ────────────────────────────────────────────────
        if 'teams' not in league_data:
            league_data['teams'] = tr_league.get('teams', 0)
            added += 1
        else:
            skipped += 1

        if 'matches' not in league_data:
            league_data['matches'] = tr_league.get('matches', 0)
            added += 1
        else:
            skipped += 1

        # ── teams_creation ─────────────────────────────────────────────────
        if 'teams_creation' not in league_data:
            league_data['teams_creation'] = {
                'extract': False,
                'last_team_created': ''
            }
            added += 1
        else:
            skipped += 1

        # ── extract_results ────────────────────────────────────────────────
        if 'extract_results' not in league_data:
            league_data['extract_results'] = {
                'extract': False,
                'round':   '',
                'match':   ''
            }
            added += 1
        else:
            skipped += 1

        # ── extract_fixtures ───────────────────────────────────────────────
        if 'extract_fixtures' not in league_data:
            league_data['extract_fixtures'] = {
                'extract': False,
                'round':   '',
                'match':   ''                
            }
            added += 1
        else:
            skipped += 1

with open(LEAGUES_INFO_PATH, 'w', encoding='utf-8') as f:
    json.dump(leagues_info, f, indent=4, ensure_ascii=False)

print(f'  Campos agregados  : {added}')
print(f'  Campos existentes : {skipped}')
print(f'  Archivo guardado  : {LEAGUES_INFO_PATH}')
