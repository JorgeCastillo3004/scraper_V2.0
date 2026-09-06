#!/usr/bin/env python3
"""READ-ONLY: ¿los partidos SCHEDULED con score -1 de Serie A Betano (Brasil)
existen en FlashScore con score real? Reusa driver en pestaña nueva. Nunca quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

URL = 'https://www.flashscore.com/football/brazil/serie-a-betano/results/'
WANT = ['botafogo', 'santos', 'gremio', 'juventude', 'fluminense', 'ceara',
        'flamengo', 'palmeiras', 'atletico', 'bahia']

drv = get_driver()
orig = drv.current_window_handle
drv.execute_script("window.open('about:blank')")
drv.switch_to.window(drv.window_handles[-1])
try:
    drv.get(URL); time.sleep(4)
    for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
        try: drv.find_element(By.CSS_SELECTOR, sel).click(); time.sleep(1); break
        except Exception: pass
    head = ''
    for sel in ('.heading__name', '.heading__title', 'h2'):
        try: head = drv.find_element(By.CSS_SELECTOR, sel).text; break
        except Exception: pass
    for _ in range(6):
        try:
            b = drv.find_element(By.CSS_SELECTOR, '.event__more')
            drv.execute_script("arguments[0].click()", b); time.sleep(2)
        except Exception: break
    rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
    print(f"heading={head!r}  filas={len(rows)}")
    print("\n=== partidos Oct-Nov 2025 con score en FlashScore (muestra) ===")
    shown = 0
    for r in rows:
        t = r.text.replace('\n', ' | ')
        low = t.lower()
        if ('10.' in t or '11.' in t or '.10.' in t or '.11.' in t) and any(w in low for w in WANT):
            print("   ", t[:90])
            shown += 1
        if shown >= 12: break
    print(f"\n(la página de results muestra el score final si el partido se jugó)")
finally:
    drv.close(); drv.switch_to.window(orig)
    print(f"\n[driver] vuelto a: {drv.current_url}")
