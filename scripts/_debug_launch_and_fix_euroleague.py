"""
_debug_launch_and_fix_euroleague.py — scratchpad

Lanza un driver propio (NO usa el del notebook), procesa SOLO Euroleague,
actualiza DB para los matches encontrados, y termina (driver se cierra solo).

No requiere login — la pagina /results de FlashScore es publica.
"""

import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from common_functions import launch_navigator, wait_update_page, dismiss_cookies, load_json
from fix_live_matches import (
    get_pending_live_matches, find_results_url,
    load_until_date, scan_results_page, update_match_in_db,
)

LEAGUES_INFO_PATH = os.path.join(ROOT, 'check_points', 'leagues_info.json')


def main():
    print('=' * 65)
    print('[setup] lanzando driver propio (no headless, sin login)')
    print('=' * 65)
    driver = launch_navigator('https://www.flashscore.com', headless=False)
    print('URL inicial: %s' % driver.current_url)

    try:
        print('\n[setup] cargando leagues_info.json')
        leagues_info = load_json(LEAGUES_INFO_PATH)

        print('\n[1] Obteniendo pending Basketball Euroleague')
        all_pending = get_pending_live_matches(sport='Basketball', verbose=False)
        league_matches = [m for m in all_pending if m['league_name'] == 'Euroleague']
        print('   Pending Euroleague: %d' % len(league_matches))
        for m in league_matches[:5]:
            print('   - [%s] %s | %s' % (m['status'], m['match_date'], m['name']))
        if len(league_matches) > 5:
            print('   ... (+%d mas)' % (len(league_matches) - 5))

        if not league_matches:
            print('Sin matches Euroleague pending. Nada que hacer.')
            return

        sn = league_matches[0]['sport_name']
        cn = league_matches[0]['country_name']
        ln = league_matches[0]['league_name']
        results_url = find_results_url(leagues_info, sn, cn, ln)
        print('\n[2] URL results: %s' % results_url)

        print('\n[3] Navegando + load_until_date')
        wait_update_page(driver, results_url, 'container__heading')
        dismiss_cookies(driver)
        oldest = min(m['match_date'] for m in league_matches)
        load_until_date(driver, oldest)

        print('\n[4] scan_results_page (con matcher FIXED)')
        found = scan_results_page(driver, league_matches)
        print('\n   Encontrados: %d / %d' % (len(found), len(league_matches)))

        print('\n[5] Aplicando UPDATEs en DB (status -> COMPLETED + scores)')
        stats = {'ok': 0, 'error': 0, 'not_found': 0}
        for m in league_matches:
            if m['match_id'] not in found:
                stats['not_found'] += 1
                continue
            try:
                ok = update_match_in_db(driver, m, found[m['match_id']], dry_run=False)
                stats['ok' if ok else 'error'] += 1
            except Exception as e:
                print('   [ERROR] %s: %s' % (m['name'], e))
                stats['error'] += 1

        print('\n' + '=' * 65)
        print('RESUMEN:')
        print('  Actualizados : %d' % stats['ok'])
        print('  No encontrados: %d' % stats['not_found'])
        print('  Errores       : %d' % stats['error'])
        print('=' * 65)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == '__main__':
    main()
