"""
_debug_inspect_row.py — diagnostico del filtro HTML "Click for match detail!"

Lanza driver propio, va a Euroleague results, carga via load_until_date
(misma logica que produjo 343 rows), busca rows que contengan "Hapoel Tel Aviv"
y dumpea outerHTML/atributos para ver el tooltip real sin login.
"""

import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from common_functions import launch_navigator, wait_update_page, dismiss_cookies
from fix_live_matches import load_until_date


def main():
    drv = launch_navigator('https://www.flashscore.com', headless=False)
    try:
        url = 'https://www.flashscore.com/basketball/europe/euroleague/results/'
        wait_update_page(drv, url, 'container__heading')
        dismiss_cookies(drv)

        from datetime import date
        load_until_date(drv, date(2025, 12, 30))

        rows = drv.find_elements(By.XPATH, '//div[contains(@class,"leagues--static event--leagues")]/div')
        print('Total rows: %d' % len(rows))

        hits = []
        for r in rows:
            try:
                t = r.text.lower().replace('-', '').replace(' ', '')
            except Exception:
                continue
            if 'hapoeltelaviv' in t:
                hits.append(r)
        print('Rows con "hapoel tel aviv": %d' % len(hits))

        any_match = None
        for r in rows[:60]:
            try:
                cls = (r.get_attribute('class') or '').lower()
                rid = (r.get_attribute('id') or '').lower()
            except Exception:
                continue
            if 'event__match' in cls or rid.startswith('g_'):
                any_match = r
                break

        sample = hits[:2] + ([any_match] if any_match is not None else [])
        for i, r in enumerate(sample):
            print('\n' + '=' * 70)
            print('SAMPLE %d' % i)
            print('=' * 70)
            try:
                print('TEXT:\n%s' % r.text)
            except Exception as e:
                print('  (no text: %s)' % e)
            try:
                print('\nCLASS: %s' % r.get_attribute('class'))
                print('ID:    %s' % r.get_attribute('id'))
                print('TITLE: %s' % r.get_attribute('title'))
            except Exception as e:
                print('  (attrs error: %s)' % e)
            try:
                html = r.get_attribute('outerHTML') or ''
                print('\nHTML LEN: %d' % len(html))
                print('  "Click for match detail!" : %s' % ('Click for match detail!' in html))
                print('  "Click for details!"      : %s' % ('Click for details!' in html))
                print('  "match detail"            : %s' % ('match detail' in html.lower()))
                print('  "haz click"               : %s' % ('haz click' in html.lower()))
                print('  "click"                   : %s' % ('click' in html.lower()))
                print('  "event__match"            : %s' % ('event__match' in html))
                import re as _re
                titles = _re.findall(r'title="([^"]+)"', html)
                print('  TITLES en HTML: %s' % titles[:8])
                print('\nHTML SNIPPET (primeros 1200):')
                print(html[:1200])
            except Exception as e:
                print('  (html error: %s)' % e)
    finally:
        try:
            drv.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
