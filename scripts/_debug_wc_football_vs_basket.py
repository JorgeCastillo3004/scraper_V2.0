#!/usr/bin/env python3
"""READ-ONLY: compara los matchups sospechosos (WORLD WC football con -1) contra
FlashScore en el link de FUTBOL y el de BASQUET. Confirma si son básquet.
Reusa driver en pestaña nueva. Nunca quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

PAGES = [
    ('FUTBOL/results',  'https://www.flashscore.com/football/world/world-championship/results/'),
    ('FUTBOL/fixtures', 'https://www.flashscore.com/football/world/world-championship/fixtures/'),
    ('BASKET/results',  'https://www.flashscore.com/basketball/world/world-cup/results/'),
    ('BASKET/fixtures', 'https://www.flashscore.com/basketball/world/world-cup/fixtures/'),
]
# (home_token, away_token) — muestra: 3 con-gemelo basket + varios sin-gemelo
SAMPLE = [
    ('austria', 'netherlands'), ('spain', 'ukraine'), ('belgium', 'finland'),   # 30 (gemelo basket)
    ('argentina', 'panama'), ('japan', 'south korea'), ('egypt', 'angola'),       # 34
    ('guam', 'australia'), ('senegal', 'ivory coast'), ('usa', 'mexico'),         # 34
    ('qatar', 'saudi arabia'), ('iran', 'syria'), ('lebanon', 'india'),           # 34
]
found = {s: {} for s in SAMPLE}

drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
try:
    for label, url in PAGES:
        drv.get(url); time.sleep(3.5)
        for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
            try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(0.6); break
            except Exception: pass
        for _ in range(6):
            try:
                b = drv.find_element(By.CSS_SELECTOR, '.event__more')
                drv.execute_script("arguments[0].click()", b); time.sleep(1.5)
            except Exception: break
        rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
        txts = [r.text.replace('\n', ' | ') for r in rows]
        print(f"\n[{label}] filas={len(rows)}")
        for (h, a) in SAMPLE:
            for t in txts:
                low = t.lower()
                if h in low and a in low:
                    found[(h, a)][label] = t[:75]
                    break
finally:
    drv.close(); drv.switch_to.window(orig)

print("\n========== RESUMEN: dónde aparece cada matchup ==========")
for (h, a) in SAMPLE:
    locs = found[(h, a)]
    if not locs:
        print(f"  {h}~{a}: NO aparece en NINGÚN link")
    else:
        for lab, t in locs.items():
            print(f"  {h}~{a}: [{lab}] {t}")
print(f"\n[driver] vuelto a: {drv.current_url}")
