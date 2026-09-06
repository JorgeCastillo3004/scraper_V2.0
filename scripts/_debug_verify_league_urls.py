#!/usr/bin/env python3
"""_debug_verify_league_urls — VERIFICA que las URLs de leagues_info.json
coincidan con las que FlashScore lista en vivo ("my-leagues-list").

SOLO LECTURA: reusa el driver vivo con get_driver() (NUNCA .quit()), navega a
la página de cada deporte, extrae las ligas con `find_ligues_torneos` (la misma
función que usa create_leagues para enumerar) y compara contra el `url` guardado
en leagues_info.json. NO escribe en DB ni sobreescribe ningún JSON.

Uso:
    env_sports/bin/python scripts/_debug_verify_league_urls.py            # todos los deportes con ligas
    env_sports/bin/python scripts/_debug_verify_league_urls.py FOOTBALL   # solo uno
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from common_functions import load_json, wait_update_page
from milestone2 import find_ligues_torneos

LEAGUES_INFO = 'check_points/leagues_info.json'
SPORTS_URL   = 'check_points/sports_url_m2.json'


def _norm(url):
    # Comparar por path canónico: sin querystring, sin barra final, en minúsculas.
    if not url:
        return ''
    return url.split('?')[0].rstrip('/').lower()


def verify_sport(driver, sport, sport_url, json_leagues):
    print('\n' + '=' * 78)
    print('  %s  (%d ligas en JSON)  ->  %s' % (sport, len(json_leagues), sport_url))
    print('=' * 78)

    # mapa normalizado de URLs en el JSON: url_norm -> league_key
    json_by_url = {}
    for key, entry in json_leagues.items():
        json_by_url[_norm(entry.get('url'))] = key

    # extracción en vivo (zoom 50% como create_leagues, para que cargue el sidebar)
    driver.execute_script("document.body.style.zoom='50%'")
    wait_update_page(driver, sport_url, 'container__heading')
    live = find_ligues_torneos(driver)            # {KEY_slug: url}
    live_by_url = {_norm(u): k for k, u in live.items()}
    print('  En vivo (my-leagues-list): %d ligas' % len(live))

    matched   = [u for u in json_by_url if u in live_by_url]
    only_json = [u for u in json_by_url if u not in live_by_url]   # en JSON, NO en vivo (stale/mal/despineada)
    only_live = [u for u in live_by_url if u not in json_by_url]   # pineada en vivo, NO en JSON

    print('\n  ✅ COINCIDEN (%d):' % len(matched))
    for u in sorted(matched):
        print('      %s' % u)

    if only_json:
        print('\n  ⚠️  EN JSON pero NO en FlashScore (URL mal / liga despineada) (%d):' % len(only_json))
        for u in sorted(only_json):
            print('      [%s] %s' % (json_by_url[u], u or '(sin url)'))

    if only_live:
        print('\n  ➕ EN FlashScore pero NO en JSON (pineada, sin scrapear) (%d):' % len(only_live))
        for u in sorted(only_live):
            print('      %s' % u)

    return {'sport': sport, 'json': len(json_leagues), 'live': len(live),
            'match': len(matched), 'only_json': len(only_json), 'only_live': len(only_live)}


def main():
    leagues_info = load_json(LEAGUES_INFO)
    sports_url   = load_json(SPORTS_URL)

    # deportes con ligas reales en el JSON
    sports_con_ligas = [s for s, l in leagues_info.items() if isinstance(l, dict) and l]
    pedido = sys.argv[1].upper() if len(sys.argv) > 1 else None
    if pedido:
        sports_con_ligas = [s for s in sports_con_ligas if s == pedido]
        if not sports_con_ligas:
            print('No hay ligas en JSON para "%s". Disponibles: %s'
                  % (pedido, ', '.join(s for s, l in leagues_info.items() if isinstance(l, dict) and l)))
            return

    driver = get_driver()
    print('[OK] driver vivo:', driver.current_url)

    resumen = []
    for sport in sports_con_ligas:
        url = sports_url.get(sport)
        if not url:
            print('\n  [SKIP] %s: sin URL en sports_url_m2.json' % sport)
            continue
        try:
            resumen.append(verify_sport(driver, sport, url, leagues_info[sport]))
        except Exception as e:
            print('  [ERROR] %s: %s' % (sport, e))

    print('\n' + '#' * 78)
    print('  RESUMEN')
    print('#' * 78)
    print('  %-14s %6s %6s %7s %10s %10s' % ('DEPORTE', 'JSON', 'VIVO', 'MATCH', 'SOLO_JSON', 'SOLO_VIVO'))
    for r in resumen:
        print('  %-14s %6d %6d %7d %10d %10d'
              % (r['sport'], r['json'], r['live'], r['match'], r['only_json'], r['only_live']))
    print('\n[done] driver vivo intacto (sin quit).')


if __name__ == '__main__':
    main()
