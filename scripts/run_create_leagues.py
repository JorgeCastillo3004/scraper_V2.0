"""
run_create_leagues.py
---------------------
Ejecuta milestone2.create_leagues() para BOXING, GOLF y MOTOR SPORT
usando un driver nuevo (no interfiere con extracciones en curso).

Uso:
    source /home/you/env/sports_env/bin/activate
    cd /home/you/work_2026/scraper_V2.0
    python scripts/run_create_leagues.py [BOXING] [GOLF] [MOTOR SPORT]

    Sin argumentos ejecuta los 3 deportes en orden.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config import FS_EMAIL, FS_PASSWORD
from common_functions import launch_navigator, login
from milestone2 import create_leagues

SPORTS_DEFAULT = ['BOXING', 'GOLF', 'MOTOR SPORT']

def main():
    sports = sys.argv[1:] if len(sys.argv) > 1 else SPORTS_DEFAULT
    print(f"Deportes a procesar: {sports}")

    driver = launch_navigator('https://www.flashscore.com', headless=True)
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)

    try:
        create_leagues(driver, sports)
        print("\n[DONE] create_leagues completado.")
    except Exception as e:
        print(f"\n[ERROR] create_leagues falló: {type(e).__name__}: {e}")
        raise
    finally:
        driver.quit()
        print("[INFO] Driver cerrado.")

if __name__ == '__main__':
    main()
