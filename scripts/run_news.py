"""
scripts/run_news.py
───────────────────
Runner de extracción de noticias para el dashboard.
Crea un driver sin login y ejecuta main_extract_news.

Uso:
    python scripts/run_news.py [--sports FOOTBALL TENNIS ...] [--max-days 30]
"""
import sys
import os
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from common_functions import launch_navigator
from milestone1 import main_extract_news

DEFAULT_SPORTS = ['FOOTBALL', 'TENNIS', 'GOLF', 'BASKETBALL', 'AMERICAN_SPORTS', 'HOCKEY']

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Extracción de noticias desde FlashScore')
    parser.add_argument('--sports', nargs='+', default=DEFAULT_SPORTS,
                        help='Lista de deportes, e.g. --sports FOOTBALL TENNIS')
    parser.add_argument('--max-days', type=int, default=30,
                        help='MAX_OLDER_DATE_ALLOWED (días atrás), default 30')
    args = parser.parse_args()

    print(f'[INFO] Iniciando extracción de noticias...')
    print(f'[INFO] Deportes: {", ".join(args.sports)}')
    print(f'[INFO] Días máximos: {args.max_days}')

    driver = None
    try:
        print('[INFO] Creando driver (sin login)...')
        driver = launch_navigator('https://www.flashscore.com', headless=False)
        print('[INFO] Driver listo — comenzando extracción...')
        main_extract_news(driver, args.sports, MAX_OLDER_DATE_ALLOWED=args.max_days)
        print('[INFO] Extracción completada.')
    except Exception as e:
        print(f'[ERROR] {type(e).__name__}: {e}')
        raise
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        print('[INFO] Driver cerrado.')
