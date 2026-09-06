#!/usr/bin/env python3
"""READ-ONLY: verifica en FlashScore cuántos Calgary Stampeders vs Saskatchewan
Roughriders hay el 2026-05-18 (caso 'mismo nombre+fecha, hora distinta').
Reusa el driver de corrección VIVO en una PESTAÑA NUEVA. NUNCA quit()."""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts'); sys.path.insert(0, 'src')
from driver_session import get_driver
from selenium.webdriver.common.by import By

URL = 'https://www.flashscore.com/american-football/canada/cfl/results/'
drv = get_driver()
orig = drv.current_window_handle
orig_url = drv.current_url
print(f"[driver] reusado. pestaña original: {orig_url}")

drv.execute_script("window.open(arguments[0])", URL)
drv.switch_to.window(drv.window_handles[-1])
try:
    time.sleep(4)
    # cookies
    for sel in ('#onetrust-accept-btn-handler', '.onetrust-close-btn-handler'):
        try:
            e = drv.find_element(By.CSS_SELECTOR, sel); e.click(); time.sleep(1); break
        except Exception:
            pass
    # click "Show more matches" varias veces para cubrir hasta mayo
    for _ in range(8):
        try:
            btn = drv.find_element(By.CSS_SELECTOR, '.event__more')
            drv.execute_script("arguments[0].click()", btn); time.sleep(2)
        except Exception:
            break

    rows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
    print(f"[results] filas de partido cargadas: {len(rows)}")
    hits = []
    cur_date = None
    for r in rows:
        txt = r.text.replace('\n', ' | ')
        low = txt.lower()
        if 'calgary' in low and 'saskatchewan' in low:
            hits.append(txt)
    print(f"\n=== Calgary vs Saskatchewan encontrados en results: {len(hits)} ===")
    for h in hits:
        print("   ", h)

    # también probar fixtures por si sigue como programado
    drv.get('https://www.flashscore.com/american-football/canada/cfl/fixtures/')
    time.sleep(3)
    frows = drv.find_elements(By.CSS_SELECTOR, '.event__match')
    fhits = [r.text.replace('\n',' | ') for r in frows
             if 'calgary' in r.text.lower() and 'saskatchewan' in r.text.lower()]
    print(f"\n=== Calgary vs Saskatchewan en fixtures: {len(fhits)} ===")
    for h in fhits:
        print("   ", h)
finally:
    drv.close()  # cierra SOLO la pestaña nueva
    drv.switch_to.window(orig)
    print(f"\n[driver] pestaña nueva cerrada, vuelto a: {drv.current_url}")
