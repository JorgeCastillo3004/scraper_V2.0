#!/usr/bin/env python3
"""
ETAPA 1 — Cargar la liga correcta.

Verifica que, dada una liga de `leagues_info.json`, el scraper:
  1. resuelve su `results_url`,
  2. navega esa URL en el driver VIVO (no relanza Firefox),
  3. la página cargada corresponde a esa liga (encabezado + URL).

Reutiliza: find_results_url / wait_update_page / dismiss_cookies (ya probados).
Engancha el driver con driver_session.get_driver() — NUNCA driver.quit().

Uso:
    python scripts/_test_etapa1_carga_liga.py --league "FOOTBALL/BRAZIL_Serie A Betano"
"""
import os
import sys
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from common_functions import wait_update_page, dismiss_cookies, load_json
from scripts.fix_live_matches import find_results_url
from scripts.driver_session import get_driver

LEAGUES_INFO_PATH = 'check_points/leagues_info.json'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--league', required=True,
                   help='SPORT/COUNTRY_LeagueName, ej. "FOOTBALL/BRAZIL_Serie A Betano"')
    args = p.parse_args()

    sport_key, league_key = args.league.split('/', 1)
    country_name, _, league_name = league_key.partition('_')

    leagues_info = load_json(LEAGUES_INFO_PATH)

    print('=' * 72)
    print(f'ETAPA 1 — Cargar liga: {sport_key} / {league_key}')
    print('=' * 72)

    # 1) Resolver entrada + results_url
    try:
        info = leagues_info[sport_key][league_key]
    except KeyError:
        print(f'[FAIL] {sport_key}/{league_key} no existe en leagues_info.json')
        sys.exit(1)

    results_url = info.get('results') or info.get('url')
    league_id   = info.get('league_id')
    print(f'  league_id (DB) : {league_id}')
    print(f'  results_url    : {results_url}')

    # find_results_url debe llegar a la misma URL (consistencia del helper)
    via_helper = find_results_url(leagues_info, sport_key, country_name, league_name)
    ok_helper = (via_helper == results_url)
    print(f'  find_results_url coincide: {ok_helper}  ({via_helper})')

    if not results_url:
        print('[FAIL] la liga no tiene results_url en leagues_info.')
        sys.exit(1)

    # 2) Navegar en el driver vivo
    driver = get_driver()
    print('\n  Navegando...')
    wait_update_page(driver, results_url, 'container__heading')
    dismiss_cookies(driver)

    # 3) Verificar que la página cargada es la liga correcta
    cur_url = driver.current_url
    try:
        heading = driver.find_element(
            'class name', 'heading__name').text
    except Exception:
        heading = '(no encontrado)'
    try:
        breadcrumb = driver.find_element(
            'class name', 'container__heading').text.replace('\n', ' | ')
    except Exception:
        breadcrumb = '(no encontrado)'

    print('\n  RESULTADO:')
    print(f'    current_url   : {cur_url}')
    print(f'    heading liga  : {heading}')
    print(f'    breadcrumb    : {breadcrumb}')

    # Heurística de validación: el nombre de la liga (o el país) aparece en
    # el encabezado/URL de la página cargada.
    blob = (cur_url + ' ' + heading + ' ' + breadcrumb).lower()
    hits = [tok for tok in (league_name, country_name) if tok and tok.lower() in blob]
    ok = bool(hits)
    print('\n' + '=' * 72)
    print(f'  ETAPA 1: {"OK" if ok else "REVISAR"}  (coincidencias: {hits or "ninguna"})')
    print('=' * 72)
    print('[done] driver vivo intacto (sin quit).')


if __name__ == '__main__':
    main()
