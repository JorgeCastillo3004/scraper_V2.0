"""¿En qué URL lista FlashScore los partidos que FOOTBALL/WORLD_World Cup no
encuentra? Reusa el DRIVER VIVO y las MISMAS funciones que el completado real
(wait_update_page + load_until_date + scan_results_page), no selectores propios.
Solo lectura: no escribe en DB ni en los JSON.

  sports_env/bin/python scripts/_debug_worldcup_url.py
"""
import sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

from driver_session import get_driver
from common_functions import wait_update_page, dismiss_cookies
from scripts.fix_live_matches import (get_pending_live_matches, load_until_date,
                                      scan_results_page)

d = get_driver()
pend = [m for m in get_pending_live_matches(verbose=False)
        if m['league_name'] == 'World Cup' and m['sport_name'] == 'Football']
print(f'Pendientes de FOOTBALL/WORLD_World Cup: {len(pend)}')
oldest = min(m['match_date'] for m in pend)

CANDIDATAS = [
    ('WORLD  (la de hoy)', 'https://www.flashscore.com/football/world/world-championship/results/'),
    ('AFRICA',             'https://www.flashscore.com/football/africa/world-championship/results/'),
    ('ASIA',               'https://www.flashscore.com/football/asia/world-championship/results/'),
    ('EUROPE',             'https://www.flashscore.com/football/europe/world-championship/results/'),
    ('N&C AMERICA',        'https://www.flashscore.com/football/north-central-america/world-championship/results/'),
    ('SOUTH AMERICA',      'https://www.flashscore.com/football/south-america/world-championship/results/'),
]
falta = list(pend)
for etiqueta, url in CANDIDATAS:
    if not falta:
        break
    print('\n' + '=' * 70)
    print(f'{etiqueta}  ({len(falta)} por ubicar)')
    try:
        try:
            wait_update_page(d, url, 'container__heading')
        except Exception:
            d.get(url); time.sleep(4)
        dismiss_cookies(d)
        load_until_date(d, oldest, target_matches=falta)
        found = scan_results_page(d, falta)
        print(f'  → encuentra {len(found)} de {len(falta)}')
        for m in falta:
            if m['match_id'] in found:
                print(f'     ✓ {m["name"]}')
        falta = [m for m in falta if m['match_id'] not in found]
    except Exception as e:
        print(f'  ERROR {type(e).__name__}: {str(e)[:110]}')

print('\n' + '=' * 70)
print(f'SIN UBICAR EN NINGUNA URL: {len(falta)}')
for m in falta:
    print(f'   ✗ {m["match_date"]} | {m["name"]}')
print('\n[fin] driver vivo intacto')
