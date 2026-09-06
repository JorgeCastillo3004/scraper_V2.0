"""Debug: validar que _no_match_visible() rechaza el falso positivo en WC."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from driver_session import get_driver
from fix_live_matches import _no_match_visible
import time

drv = get_driver()
orig = drv.window_handles
drv.execute_script("window.open(arguments[0])",
                   "https://www.flashscore.com/football/world/world-cup/results/")
time.sleep(4)
new = [h for h in drv.window_handles if h not in orig][0]
drv.switch_to.window(new)
time.sleep(3)

print(f"url: {drv.current_url}")
print(f"_no_match_visible() => {_no_match_visible(drv)}  (esperado: False, hay 124 matches)")

drv.close()
drv.switch_to.window(orig[0])
