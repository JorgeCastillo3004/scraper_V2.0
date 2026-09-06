#!/usr/bin/env python3
"""READ-ONLY: ¿qué son los 4 partidos NULL restantes en FlashScore?
Reusa el driver de corrección en PESTAÑA NUEVA. Nunca quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

PAGES = [
    ('WORLD/results',  'https://www.flashscore.com/football/world/world-championship/results/'),
    ('WORLD/fixtures', 'https://www.flashscore.com/football/world/world-championship/fixtures/'),
    ('AFRICA/fixtures','https://www.flashscore.com/football/africa/world-championship/fixtures/'),
]
NEEDLES = ['great britain', 'france', 'senegal', 'lithuania', 'italy']

drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
try:
    for label, url in PAGES:
        drv.get(url); time.sleep(4)
        for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
            try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(1); break
            except Exception: pass
        # heading de la competición
        head = ''
        for sel in ('.heading__name', '.heading__title', 'h2'):
            try: head = drv.find_element(By.CSS_SELECTOR, sel).text; break
            except Exception: pass
        # cargar algunos "show more"
        for _ in range(4):
            try:
                b = drv.find_element(By.CSS_SELECTOR, '.event__more')
                drv.execute_script("arguments[0].click()", b); time.sleep(2)
            except Exception: break
        rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
        print(f"\n===== {label} =====")
        print(f"  heading: {head!r}   filas={len(rows)}")
        found = {}
        for r in rows:
            low = r.text.lower()
            for n in NEEDLES:
                if n in low:
                    found.setdefault(n, []).append(r.text.replace('\n', ' | ')[:80])
        if not found:
            print("  (ninguno de los equipos buscados aparece en esta página)")
        for n, lst in found.items():
            print(f"  '{n}': {len(lst)} -> {lst[:3]}")
finally:
    drv.close()
    drv.switch_to.window(orig)
    print(f"\n[driver] vuelto a: {drv.current_url}")
