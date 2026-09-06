"""
_debug_diagnostic_scan.py — diagnostico granular del fallo 0/64

Reproduce el scan pero IMPRIME para cada match:
 - hits_text  : rows cuyo texto normalizado contiene ambos nombres
 - hits_html  : de esos, cuantos tienen 'Click for details!'
 - sample     : un text de hit si hay
Tambien lista TODOS los rows que contienen "hapoel tel aviv" y muestra
su texto (fecha + rival) para confirmar si los matches contra Zalgiris,
Dubai, Paris, etc. estan o no cargados.
"""

import os, sys
from datetime import date
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from common_functions import launch_navigator, wait_update_page, dismiss_cookies
from fix_live_matches import get_pending_live_matches, load_until_date


def _norm(s):
    return s.lower().replace('-', '').replace(' ', '')


def main():
    drv = launch_navigator('https://www.flashscore.com', headless=False)
    try:
        url = 'https://www.flashscore.com/basketball/europe/euroleague/results/'
        wait_update_page(drv, url, 'container__heading')
        dismiss_cookies(drv)
        load_until_date(drv, date(2025, 12, 30))

        rows = drv.find_elements(By.XPATH, '//div[contains(@class,"leagues--static event--leagues")]/div')
        print('\nTOTAL ROWS: %d' % len(rows))

        # Pre-cachear info de cada row
        row_data = []
        for r in rows:
            try:
                t = r.text
                t_norm = _norm(t)
                html = r.get_attribute('outerHTML') or ''
            except Exception:
                continue
            row_data.append({
                'text': t,
                'norm': t_norm,
                'has_tooltip': 'Click for details!' in html or 'Click for match detail!' in html,
                'cls': r.get_attribute('class') or '',
            })

        # Stats globales
        with_tooltip = sum(1 for r in row_data if r['has_tooltip'])
        print('Rows con tooltip "Click for details!": %d' % with_tooltip)

        # Listar rows Hapoel
        print('\n=== Todos los rows con "hapoel tel aviv" ===')
        hap_rows = [r for r in row_data if 'hapoeltelaviv' in r['norm']]
        print('Total: %d' % len(hap_rows))
        for r in hap_rows:
            first2 = ' | '.join([ln for ln in r['text'].splitlines() if ln.strip()][:3])
            print('  tooltip=%s  %s' % (r['has_tooltip'], first2))

        # Diagnostico por target
        print('\n=== Diagnostico target-by-target (Basketball Euroleague pending) ===')
        pending = get_pending_live_matches(sport='Basketball', verbose=False)
        targets = [m for m in pending if m['league_name'] == 'Euroleague']
        print('Pending Euroleague: %d' % len(targets))

        not_found_text = 0
        text_yes_html_no = 0
        ok = 0
        for m in targets:
            home, _, visitor = m['name'].partition('~')
            h, v = _norm(home), _norm(visitor)
            hits_text = [r for r in row_data if h in r['norm'] and v in r['norm']]
            hits_html = [r for r in hits_text if r['has_tooltip']]
            if not hits_text:
                not_found_text += 1
            elif not hits_html:
                text_yes_html_no += 1
                sample = hits_text[0]
                first3 = ' | '.join([ln for ln in sample['text'].splitlines() if ln.strip()][:4])
                print('  [TEXT_NO_TOOLTIP] %s  -> %s' % (m['name'], first3))
            else:
                ok += 1

        print('\n=== RESUMEN DIAGNOSTICO ===')
        print('  total targets             : %d' % len(targets))
        print('  ok (text+tooltip)         : %d' % ok)
        print('  text matches, no tooltip  : %d' % text_yes_html_no)
        print('  no text match             : %d' % not_found_text)
    finally:
        try:
            drv.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
