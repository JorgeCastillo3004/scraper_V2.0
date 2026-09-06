#!/usr/bin/env python3
"""
ETAPA 3 — Click en "Show more matches" hasta la fecha más antigua pendiente.

Encadena Etapa 1 (cargar liga) + Etapa 2 (fecha más antigua en DB) y luego
verifica que `load_until_date`:
  - haga click en "Show more matches" (las filas CRECEN entre estados),
  - se detenga cuando la última fecha visible <= fecha más antigua pendiente.
Finalmente corre `scan_results_page` para confirmar cuántos de los partidos
pendientes quedaron visibles en la página (cobertura).

Reutiliza: detect_null_team_matches / wait_update_page / dismiss_cookies /
get_last_visible_date / load_until_date / scan_results_page (todos ya probados).
Engancha el driver vivo con get_driver() — NUNCA driver.quit().
Solo LECTURA (no escribe en DB).

Uso:
    python scripts/_test_etapa3_mostrar_mas.py --league "FOOTBALL/BRAZIL_Serie A Betano"
"""
import os
import sys
import argparse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By

from common_functions import wait_update_page, dismiss_cookies, load_json
from scripts.fix_live_matches import (
    get_pending_live_matches, load_until_date, scan_results_page,
    get_last_visible_date,
)
from scripts.driver_session import get_driver

LEAGUES_INFO_PATH = 'check_points/leagues_info.json'
XPATH_ROWS = '//div[contains(@class,"leagues--static event--leagues")]/div'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--league', required=True,
                   help='SPORT/COUNTRY_LeagueName, ej. "FOOTBALL/BRAZIL_Serie A Betano"')
    args = p.parse_args()

    sport_key, league_key = args.league.split('/', 1)
    leagues_info = load_json(LEAGUES_INFO_PATH)

    print('=' * 72)
    print(f'ETAPA 3 — "Show more" hasta el más antiguo: {sport_key} / {league_key}')
    print('=' * 72)

    try:
        info = leagues_info[sport_key][league_key]
    except KeyError:
        print(f'[FAIL] {sport_key}/{league_key} no existe en leagues_info.json')
        sys.exit(1)

    league_id   = info['league_id']
    results_url = info.get('results') or info.get('url')
    if not results_url:
        print('[FAIL] la liga no tiene results_url en leagues_info.')
        sys.exit(1)

    # --- Etapa 2: partidos a actualizar (fecha<hoy AND (LIVE OR score=-1)) ---
    matches = [m for m in get_pending_live_matches(verbose=False)
               if m['league_id'] == league_id]
    if not matches:
        print('\n  Sin partidos a actualizar: no hay target. (nada que cargar)')
        sys.exit(0)
    target = min(m['match_date'] for m in matches if m['match_date'])
    print(f'  A actualizar={len(matches)} | fecha más antigua (target)={target}')

    # --- Etapa 1: cargar la liga ---
    driver = get_driver()
    print('\n  Navegando results...')
    wait_update_page(driver, results_url, 'container__heading')
    dismiss_cookies(driver)

    rows_before = len(driver.find_elements(By.XPATH, XPATH_ROWS))
    date_before = get_last_visible_date(driver)
    print(f'  ANTES de "Show more": filas={rows_before} | última fecha visible={date_before}')

    # --- Etapa 3: bucle de "Show more matches" ---
    print('\n  >>> load_until_date (mira los [click N] abajo) <<<')
    load_until_date(driver, target)

    rows_after = len(driver.find_elements(By.XPATH, XPATH_ROWS))
    date_after = get_last_visible_date(driver)
    print(f'\n  DESPUÉS: filas={rows_after} | última fecha visible={date_after}')

    # --- Verificación de cobertura: ¿qué pendientes quedaron en la página? ---
    found = scan_results_page(driver, matches)
    cobertura = len(found)

    # --- Veredicto ---
    crecio        = rows_after > rows_before
    alcanzo_fecha = bool(date_after) and date_after <= target
    print('\n' + '=' * 72)
    print('  VEREDICTO ETAPA 3')
    print(f'    filas crecieron (hubo clicks): {crecio}  ({rows_before} -> {rows_after})')
    print(f'    alcanzó la fecha más antigua : {alcanzo_fecha}  '
          f'(visible {date_after} <= target {target})')
    print(f'    cobertura pendientes en página: {cobertura}/{len(matches)}')
    ok = crecio and alcanzo_fecha
    print(f'    RESULTADO: {"OK" if ok else "REVISAR"}')
    print('=' * 72)
    print('[done] driver vivo intacto (sin quit).')


if __name__ == '__main__':
    main()
