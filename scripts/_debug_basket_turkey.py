import os, sys, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'scripts')); sys.path.insert(0, os.path.join(ROOT,'src'))
from driver_session import get_driver
from selenium.webdriver.common.by import By

drv = get_driver()                      # adjunta al driver de CORRECCIÓN (no abre nuevo)
orig = drv.current_window_handle
print("driver actual:", drv.current_url)

def scan(url, label):
    drv.execute_script("window.open(arguments[0])", url)
    drv.switch_to.window(drv.window_handles[-1])
    time.sleep(5)
    print(f"\n===== {label} -> {drv.current_url} =====")
    # cerrar cookies si aparece
    try:
        drv.find_element(By.ID, 'onetrust-accept-btn-handler').click(); time.sleep(1)
    except Exception: pass
    rows = drv.find_elements(By.CSS_SELECTOR, 'div.event__match')
    print(f"  filas event__match: {len(rows)}")
    found = 0
    for r in rows[:40]:
        try:
            home = r.find_element(By.CSS_SELECTOR, '[class*="event__homeParticipant"]').text
            away = r.find_element(By.CSS_SELECTOR, '[class*="event__awayParticipant"]').text
        except Exception:
            home = away = '?'
        try: stage = r.find_element(By.CSS_SELECTOR, 'div.event__stage').text
        except Exception:
            try: stage = r.find_element(By.CSS_SELECTOR, 'div.event__time').text
            except Exception: stage = '-'
        try:
            hs = r.find_element(By.CSS_SELECTOR, '[class*="event__score--home"]').text
            as_ = r.find_element(By.CSS_SELECTOR, '[class*="event__score--away"]').text
            score = f"{hs}-{as_}"
        except Exception: score = ''
        if 'fenerbah' in (home+away).lower() or 'ikta' in (home+away).lower():
            print(f"  >>> {home} {score} {away}  [{stage}]")
            found += 1
    if not found:
        print("  (ningún Fenerbahce/Besiktas en esta página)")
    drv.close()
    drv.switch_to.window(orig)

scan("https://www.flashscore.com/basketball/turkey/super-lig/", "BASKET TURKEY Super Lig (vista liga)")
scan("https://www.flashscore.com/basketball/", "BASKET portada (live del momento)")
print("\nvuelto a pestaña original:", drv.current_url)
