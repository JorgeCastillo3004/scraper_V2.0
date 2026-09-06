"""
_debug_repro_get_stats.py
--------------------------
Reproduce exactamente el flujo que usa fix_null_team_ids:
1) wait_update_page(driver, match_url, 'duelParticipant')
2) dismiss_cookies
3) get_statistics_game(driver)

Para entender por que en este flujo se extraen solo 5 cats.
"""
import os, sys, time, ast
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from common_functions import wait_update_page, dismiss_cookies
from milestone4 import get_statistics_game

MATCH_URL = "https://www.flashscore.com/match/bHZgKFgA/#/match-summary/match-summary"

d = get_driver()
print('PASO 1 — current URL antes:', d.current_url)
print()

print('PASO 2 — wait_update_page(match_url, duelParticipant)...')
wait_update_page(d, MATCH_URL, 'duelParticipant')
dismiss_cookies(d)
print('  URL despues:', d.current_url)
print()

print('PASO 3 — primer get_statistics_game (inmediato):')
t0 = time.time()
s1 = get_statistics_game(d)
dt1 = time.time() - t0
info1 = ast.literal_eval(s1) if s1 and s1 != '{}' else {}
print(f'  tiempo: {dt1:.2f}s  → {len(info1)} cats')
print()

print('PASO 4 — sleep 3s + segundo get_statistics_game (post render):')
time.sleep(3)
t0 = time.time()
s2 = get_statistics_game(d)
dt2 = time.time() - t0
info2 = ast.literal_eval(s2) if s2 and s2 != '{}' else {}
print(f'  tiempo: {dt2:.2f}s  → {len(info2)} cats')
print()

print('PASO 5 — conteo wcl-statistics ahora en DOM:')
n = d.execute_script('return document.querySelectorAll(\'[data-testid="wcl-statistics"]\').length;')
print(f'  {n} elementos')
print()

print('PASO 6 — categorias 2da llamada:')
for k, v in info2.items():
    print(f'  {k:32s} home={v.get("home",""):>14s}  away={v.get("away",""):>14s}')
