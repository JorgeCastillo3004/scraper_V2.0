"""Debug: ¿el driver vivo ve matches en /world/world-cup/results/?"""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By
import time

drv = get_driver()
print(f"[BEFORE] current_url={drv.current_url}")

# Abrir nueva pestaña sin perturbar
orig_handles = drv.window_handles
drv.execute_script("window.open(arguments[0])",
                   "https://www.flashscore.com/football/world/world-cup/results/")
time.sleep(3)
new_handle = [h for h in drv.window_handles if h not in orig_handles][0]
drv.switch_to.window(new_handle)
print(f"[OPEN] current_url={drv.current_url}")
time.sleep(4)  # dejar que cargue

# Heurísticas que usa el scraper
body_text = drv.find_element(By.TAG_NAME, "body").text[:500]
print(f"\n[BODY snippet]\n{body_text}\n")

# Buscar matches
events = drv.find_elements(By.CSS_SELECTOR, "div.event__match")
print(f"\n[MATCH COUNT] div.event__match = {len(events)}")
if events:
    for ev in events[:5]:
        print(f"  - {ev.text[:120].replace(chr(10), ' | ')}")

# "No match found" detection
no_match = drv.find_elements(By.XPATH, "//*[contains(text(),'No match found')]")
print(f"\n[NO MATCH FOUND text present] {len(no_match) > 0}")

# Cerrar pestaña y volver
drv.close()
drv.switch_to.window(orig_handles[0])
print(f"\n[AFTER] current_url={drv.current_url} (back to original)")
