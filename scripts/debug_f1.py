"""
scripts/debug_f1.py
───────────────────
Navega a la página de resultados F1 de FlashScore y vuelca las
clases/atributos relevantes para validar los selectores de
create_events_f1() y build_match_dict().

Uso:
    python scripts/debug_f1.py
"""
import sys, os, re, time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common_functions import launch_navigator, dismiss_cookies, login
from config import FS_EMAIL, FS_PASSWORD

F1_RESULTS_URL = "https://www.flashscore.com/auto-racing/formula-1/results/"
F1_CALENDAR_URL = "https://www.flashscore.com/motorsport/calendar/f1/"

SEP = "=" * 70

def dump_block(label, el):
    print(f"\n--- {label} ---")
    print(f"  tag: {el.tag_name}")
    print(f"  class: {el.get_attribute('class')}")
    txt = el.text.strip()
    if txt:
        print(f"  text: {txt[:120]}")

def main():
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
    try:
        # Navegar primero a home para establecer sesión
        print(f"\n[1] Navegando a home para sesión...")
        driver.get("https://www.flashscore.com/")
        time.sleep(4)
        dismiss_cookies(driver)
        time.sleep(2)

        print(f"[2] Navegando a F1 results: {F1_RESULTS_URL}")
        driver.get(F1_RESULTS_URL)
        time.sleep(8)
        page_size = len(driver.page_source)
        print(f"  page size: {page_size}")
        if page_size < 20000:
            print(f"  [WARN] Página muy pequeña, probando calendar URL...")
            driver.get(F1_CALENDAR_URL)
            time.sleep(8)
            page_size = len(driver.page_source)
            print(f"  calendar page size: {page_size}")
        dismiss_cookies(driver)
        time.sleep(2)
        print(f"  URL actual: {driver.current_url}")

        # ── Selector principal de bloques F1 ──────────────────────────
        print(f"\n{SEP}")
        print("BLOQUES sportName--noDuel.motorsport-auto-racing:")
        blocks = driver.find_elements(By.CLASS_NAME, "sportName--noDuel.motorsport-auto-racing")
        print(f"  Encontrados: {len(blocks)}")

        if not blocks:
            # Intentar variante sin el segundo selector
            print("  [WARN] No encontrados. Intentando sólo 'sportName--noDuel'...")
            blocks = driver.find_elements(By.CLASS_NAME, "sportName--noDuel")
            print(f"  sportName--noDuel encontrados: {len(blocks)}")
            # Volcar clases de los primeros bloques para diagnóstico
            all_blocks = driver.find_elements(By.XPATH, '//*[contains(@class,"sportName")]')
            print(f"  Elementos con 'sportName' en clase: {len(all_blocks)}")
            for b in all_blocks[:5]:
                print(f"    class='{b.get_attribute('class')}' text='{b.text[:60]}'")

        if not blocks:
            print("  [ERROR] Sin bloques de carrera. Guardando HTML para inspección.")
            with open(os.path.join(_ROOT, 'scripts', 'debug_f1.html'), 'w') as f:
                f.write(driver.page_source)
            return

        # ── Primer bloque: inspección interna ────────────────────────
        b0 = blocks[0]
        print(f"\n{SEP}")
        print(f"PRIMER BLOQUE — clase: '{b0.get_attribute('class')}'")
        print(f"  text[:100]: '{b0.text[:100]}'")

        # event__titleBox
        print(f"\n{SEP}")
        print("SELECTOR event__titleBox:")
        titles = b0.find_elements(By.CLASS_NAME, 'event__titleBox')
        if titles:
            for t in titles[:3]:
                print(f"  OK → '{t.text[:80]}'")
        else:
            print("  [FAIL] No encontrado")
            alt = b0.find_elements(By.XPATH, './/*[contains(@class,"titleBox") or contains(@class,"title")]')
            for a in alt[:5]:
                print(f"  ALT class='{a.get_attribute('class')}' text='{a.text[:60]}'")

        # event__header--info
        print(f"\n{SEP}")
        print("SELECTOR event__header.event__header--info:")
        headers = b0.find_elements(By.CLASS_NAME, 'event__header')
        for h in headers[:3]:
            print(f"  class='{h.get_attribute('class')}' text='{h.text[:80]}'")
        infos = b0.find_elements(By.CSS_SELECTOR, '.event__header--info')
        if infos:
            print(f"  event__header--info encontrados: {len(infos)}")
            for i in infos[:2]:
                print(f"    text='{i.text[:80]}'")
        else:
            print("  [FAIL] event__header--info no encontrado")

        # wcl-simpleText1 (data-testid)
        print(f"\n{SEP}")
        print("SELECTOR span[@data-testid='wcl-simpleText1']:")
        spans = b0.find_elements(By.XPATH, './/span[@data-testid="wcl-simpleText1"]')
        if spans:
            for s in spans[:3]:
                print(f"  OK → '{s.text}'")
        else:
            print("  [FAIL] No encontrado. Buscando alternativas data-testid...")
            all_testid = b0.find_elements(By.XPATH, './/*[@data-testid]')
            for el in all_testid[:10]:
                print(f"    data-testid='{el.get_attribute('data-testid')}' tag={el.tag_name} text='{el.text[:50]}'")

        # event__match--noDuel (racer rows)
        print(f"\n{SEP}")
        print("SELECTOR div[@title='Click for details!']:")
        racers = b0.find_elements(By.XPATH, './div[@title="Click for details!"]')
        print(f"  Encontrados: {len(racers)}")
        if not racers:
            print("  [FAIL] Buscando alternativas...")
            alts = b0.find_elements(By.XPATH, './/*[@title]')
            for a in alts[:5]:
                print(f"    title='{a.get_attribute('title')}' class='{a.get_attribute('class')}'")

        # ── Buscar Race blocks ────────────────────────────────────────
        print(f"\n{SEP}")
        print(f"BLOQUES con 'Race' en título ({len(blocks)} total):")
        race_count = 0
        for b in blocks:
            try:
                title = b.find_element(By.CLASS_NAME, 'event__titleBox').text
                if 'Race' in title:
                    race_count += 1
                    if race_count <= 3:
                        print(f"  [Race] '{title}'")
            except Exception:
                pass
        print(f"  Total Race blocks: {race_count}")

        # ── Guardar HTML ──────────────────────────────────────────────
        out_path = os.path.join(_ROOT, 'scripts', 'debug_f1.html')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"\n[INFO] HTML guardado en: {out_path}")

    finally:
        driver.quit()

if __name__ == '__main__':
    main()
