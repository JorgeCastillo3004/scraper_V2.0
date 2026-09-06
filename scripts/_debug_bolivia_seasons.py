#!/usr/bin/env python3
"""READ-ONLY: ¿dónde viven en FlashScore los 21 partidos Jun-2026 de Bolivia
Division Profesional? URL actual vs posibles archivos. Pestaña nueva, sin quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

URLS = [
    ('actual',  'https://www.flashscore.com/football/bolivia/division-profesional/results/'),
    ('2026',    'https://www.flashscore.com/football/bolivia/division-profesional-2026/results/'),
]
# muestras de los 21 (home~away)
SAMPLES = [('gv san jose', 'tomayapo'), ('real potosi', 'academia'),
           ('blooming', 'the strongest'), ('bolivar', 'real potosi'),
           ('always ready', 'bulo bulo')]

drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
try:
    for label, url in URLS:
        drv.get(url); time.sleep(4)
        for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
            try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(1); break
            except Exception: pass
        head = ''
        for sel in ('.heading__name', '.heading__title'):
            try: head = drv.find_element(By.CSS_SELECTOR, sel).text; break
            except Exception: pass
        # ¿es 404 / sin datos?
        body = drv.find_element(By.TAG_NAME, 'body').text[:120].replace('\n',' ')
        for _ in range(5):
            try:
                b = drv.find_element(By.CSS_SELECTOR, '.event__more')
                drv.execute_script("arguments[0].click()", b); time.sleep(2)
            except Exception: break
        rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
        first_dates = [r.text.split('\n')[0] for r in rows[:4]]
        print(f"\n=== {label}: {url}")
        print(f"   heading={head!r}  filas={len(rows)}  primeras_fechas={first_dates}")
        if len(rows) == 0:
            print(f"   body: {body!r}")
        for h, a in SAMPLES:
            hit = [r.text.replace('\n',' | ')[:70] for r in rows
                   if h in r.text.lower() and a in r.text.lower()]
            if hit:
                print(f"   ✓ {h}~{a}: {hit[0]}")
finally:
    drv.close(); drv.switch_to.window(orig)
    print(f"\n[driver] vuelto a: {drv.current_url}")
