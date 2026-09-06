#!/usr/bin/env python3
"""READ-ONLY: ¿los partidos Oct-Nov 2025 están en el ARCHIVO de temporada 2025?
Prueba serie-a-betano-2025. Reusa driver en pestaña nueva. Nunca quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

URLS = [
    ('actual',  'https://www.flashscore.com/football/brazil/serie-a-betano/results/'),
    ('2025',    'https://www.flashscore.com/football/brazil/serie-a-betano-2025/results/'),
]
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
        rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
        # fechas visibles sin cargar más
        dates = []
        for r in rows[:6]:
            t = r.text.split('\n')[0]
            dates.append(t)
        # buscar Botafogo~Santos explícitamente
        hit = [r.text.replace('\n',' | ')[:70] for r in rows
               if 'botafogo' in r.text.lower() and 'santos' in r.text.lower()]
        print(f"\n=== {label}: {url}")
        print(f"   heading={head!r}  filas={len(rows)}")
        print(f"   primeras fechas: {dates}")
        print(f"   Botafogo~Santos en esta página: {hit}")
finally:
    drv.close(); drv.switch_to.window(orig)
    print(f"\n[driver] vuelto a: {drv.current_url}")
