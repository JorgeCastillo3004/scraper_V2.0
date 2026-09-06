import os,sys
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
sys.path.insert(0,ROOT); sys.path.insert(0,os.path.join(ROOT,'scripts')); sys.path.insert(0,os.path.join(ROOT,'src'))
from driver_session import get_driver
from selenium.webdriver.common.by import By
drv=get_driver(os.path.join(ROOT,'tmp','test_tennis_driver.json'))
drv.get('https://www.flashscore.com/player/rus-arantxa/84GyAaXB/'); import time; time.sleep(3)
pb=drv.find_element(By.CLASS_NAME,'container__heading')
print("=== imgs en container__heading ===")
for im in pb.find_elements(By.XPATH,'.//img'):
    print("  class=",repr(im.get_attribute('class')),"| loading=",im.get_attribute('loading'),"| src=",(im.get_attribute('src') or '')[:55])
