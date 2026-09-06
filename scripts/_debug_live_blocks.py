"""
_debug_live_blocks.py — scratchpad (metodología notebook)
=========================================================
Prueba los BLOQUES ya desarrollados de live_function.py contra el driver vivo
de start_driver.py (se conecta con get_driver, NO abre browser ni hace login,
NO cierra nada). Solo funciones de scraping/parseo (no escribe en DB).

Reusa funciones existentes:
  - common_functions.load_json / wait_update_page / dismiss_cookies
  - live_function.give_click_on_live / expand_all_live_leagues / get_live_match
"""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from common_functions import load_json, wait_update_page, dismiss_cookies
from live_function import give_click_on_live, expand_all_live_leagues, get_live_match

SPORT = sys.argv[1] if len(sys.argv) > 1 else 'FOOTBALL'

drv = get_driver()
print('current_url (antes):', drv.current_url)

dict_sports_url = load_json('check_points/sports_url_m2.json')
url = dict_sports_url[SPORT]

print(f'\n[1] wait_update_page -> {url}')
wait_update_page(drv, url, 'container__heading')
dismiss_cookies(drv)
print('    current_url:', drv.current_url)

print(f'\n[2] give_click_on_live({SPORT})')
hay_live = give_click_on_live(drv, SPORT)
print('    hay partidos live?:', hay_live)

if hay_live:
    print('\n[3] expand_all_live_leagues')
    n = expand_all_live_leagues(drv)
    print('    ligas expandidas:', n)

    print('\n[4] get_live_match — 5 campos (status, home, sh, visitante, sv)')
    matches = get_live_match(drv, sport_name=SPORT)
    print(f'    total partidos: {len(matches)}')
    for m in matches:
        print(f'    [{m["status"]}] {m["home"]} {m["home_result"]} - '
              f'{m["visitor_result"]} {m["visitor"]}  '
              f'({m["league_country"]} / {m["league_name"]})')
else:
    print('    (sin partidos live ahora; nada que expandir/leer)')

print('\n[done] driver sigue vivo (no se cerró nada).')
