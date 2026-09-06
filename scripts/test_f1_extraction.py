"""
scripts/test_f1_extraction.py
──────────────────────────────
Prueba end-to-end de create_events_f1():
1. Login y navega a la página de resultados F1
2. Ejecuta create_events_f1() con season_year='2026'
3. Reporta matches y pilotos procesados

Uso:
    python scripts/test_f1_extraction.py
"""
import sys, os, time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from common_functions import launch_navigator, login, dismiss_cookies
from milestone4 import create_events_f1
from config import FS_EMAIL, FS_PASSWORD

F1_RESULTS_URL = "https://www.flashscore.com/auto-racing/formula-1/results/"

def main():
    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
    try:
        print(f"\n[1] Navegando a: {F1_RESULTS_URL}")
        driver.get("https://www.flashscore.com/")
        time.sleep(3)
        dismiss_cookies(driver)
        driver.get(F1_RESULTS_URL)
        time.sleep(7)
        dismiss_cookies(driver)
        time.sleep(2)

        page_size = len(driver.page_source)
        print(f"[2] Page size: {page_size}")
        if page_size < 20000:
            print("[ERROR] Página de bloqueo recibida. Abortando.")
            return

        print("[3] Ejecutando create_events_f1(category='FORMULA 1', season_year='2026')...")
        create_events_f1(driver, category='FORMULA 1', season_year='2026')
        print("\n[DONE] create_events_f1 completado.")

    except Exception as e:
        import traceback
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
    finally:
        driver.quit()
        print("[INFO] Driver cerrado.")

if __name__ == '__main__':
    main()
