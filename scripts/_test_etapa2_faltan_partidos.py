#!/usr/bin/env python3
"""
ETAPA 2 — Partidos que necesitan ACTUALIZACIÓN.

Criterio (reusa get_pending_live_matches, el detector canónico del proyecto):
    fecha < hoy  AND  (status = 'LIVE'  OR  algún score_entity.points = -1)
es decir: partidos pasados que quedaron en LIVE o con score placeholder -1
(fixtures sin cerrar / incompletos). Se filtra a la liga indicada y se calcula
la FECHA MÁS ANTIGUA pendiente (target de la Etapa 3).

Solo LECTURA de DB (no escribe). No usa driver.

Uso:
    python scripts/_test_etapa2_faltan_partidos.py --league "FOOTBALL/RUSSIA_Premier League"
"""
import os
import sys
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from common_functions import load_json
from scripts.fix_live_matches import get_pending_live_matches

LEAGUES_INFO_PATH = 'check_points/leagues_info.json'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--league', required=True,
                   help='SPORT/COUNTRY_LeagueName, ej. "FOOTBALL/RUSSIA_Premier League"')
    p.add_argument('--limit', type=int, default=40,
                   help='cuántas filas mostrar (default 40)')
    args = p.parse_args()

    sport_key, league_key = args.league.split('/', 1)
    leagues_info = load_json(LEAGUES_INFO_PATH)

    print('=' * 72)
    print(f'ETAPA 2 — Partidos a actualizar: {sport_key} / {league_key}')
    print('=' * 72)

    try:
        info = leagues_info[sport_key][league_key]
    except KeyError:
        print(f'[FAIL] {sport_key}/{league_key} no existe en leagues_info.json')
        sys.exit(1)

    league_id = info['league_id']
    print(f'  league_id (DB): {league_id}')
    print('  criterio: fecha < hoy  AND  (status=LIVE  OR  score=-1)\n')

    # Detector canónico (todos los deportes/ligas); filtramos a esta liga.
    all_pending = get_pending_live_matches(verbose=False)
    matches = [m for m in all_pending if m['league_id'] == league_id]

    if not matches:
        print('  Sin partidos pendientes de actualización para esta liga.')
        print('=' * 72)
        return

    by_status = {}
    for m in matches:
        by_status[m['status']] = by_status.get(m['status'], 0) + 1
    oldest = min(m['match_date'] for m in matches if m['match_date'])
    newest = max(m['match_date'] for m in matches if m['match_date'])

    print(f'  TOTAL a actualizar : {len(matches)}')
    print(f'  Desglose por status: {by_status}')
    print(f'  Rango de fechas    : {oldest}  ->  {newest}')
    print(f'  >>> FECHA MÁS ANTIGUA pendiente (target Etapa 3): {oldest} <<<')

    print(f'\n  Detalle (primeros {args.limit}):')
    print('  %-12s %-10s  %s' % ('fecha', 'status', 'partido'))
    for m in matches[:args.limit]:
        print('  %-12s %-10s  %s' % (
            str(m['match_date']), (m['status'] or '')[:10], m['name']))
    if len(matches) > args.limit:
        print(f'  ... (+{len(matches) - args.limit} más)')

    print('\n' + '=' * 72)
    print('  ETAPA 2: OK — partidos a actualizar y fecha más antigua calculados.')
    print('=' * 72)


if __name__ == '__main__':
    main()
