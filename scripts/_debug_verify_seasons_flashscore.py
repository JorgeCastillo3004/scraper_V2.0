#!/usr/bin/env python3
"""READ-ONLY: por cada liga afectada (partidos pasados con score -1), lee el
NOMBRE DE TEMPORADA que muestra FlashScore (.heading__info, igual que
milestone2.get_league_data) y lo compara con el season_name de la DB.
Reusa el driver vivo en pestaña nueva. Nunca quit()."""
import sys, json, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

data = json.load(open('tmp/_affected_leagues.json'))
# agrupar por results_url -> lista de db_season_name
byurl = {}
for x in data:
    url = x['results_url']
    if not url:
        continue
    byurl.setdefault(url, {'key': x['league_key'], 'sport': x['sport_key'], 'seasons': {}})
    byurl[url]['seasons'][str(x['db_season_name'])] = byurl[url]['seasons'].get(str(x['db_season_name']), 0) + x['n_matches']

drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
results = []
try:
    for url, info in byurl.items():
        fs_season = '??'
        try:
            drv.get(url); time.sleep(3.5)
            for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
                try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(0.6); break
                except Exception: pass
            head = drv.find_element(By.CLASS_NAME, 'container__heading')
            fs_season = head.find_element(By.CLASS_NAME, 'heading__info').text.strip()
        except Exception as e:
            fs_season = f'[ERR {type(e).__name__}]'
        results.append((info['sport'], info['key'], info['seasons'], fs_season))
        seasons_str = ', '.join(f"{k}({v})" for k, v in info['seasons'].items())
        print(f"\n■ {info['sport']}/{info['key']}")
        print(f"   FlashScore temporada actual: {fs_season!r}")
        print(f"   DB season_name de los -1:    {seasons_str}")
        for sname in info['seasons']:
            if sname == 'None':
                verdict = 'SIN season en DB (huérfana)'
            elif fs_season and sname and (sname in fs_season or fs_season in sname):
                verdict = 'COINCIDE → temporada ACTUAL (completable)'
            else:
                verdict = 'DIFIERE → temporada VIEJA (etiquetar) o nueva a crear'
            print(f"      season DB={sname!r} -> {verdict}")
finally:
    drv.close(); drv.switch_to.window(orig)
    print(f"\n[driver] vuelto a: {drv.current_url}")
