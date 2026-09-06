"""
_debug_stats.py — diagnóstico de get_statistics_game.

Se conecta al driver vivo (NO lanza Firefox nuevo). Para cada liga objetivo:
  - Abre la página de results en pestaña nueva
  - Toma el URL del primer match con marcador (jugado)
  - Abre el match en otra pestaña
  - Prueba múltiples selectores para detectar el tab Stats
  - Reporta hallazgos
  - Cierra ambas pestañas y vuelve a la pestaña principal

NO modifica DB. NO mata el driver. Solo lee DOM.
"""

import os, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from fix_null_team_ids import _reuse_driver_session


# Liga-results-URL, hint
LIGAS_PRUEBA = [
    # CONTROL POSITIVO: liga top con cobertura estadística rica
    ('https://www.flashscore.com/football/england/premier-league/results/',
     'EPL — control positivo'),
    # TEST 1: Liga A basket Argentina (183 sin stats en DB)
    ('https://www.flashscore.com/basketball/argentina/liga-a/results/',
     'Liga A basket Argentina'),
    # TEST 2 directo: el match Jamaica~Guatemala (NACA WC eliminatoria)
    # ya verificado: 0 stats. Lo dejo como referencia.
]

JAMAICA_GUATEMALA = (
    'https://www.flashscore.com/match/2yJSbB6T/#/match-summary/match-summary',
    'Jamaica~Guatemala (NACA WC)'
)


def in_tab(driver, url, fn, base_handle):
    """Abre pestaña, ejecuta fn, cierra pestaña, vuelve a base_handle."""
    driver.execute_script("window.open(arguments[0])", url)
    time.sleep(1)
    new_handle = [h for h in driver.window_handles if h != base_handle][-1]
    driver.switch_to.window(new_handle)
    try:
        return fn(driver)
    finally:
        try:
            driver.close()
        except Exception:
            pass
        driver.switch_to.window(base_handle)


def grab_first_match_url(driver):
    """Estando en la página de results de una liga, retorna el URL
    del primer match con marcador (jugado)."""
    try:
        # Esperar matches cargados
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class*="event__match"]'))
        )
    except Exception:
        return None
    # Tomar el primer match con event__score (jugado)
    rows = driver.find_elements(By.CSS_SELECTOR, 'div[class*="event__match"]')
    for row in rows[:15]:
        try:
            row.find_element(By.CSS_SELECTOR, '[class*="event__score--home"]')
        except Exception:
            continue
        # FlashScore renderiza el link via JS. El link real está al hacer click,
        # pero también está en data-event-row-id o construible con id.
        # Más simple: extract via JS el href del anchor del row.
        try:
            href = driver.execute_script(
                "var a=arguments[0].querySelector('a'); return a ? a.href : null;",
                row
            )
            if href:
                return href
        except Exception:
            pass
    return None


