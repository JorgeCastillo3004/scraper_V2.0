import os,sys,time
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
sys.path.insert(0,ROOT); sys.path.insert(0,os.path.join(ROOT,'scripts')); sys.path.insert(0,os.path.join(ROOT,'src'))
from driver_session import get_driver
import milestone6 as M6
drv=get_driver(os.path.join(ROOT,'tmp','test_tennis_driver.json'))
for url in ['https://www.flashscore.com/player/rus-arantxa/84GyAaXB/',
            'https://www.flashscore.com/player/bolkvadze-mariam/vySLbjQG/']:
    drv.get(url); time.sleep(3)
    info=M6.get_all_player_info_tennis(drv)
    print(url.split('/player/')[1].split('/')[0])
    print("  claves:", list(info.keys()))
    print("  age?:", 'age' in info, "| Age?:", 'Age' in info)
