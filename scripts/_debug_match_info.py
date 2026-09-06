"""
_debug_match_info.py — inspecciona la página de match ACTUAL (read-only, sin
navegar ni abrir pestañas) para ver dónde está el VENUE/estadio.
"""
import os, sys, time
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'src'))
from selenium.webdriver.common.by import By
from driver_session import get_driver

drv = get_driver()
# volver a la primera pestaña (donde quedó la página de match) y cerrar extras
handles = drv.window_handles
if len(handles) > 1:
    for h in handles[1:]:
        try:
            drv.switch_to.window(h); drv.close()
        except Exception: pass
    drv.switch_to.window(drv.window_handles[0])
print('URL actual:', drv.current_url)

print('\n=== duelParticipant__startTime ===')
print([e.text for e in drv.find_elements(By.CLASS_NAME, 'duelParticipant__startTime')])

print('\n=== //div[@class="matchInfoData"]/div (selector usado por get_match_info) ===')
els = drv.find_elements(By.XPATH, '//div[@class="matchInfoData"]/div')
print('count:', len(els))
for e in els[:20]: print('   ', repr(e.text))

print('\n=== conteo de selectores candidatos ===')
for css in ['[class*="matchInfo"]', '[class*="wcl-infoValue"]', '[class*="wcl-overline"]',
            '[data-testid*="match"]', '.mi__item', '[class*="mi__"]']:
    print(f'  {css}: {len(drv.find_elements(By.CSS_SELECTOR, css))}')

print('\n=== muestra de elementos [class*="matchInfo"] (texto + clase) ===')
for e in drv.find_elements(By.CSS_SELECTOR, '[class*="matchInfo"]')[:15]:
    t = e.text.replace("\n", " | ").strip()
    if t: print(f'   [{e.get_attribute("class")}] {t[:100]}')

print('\n=== líneas del body con VENUE/ESTADIO/STADIUM/CAPAC ===')
try:
    for line in drv.find_element(By.TAG_NAME, 'body').text.split('\n'):
        if any(k in line.upper() for k in ['VENUE', 'ESTADIO', 'STADIUM', 'CAPAC']):
            print('   >>', line.strip()[:100])
except Exception as e:
    print('   (no body text:', e, ')')
print('\n[done] driver vivo intacto.')