def diagnose_match_page(driver, url, hint):
    print(f'\n{"="*72}\nMATCH: {hint}\nURL: {url}\n{"="*72}')

    print('[1] Esperando carga (duelParticipant, 30s)...')
    try:
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'duelParticipant'))
        )
        print(f'    OK — current_url: {driver.current_url}')
    except Exception as e:
        print(f'    FALLO duelParticipant: {e}')
        return

    # Esperar más a que cargue todo
    time.sleep(2)

    # PROBE A: selector original
    btns = driver.find_elements(By.XPATH, '//button[contains(.,"Stats")]')
    print(f'[A] //button[contains(.,"Stats")]: {len(btns)} encontrados')

    # PROBE B: cualquier elemento con texto Stats
    elems = driver.find_elements(
        By.XPATH, '//*[contains(text(),"Stats") and not(self::script) and not(self::style)]'
    )
    print(f'[B] cualquier elemento texto "Stats": {len(elems)}')
    for i, e in enumerate(elems[:5]):
        try:
            tag = e.tag_name
            text = (e.text or '')[:50]
            cls = (e.get_attribute('class') or '')[:60]
            disp = e.is_displayed()
            print(f'    <{tag}> displayed={disp} text={text!r} class={cls!r}')
        except Exception:
            pass

    # PROBE C: tabs por data-testid o role
    print('[C] tabs/nav:')
    for sel in [
        '[data-testid*="wcl-tab"]',
        '[role="tab"]',
        'a[href*="match-statistics"]',
        'a[href*="statistics"]',
    ]:
        try:
            ee = driver.find_elements(By.CSS_SELECTOR, sel)
            if ee:
                print(f'    "{sel}" → {len(ee)}')
                seen = set()
                for e in ee[:8]:
                    try:
                        key = (e.tag_name, e.get_attribute('href') or '', (e.text or '')[:30])
                        if key in seen:
                            continue
                        seen.add(key)
                        href = (e.get_attribute('href') or '')[-60:]
                        text = (e.text or '')[:30]
                        tid = e.get_attribute('data-testid') or ''
                        print(f'      <{e.tag_name}> tid={tid!r} text={text!r} href={href!r}')
                    except Exception:
                        pass
        except Exception:
            pass

    # PROBE D: navegación directa a /match-statistics/0
    base = url.split('/#/')[0]
    stats_url = f'{base}#/match-summary/match-statistics/0'
    print(f'[D] navegando a {stats_url}')
    try:
        driver.execute_script('window.location.href = arguments[0]', stats_url)
        time.sleep(4)
        print(f'    landed: {driver.current_url}')
        for sel in [
            '[data-testid="wcl-statistics"]',
            '[class*="statCategory"]',
            '[class*="_statisticBox_"]',
            '[class*="stat__row"]',
            '[class*="wcl-statistics"]',
            'div._row_1pvfu_7',  # ejemplo de hash de tailwind cssmodules
        ]:
            ee = driver.find_elements(By.CSS_SELECTOR, sel)
            if ee:
                print(f'    "{sel}" → {len(ee)} elementos')
                for e in ee[:3]:
                    try:
                        cls = (e.get_attribute('class') or '')[:80]
                        text = (e.text or '').replace('\n', ' | ')[:80]
                        print(f'      class={cls!r} text={text!r}')
                    except Exception:
                        pass
    except Exception as e:
        print(f'    error: {e}')

    # PROBE E: dump del título y un pedazo del HTML del cuerpo si nada apareció
    if not btns and not elems:
        print('[E] dump fragmento HTML para inspección')
        try:
            body_html = driver.execute_script(
                "var d=document.querySelector('div[class*=\"detail\"]') || document.body; "
                "return d.outerHTML.substring(0, 800);"
            )
            print(f'    body[:800]: {body_html!r}')
        except Exception as e:
            print(f'    error: {e}')


def diagnose_liga(driver, results_url, hint, base_handle):
    print(f'\n\n{"#"*72}\n# LIGA: {hint}\n# RESULTS URL: {results_url}\n{"#"*72}')
    def step(d):
        print('[L1] cargando results de liga...')
        url = grab_first_match_url(d)
        if not url:
            print('    NO se pudo extraer URL del primer match')
            return
        print(f'    primer match URL: {url}')
        return url

    match_url = in_tab(driver, results_url, step, base_handle)
    if not match_url:
        return

    in_tab(driver, match_url, lambda d: diagnose_match_page(d, match_url, hint), base_handle)


def main():
    print('Conectando al driver vivo...')
    drv = _reuse_driver_session()
    if drv is None:
        print('NO HAY DRIVER VIVO'); return

    print(f'OK — session_id={drv.session_id}')
    print(f'  current_url principal: {drv.current_url}')
    print(f'  pestañas abiertas: {len(drv.window_handles)}')

    base_handle = drv.current_window_handle

    # Primero: re-validar Jamaica~Guatemala (caso ya confirmado)
    in_tab(drv, JAMAICA_GUATEMALA[0],
           lambda d: diagnose_match_page(d, JAMAICA_GUATEMALA[0], JAMAICA_GUATEMALA[1]),
           base_handle)

    # Luego: las ligas de prueba
    for results_url, hint in LIGAS_PRUEBA:
        diagnose_liga(drv, results_url, hint, base_handle)

    print('\n[FIN] driver intacto')
    print(f'  pestaña principal current_url: {drv.current_url}')


if __name__ == '__main__':
    main()
