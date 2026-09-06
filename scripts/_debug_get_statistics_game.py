"""
_debug_get_statistics_game.py
------------------------------
Prueba milestone4.get_statistics_game tal-cual sobre el match
actualmente cargado en el driver vivo. Imprime cada paso.

NO toca DB. NO mata driver.
"""
import os, sys, time, ast
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By
from milestone4 import get_statistics_game

d = get_driver()
print('=' * 70)
print('PASO 1 — driver activo')
print('=' * 70)
print('current URL :', d.current_url)
print('title       :', d.title[:90])
print()

# Si no estamos en una match page, abortar
if '/match/' not in d.current_url:
    print('[ABORT] driver no esta en una match page')
    sys.exit(1)

print('=' * 70)
print('PASO 2 — buscar boton "Stats" (lo que hace get_statistics_game)')
print('=' * 70)
btns = d.find_elements(By.XPATH, '//button[contains(.,"Stats")]')
print(f'botones encontrados: {len(btns)}')
for i, b in enumerate(btns):
    try:
        print(f'  [{i}] text={b.text!r} aria={b.get_attribute("aria-label")!r}')
    except Exception as e:
        print(f'  [{i}] err: {e}')
print()

print('=' * 70)
print('PASO 3 — llamar get_statistics_game tal-cual (clica boton + extrae)')
print('=' * 70)
t0 = time.time()
try:
    result_str = get_statistics_game(d)
except Exception as e:
    print(f'[ERROR] get_statistics_game raised: {e}')
    sys.exit(2)
dt = time.time() - t0
print(f'tiempo: {dt:.2f}s')
print()

print('=' * 70)
print('PASO 4 — resultado (str dump del dict que iria a DB)')
print('=' * 70)
print(f'tipo : {type(result_str).__name__}')
print(f'longitud chars: {len(result_str)}')
print()
print('[RAW]', result_str[:500], '...' if len(result_str) > 500 else '')
print()

print('=' * 70)
print('PASO 5 — parsear y mostrar cada campo que iria a DB')
print('=' * 70)
try:
    d_info = ast.literal_eval(result_str)
    print(f'total categorias: {len(d_info)}')
    print()
    for k, v in d_info.items():
        print(f"  {k:32s} home={v.get('home',''):>14s}  away={v.get('away',''):>14s}")
except Exception as e:
    print(f'[ERROR] no se pudo parsear: {e}')
