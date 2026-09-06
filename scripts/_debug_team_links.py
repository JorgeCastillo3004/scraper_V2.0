"""Diagnóstico de get_team_links_from_match para identificar bug de team duplicados."""
import os, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from fix_null_team_ids import _reuse_driver_session

# Matches con duplicados confirmados (de la query anterior)
TESTS = [
    ('https://www.flashscore.com/match/pvTiKJgl/#/match-summary/match-summary',
     'San Martin~Atenas 2025-09-27 (Liga A basket)'),
    ('https://www.flashscore.com/match/WnL1Z4Hr/#/match-summary/match-summary',
     'San Lorenzo~Penarol 2025-09-27 (Liga A basket)'),
]


def main():
    drv = _reuse_driver_session()
    if drv is None:
        print('NO DRIVER'); return

    base = drv.current_window_handle
    print(f'driver vivo session={drv.session_id}')

    for url, hint in TESTS:
        print(f'\n{"="*80}\n{hint}\nURL: {url}\n{"="*80}')

        drv.execute_script("window.open(arguments[0])", url)
        time.sleep(3)
        new = [h for h in drv.window_handles if h != base][-1]
        drv.switch_to.window(new)

        try:
            print(f'\n[1] current_url tras navegación:')
            print(f'    {drv.current_url}')
            print(f'\n[2] title:')
            print(f'    {drv.title!r}')

            # Esperar duelParticipant
            time.sleep(3)

            # Probe A: selector actual
            xpath_all = "//a[contains(@class,'participant__participantName')]"
            links = drv.find_elements(By.XPATH, xpath_all)
            print(f'\n[3] Selector actual //a[contains(@class,"participant__participantName")]:')
            print(f'    encontrados: {len(links)}')
            for i, l in enumerate(links):
                try:
                    href = l.get_attribute('href') or ''
                    text = (l.text or '').strip()[:30]
                    cls = (l.get_attribute('class') or '')[:60]
                    print(f'    [{i}] text={text!r:<25} href={href[-50:]!r}')
                    print(f'        class={cls!r}')
                except Exception as e:
                    print(f'    [{i}] error: {e}')

            # Probe B: estructura duelParticipant — home / away separados
            print(f'\n[4] Estructura duelParticipant (home / away separados):')
            for side in ['home', 'away']:
                xp = f"//div[contains(@class,'duelParticipant__{side}')]//a[contains(@class,'participant__participantName')]"
                ee = drv.find_elements(By.XPATH, xp)
                print(f'    duelParticipant__{side}: {len(ee)} link(s)')
                for i, e in enumerate(ee[:3]):
                    try:
                        href = e.get_attribute('href') or ''
                        text = (e.text or '').strip()[:30]
                        print(f'      [{i}] {text!r} href={href[-50:]!r}')
                    except: pass

            # Probe C: nombres de equipos visibles en duelParticipant
            print(f'\n[5] duelParticipant — texto completo del header:')
            try:
                dp = drv.find_element(By.CLASS_NAME, 'duelParticipant')
                print(f'    text:\n    {dp.text!r}')
            except Exception as e:
                print(f'    error: {e}')

        finally:
            drv.close()
            drv.switch_to.window(base)


if __name__ == '__main__':
    main()
