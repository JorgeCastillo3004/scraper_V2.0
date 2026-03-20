import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import chromedriver_autoinstaller
from selenium import webdriver
from datetime import datetime
import pandas as pd
import random
import time
import json
import re
from datetime import date, timedelta
import string
from common_functions import *
from data_base import *
from milestone7 import *
from milestone8 import *
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FS_EMAIL, FS_PASSWORD

def main_live():
    print("Section live — iniciando loop continuo...")
    retry_count = 0
    MAX_RETRIES = 10
    RETRY_DELAY = 30  # segundos entre reinicios

    while True:
        driver = None
        try:
            driver = launch_navigator('https://www.flashscore.com', headless=True)
            login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
            retry_count = 0  # reset al conectar exitosamente
            section_schedule = update_data()
            live_games(driver, section_schedule.get('LIVE_SECTION', {}).get('SPORTS', ['FOOTBALL']))
        except Exception as e:
            retry_count += 1
            print(f'[ERROR] main_live crash (intento {retry_count}/{MAX_RETRIES}): {type(e).__name__}: {e}')
            if retry_count >= MAX_RETRIES:
                print(f'[ERROR] main_live detenido tras {MAX_RETRIES} crashes consecutivos.')
                break
            print(f'[INFO] Reiniciando en {RETRY_DELAY}s...')
            time.sleep(RETRY_DELAY)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

if __name__ == "__main__":	
	main_live()
	