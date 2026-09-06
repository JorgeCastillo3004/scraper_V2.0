"""Probar el fix de fix_match_statistic sobre Brighton~Man United (EPL).

Driver vivo, pestaña nueva, dry_run=True para NO modificar DB.
"""
import os, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from fix_null_team_ids import _reuse_driver_session, fix_match_statistic

# URLs de prueba
TESTS = [
    # (URL del match (sin la sub-ruta de stats), match_id ficticio, hint)
    ('https://www.flashscore.com/match/football/brighton-2XrRecc3/manchester-united-ppjDR086/?mid=xQXUa3UG',
     'fake-epl-id', 'EPL Brighton~Man United (control positivo)'),
    ('https://www.flashscore.com/match/2yJSbB6T/#/match-summary/match-summary',
     'fake-naca-id', 'Jamaica~Guatemala (esperado: skip)'),
    ('https://www.flashscore.com/match/basketball/boca-juniors-pn7Cecgf/quimsa-E7pXLvd8/?mid=vqK0Z5jS',
     'fake-basket-id', 'Liga A basket Boca~Quimsa (esperado: skip)'),
]


def main():
    drv = _reuse_driver_session()
    if drv is None:
        print('NO DRIVER'); return

    base = drv.current_window_handle
    print(f'driver vivo — session_id={drv.session_id}')
    print(f'  pestaña principal: {drv.current_url}')

    for url, fake_match_id, hint in TESTS:
        print(f'\n{"="*72}\n{hint}\nURL: {url}\n{"="*72}')

        # Abrir pestaña nueva
        drv.execute_script("window.open(arguments[0])", url)
        time.sleep(2)
        new = [h for h in drv.window_handles if h != base][-1]
        drv.switch_to.window(new)

        try:
            # Esperar a duelParticipant (el script de fix hace esto antes)
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            try:
                WebDriverWait(drv, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, 'duelParticipant'))
                )
            except Exception as e:
                print(f'  duelParticipant timeout: {e}')

            # Llamar al fix con dry_run=True (no toca DB; con=None está OK porque dry_run no usa el cursor)
            result = fix_match_statistic(con=None, driver=drv, match_id=fake_match_id, dry_run=True)
            print(f'  resultado: {result}')
        finally:
            try:
                drv.close()
            except Exception:
                pass
            drv.switch_to.window(base)

    print(f'\n[FIN] pestaña principal: {drv.current_url}')


if __name__ == '__main__':
    main()
