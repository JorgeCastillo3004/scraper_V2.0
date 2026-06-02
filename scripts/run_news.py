"""
scripts/run_news.py
───────────────────
Runner de extracción de noticias. Soporta dos formas de pasar deportes:
  --sports FOOTBALL,TENNIS   (coma-separado, usado por la API)
  --sports FOOTBALL TENNIS   (espacio-separado, uso manual)
"""
import sys, os, argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from common_functions import launch_navigator, login
from milestone1 import main_extract_news
from config import FS_EMAIL, FS_PASSWORD

DEFAULT_SPORTS = ['FOOTBALL', 'TENNIS', 'GOLF', 'BASKETBALL', 'AMERICAN_SPORTS', 'HOCKEY']

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sports', default='')
    parser.add_argument('--days',   type=int, default=31)
    args = parser.parse_args()

    if args.sports:
        sports = [s.strip() for s in args.sports.replace(',', ' ').split()]
    else:
        sports = DEFAULT_SPORTS

    print(f'[NEWS] deportes={sports}  días={args.days}')

    driver = None
    try:
        driver = launch_navigator('https://www.flashscore.com', headless=True)
        login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
        main_extract_news(driver, sports, MAX_OLDER_DATE_ALLOWED=args.days)
        print('[NEWS] Extracción completada.')
    except Exception as e:
        print(f'[ERROR] {type(e).__name__}: {e}')
        raise
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
