#!/usr/bin/env python3
"""READ-ONLY: ¿dónde están en FlashScore los 21 partidos Bolivia (Jun 3-15) con -1?
Carga results (varios Show more) + fixtures y busca cada matchup. Pestaña nueva, sin quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

PAGES = [
    ('results',  'https://www.flashscore.com/football/bolivia/division-profesional/results/'),
    ('fixtures', 'https://www.flashscore.com/football/bolivia/division-profesional/fixtures/'),
]
# (home_token, away_token)
PAIRS = [
    ('gv san jose', 'tomayapo'), ('real potosi', 'academia'), ('academia', 'independiente'),
    ('nacional potosi', 'aurora'), ('real oruro', 'universitario'), ('blooming', 'gv san jose'),
    ('real potosi', 'bulo bulo'), ('the strongest', 'oriente'), ('aurora', 'academia'),
    ('nacional potosi', 'tomayapo'), ('gv san jose', 'universitario'), ('guabira', 'real oruro'),
    ('independiente', 'real potosi'), ('nacional potosi', 'real oruro'), ('always ready', 'bulo bulo'),
    ('bolivar', 'real potosi'), ('independiente', 'oriente'), ('aurora', 'oriente'),
    ('blooming', 'the strongest'),
]
drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
hits = {p: [] for p in PAIRS}
try:
    for label, url in PAGES:
        drv.get(url); time.sleep(3.5)
        for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
            try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(0.6); break
            except Exception: pass
        clicks = 0
        for _ in range(10):
            try:
                b = drv.find_element(By.CSS_SELECTOR, '.event__more')
                drv.execute_script("arguments[0].click()", b); time.sleep(1.5); clicks += 1
            except Exception: break
        rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
        txts = [r.text.replace('\n', ' | ') for r in rows]
        dates = [t.split(' | ')[0] for t in txts]
        rng = f"{dates[0] if dates else '?'} .. {dates[-1] if dates else '?'}"
        print(f"\n[{label}] filas={len(rows)} (showmore x{clicks}) rango={rng}")
        for (h, a) in PAIRS:
            for t in txts:
                low = t.lower()
                if h in low and a in low:
                    hits[(h, a)].append(f"{label}: {t[:60]}")
                    break
finally:
    drv.close(); drv.switch_to.window(orig)

print("\n========== ¿dónde aparece cada matchup en FlashScore? ==========")
n_found = 0
for (h, a) in PAIRS:
    locs = hits[(h, a)]
    if locs:
        n_found += 1
        print(f"  ✓ {h}~{a}: {locs}")
    else:
        print(f"  ✗ {h}~{a}: NO aparece")
print(f"\n  encontrados {n_found}/{len(PAIRS)}")
print(f"[driver] vuelto a: {drv.current_url}")
