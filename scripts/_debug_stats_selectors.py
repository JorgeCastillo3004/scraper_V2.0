"""
_debug_stats_selectors.py
--------------------------
Inspecciona la pagina de stats de un match para entender por que se
extraen solo 5 categorias cuando FlashScore muestra ~20.

NO mata driver. Solo navega y lee DOM.
"""
import os, sys, json, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Una de las URLs ya procesadas (Brighton~Wolves 2026-05-09)
# Usamos la URL guardada en scan_cache si existe; si no, vamos a la actual.
d = get_driver()
print('current URL:', d.current_url)

base = d.current_url.split('#')[0].split('?')[0]
if '/match/' not in base:
    print('[ABORT] no estamos en una match page')
    sys.exit(1)

stats_url = base + '#/match-summary/match-statistics/0'
print('navigating to:', stats_url)
d.execute_script("window.location.href = arguments[0]", stats_url)
time.sleep(3)

# Esperar wcl-statistics container
try:
    WebDriverWait(d, 10).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '[data-testid="wcl-statistics"]')))
    print('[OK] wcl-statistics presente')
except Exception:
    print('[WARN] wcl-statistics no aparece — quiza usa otra estructura')

# 1) Cuantos elementos de stats hay con el selector ACTUAL
n_wcl = d.execute_script(
    'return document.querySelectorAll(\'[data-testid="wcl-statistics"]\').length;')
print(f"\n[SELECTOR ACTUAL]  document.querySelectorAll('[data-testid=\"wcl-statistics\"]')  → {n_wcl} elementos")

# 2) Buscar otros candidatos
selectors = [
    '[data-testid*="statistics"]',
    '[data-testid="wcl-statistics-category"]',
    '[class*="stat__row"]',
    '[class*="statRow"]',
    '[class*="stat__category"]',
    '[class*="statCategory"]',
    'div._row_ipxal_5',
    'div[class*="row_"]',
    'div[class*="value_"]',
]
print('\n[OTROS SELECTORS] conteos:')
for sel in selectors:
    try:
        n = d.execute_script(f"return document.querySelectorAll(arguments[0]).length;", sel)
        print(f"  {n:4d}  {sel}")
    except Exception as e:
        print(f"  err  {sel}: {e}")

# 3) Print de los primeros 30 elementos con data-testid presente para buscar pattern
print('\n[DATA-TESTID inventario] primeros 50 distintos en la pagina:')
testids = d.execute_script("""
    return Array.from(new Set(
        Array.from(document.querySelectorAll('[data-testid]'))
             .map(e => e.getAttribute('data-testid'))
    )).slice(0, 50);
""")
for t in testids:
    print(f"  {t}")

# 4) Inspeccionar la estructura de UN row para ver categoria+home+away
print('\n[ESTRUCTURA] primer wcl-statistics:')
try:
    html = d.execute_script("""
        const el = document.querySelector('[data-testid=\"wcl-statistics\"]');
        return el ? el.outerHTML : 'null';
    """)
    print(html[:2000])
except Exception as e:
    print('err:', e)

# 5) Probar JS más amplio que el actual
print('\n[EXTRACCION ALTERNATIVA] buscando todos los rows con value home/away:')
alt = d.execute_script("""
    // intentar 2 estrategias
    const rows = [];
    document.querySelectorAll('[data-testid="wcl-statistics"]').forEach(el => {
        rows.push({
            mode: 'wcl-statistics',
            cat: (el.querySelector('[data-testid="wcl-statistics-category"]') || {}).textContent || '',
            home: (el.querySelector('[class*="homeValue"]') || {}).textContent || '',
            away: (el.querySelector('[class*="awayValue"]') || {}).textContent || ''
        });
    });
    // Strategy 2: ver si hay otros containers
    document.querySelectorAll('[class*="_row_"]').forEach(el => {
        const cat = (el.querySelector('[class*="category"]') || {}).textContent || '';
        if (!cat) return;
        const vs = el.querySelectorAll('[class*="value"]');
        rows.push({
            mode: 'class-row',
            cat: cat,
            home: (vs[0] || {}).textContent || '',
            away: (vs[1] || {}).textContent || ''
        });
    });
    return rows;
""")
print(f'total rows encontrados: {len(alt)}')
for r in alt[:30]:
    print(f"  [{r['mode']}] {r['cat']:30s} home={r['home']!r} away={r['away']!r}")
