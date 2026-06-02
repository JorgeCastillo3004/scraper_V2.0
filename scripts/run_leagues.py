"""Wrapper CLI para lanzar creación de ligas desde la API."""
import argparse, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from common_functions import launch_navigator, login
from milestone2 import create_leagues
from config import FS_EMAIL, FS_PASSWORD

parser = argparse.ArgumentParser()
parser.add_argument('--sports', default='FOOTBALL')
args = parser.parse_args()

sports = [s.strip() for s in args.sports.split(',')]
print(f'[LEAGUES] Iniciando creación: deportes={sports}')

driver = launch_navigator('https://www.flashscore.com', headless=True)
login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
create_leagues(driver, sports)
driver.quit()
print('[LEAGUES] Creación finalizada')
