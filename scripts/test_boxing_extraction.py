"""
scripts/test_boxing_extraction.py
───────────────────────────────────
Prueba end-to-end de extract_info_boxing() para la primera liga activa.
Navega a results, inspecciona selectores paso a paso y ejecuta la extracción.

Uso:
    python scripts/test_boxing_extraction.py
"""
import sys, os, time, json, re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common_functions import launch_navigator, login, dismiss_cookies
from config import FS_EMAIL, FS_PASSWORD

SEP = "=" * 70

def get_first_active_boxing_league():
    with open('check_points/leagues_info.json') as f:
        data = json.load(f)
    for name, info in data.get('BOXING', {}).items():
        if 'results' in info and info.get('league_id'):
            return name, info
    return None, None

def main():
    league_name, league_info = get_first_active_boxing_league()
    if not league_name:
        print("[ERROR] No hay ligas Boxing activas con league_id.")
        return

    results_url = league_info['results']
    print(f"\nLiga: {league_name}")
    print(f"URL: {results_url}")
    print(f"league_id: {league_info.get('league_id')}")

    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)

    try:
        driver.get("https://www.flashscore.com/")
        time.sleep(3)
        dismiss_cookies(driver)

        print(f"\n[1] Navegando a results: {results_url}")
        driver.get(results_url)
        time.sleep(5)
        dismiss_cookies(driver)

        page_size = len(driver.page_source)
        print(f"  page size: {page_size}")
        if page_size < 20000:
            print("[ERROR] Página bloqueada.")
            return

        # ── Selector de match rows ────────────────────────────────────
        print(f"\n{SEP}")
        print("SELECTOR match rows (data-event-row='true'):")
        matches = driver.find_elements(By.XPATH, '//div[contains(@class,"event__match") and @data-event-row="true"]')
        print(f"  Encontrados: {len(matches)}")
        if not matches:
            print("  [FAIL] No se encontraron matches")
            with open('scripts/debug_boxing_results.html', 'w') as f:
                f.write(driver.page_source)
            print("  HTML guardado en debug_boxing_results.html")
            return

        # Obtener link del primer match
        html_block = matches[0].get_attribute('outerHTML')
        link_ids = re.findall(r'id="[a-z]_\d+_(.+?)"', html_block)
        if not link_ids:
            print("  [FAIL] No se pudo extraer el link del match")
            return
        match_url = f"https://www.flashscore.com/match/{link_ids[0]}/#/match-summary/match-summary"
        print(f"  Primer match URL: {match_url}")

        # ── Navegar al detalle del match ──────────────────────────────
        print(f"\n{SEP}")
        print(f"[2] Navegando al detalle del match...")
        driver.get(match_url)
        time.sleep(5)
        dismiss_cookies(driver)

        page_size2 = len(driver.page_source)
        print(f"  page size: {page_size2}")

        # matchInfoData selector (wait_load_details)
        print(f"\n{SEP}")
        print("SELECTOR matchInfoData (wait_load_details):")
        info_blocks = driver.find_elements(By.XPATH, '//div[@class="matchInfoData"]')
        if info_blocks:
            print(f"  OK → {len(info_blocks)} encontrados")
        else:
            print("  [FAIL] matchInfoData no encontrado — buscando alternativas...")
            alts = driver.find_elements(By.XPATH, '//*[contains(@class,"matchInfo") or contains(@class,"duelParticipant")]')
            for a in alts[:5]:
                print(f"    class='{a.get_attribute('class')}' text='{a.text[:60]}'")

        # duelParticipant selectors
        print(f"\n{SEP}")
        print("SELECTORES duelParticipant:")
        for cls in ['duelParticipant', 'duelParticipant__home', 'duelParticipant__away',
                    'duelParticipant__startTime', 'duelParticipant__home duelParticipant--winner']:
            els = driver.find_elements(By.CLASS_NAME, cls)
            status = f"OK ({len(els)})" if els else "FAIL"
            text = els[0].text[:60] if els else ''
            print(f"  {cls}: {status}  text='{text}'")

        # participant__participantLink
        print(f"\n{SEP}")
        print("SELECTOR participant__participantLink:")
        links = driver.find_elements(By.XPATH, '//a[@class="participant__participantLink"]')
        if links:
            for lnk in links[:4]:
                print(f"  OK → {lnk.get_attribute('href')}")
        else:
            print("  [FAIL] No encontrado — buscando alternativas...")
            alts = driver.find_elements(By.XPATH, '//div[@class="duelParticipant"]//a')
            for a in alts[:6]:
                print(f"    class='{a.get_attribute('class')}' href='{a.get_attribute('href')}'")

        # Guardar HTML del detalle
        with open('scripts/debug_boxing_match.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"\n[INFO] HTML del match guardado en debug_boxing_match.html")

        # ── Ejecutar extracción completa ──────────────────────────────
        print(f"\n{SEP}")
        print("[3] Ejecutando extract_info_boxing()...")
        from milestone4 import extract_info_boxing
        # Completar league_info con campos necesarios
        league_info['sport_name'] = 'BOXING'
        from data_base import get_dict_sport_id
        league_info['sport_id'] = get_dict_sport_id().get('Boxing') or get_dict_sport_id().get('BOXING')
        league_info['season_id'] = league_info.get('season_id', '')
        league_info['country_id'] = league_info.get('country_id', '')

        extract_info_boxing(driver, league_info)
        print("\n[DONE] extract_info_boxing completado.")

    except Exception as e:
        import traceback
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        driver.quit()
        print("[INFO] Driver cerrado.")

if __name__ == '__main__':
    main()
