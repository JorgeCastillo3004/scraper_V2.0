"""Inspeccionar la estructura interna de [data-testid="wcl-statistics"] en EPL."""
import os, sys, time, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

from selenium.webdriver.common.by import By
from fix_null_team_ids import _reuse_driver_session


URL = ('https://www.flashscore.com/match/football/brighton-2XrRecc3/'
       'manchester-united-ppjDR086/?mid=xQXUa3UG#/match-summary/match-statistics/0')


def main():
    drv = _reuse_driver_session()
    if drv is None:
        print('NO DRIVER'); return

    base = drv.current_window_handle
    drv.execute_script("window.open(arguments[0])", URL)
    time.sleep(2)
    new = [h for h in drv.window_handles if h != base][-1]
    drv.switch_to.window(new)

    try:
        # Esperar
        time.sleep(5)
        print(f'current_url: {drv.current_url}')

        # Dump outerHTML del primer wcl-statistics
        html = drv.execute_script("""
            var el = document.querySelector('[data-testid="wcl-statistics"]');
            return el ? el.outerHTML : null;
        """)
        print('\n=== outerHTML del primer wcl-statistics ===')
        print(html)

        # Verificar los 3 selectores que el JS actual usa
        print('\n=== Verificación de selectores hijos ===')
        probes = drv.execute_script("""
            return Array.from(document.querySelectorAll('[data-testid="wcl-statistics"]')).slice(0,3).map(el => ({
                outer: el.outerHTML,
                category_via_testid: !!el.querySelector('[data-testid="wcl-statistics-category"]'),
                home_via_homeValue: !!el.querySelector('[class*="homeValue"]'),
                away_via_awayValue: !!el.querySelector('[class*="awayValue"]'),
                child_class_names: Array.from(el.children).map(c => c.className),
                text: el.textContent
            }));
        """)
        for i, p in enumerate(probes):
            print(f'\n--- statistic [{i}] ---')
            print(f'  category_via_testid={p["category_via_testid"]}')
            print(f'  home_via_homeValue={p["home_via_homeValue"]}')
            print(f'  away_via_awayValue={p["away_via_awayValue"]}')
            print(f'  child class names: {p["child_class_names"]}')
            print(f'  text: {p["text"]!r}')
    finally:
        drv.close()
        drv.switch_to.window(base)


if __name__ == '__main__':
    main()
