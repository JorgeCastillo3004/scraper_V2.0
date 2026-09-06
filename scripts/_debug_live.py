"""Debug live: prueba las funciones de live_function contra el driver vivo.
Camino de LECTURA (sin escribir en DB): navegar -> click LIVE -> get_live_match.
"""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from driver_session import get_driver
from common_functions import wait_update_page, dismiss_cookies, load_json
from live_function import give_click_on_live, get_live_match, expand_all_live_leagues

SPORT = sys.argv[1] if len(sys.argv) > 1 else 'FOOTBALL'

drv = get_driver()
print('[INFO] current_url:', drv.current_url)

dict_sports_url = load_json('check_points/sports_url_m2.json')
url = dict_sports_url[SPORT]
print(f'[INFO] navegando a {SPORT}: {url}')
wait_update_page(drv, url, 'container__heading')
dismiss_cookies(drv)

print('[INFO] click en LIVE...')
found = give_click_on_live(drv, SPORT)
print('[INFO] give_click_on_live ->', found)

if found:
    n = expand_all_live_leagues(drv)
    print('[INFO] expand_all_live_leagues ->', n, 'ligas expandidas')
    matches = get_live_match(drv, sport_name=SPORT)
    print(f'[INFO] get_live_match -> {len(matches)} partidos')
    for m in matches:
        print(f'  [{m["status"]}] {m["home"]} {m["home_result"]} - '
              f'{m["visitor_result"]} {m["visitor"]}  '
              f'({m.get("league_country","?")} / {m.get("league_name","?")})')
else:
    print('[INFO] no hay sección live activa (o no hay partidos en vivo).')

print('[DONE] (driver sigue vivo, no se cierra)')
