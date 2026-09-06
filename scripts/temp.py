import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common_functions import launch_navigator

URL = 'https://www.flashscore.com/football/belgium/jupiler-pro-league/standings/'

driver = launch_navigator(URL, headless=False)

wait = WebDriverWait(driver, 10)
tabs_container = wait.until(EC.presence_of_all_elements_located((
    By.XPATH,
    '//div[@data-testid="wcl-tabs" and @data-type="secondary"]/a'
)))

tabs = {
    tab.find_element(By.XPATH, './/button[@data-testid="wcl-tab"]').text: tab.get_attribute('href')
    for tab in tabs_container
}

for text, href in tabs.items():
    print(f'  {text}: {href}')

driver.quit()
