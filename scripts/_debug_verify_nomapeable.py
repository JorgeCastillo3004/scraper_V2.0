#!/usr/bin/env python3
"""_debug_verify_nomapeable — verifica en FlashScore (navegando como create_leagues)
las 4 ligas marcadas "no mapeable" en el panel de Inconsistencias.

Para cada URL candidata: navega con wait_update_page (espera 'container__heading')
y lee el MISMO bloque que usa get_league_data (milestone2) en el flujo de creación:
  - deporte : breadcrumb/a[1]
  - país    : breadcrumb/a[2]
  - liga    : heading__title
  - temporada: heading__info

SOLO LECTURA: reusa el driver vivo con get_driver() (NUNCA .quit()). No escribe
en DB ni en ningún JSON. Reporta el resultado por liga para decidir el mapeo.
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from driver_session import get_driver
from common_functions import wait_update_page

# (etiqueta, league_id en BD, deporte esperado, país esperado, [URLs candidatas])
CANDIDATES = [
    ('Extraliga',        '67ac7f77-682d-4fc0-a1e4-0dbb04b8b80b', 'HOCKEY',   'Czech Republic',
        ['https://www.flashscore.com/hockey/czech-republic/extraliga/']),
    ('Liiga',            '9d698813-a2bf-408b-ab43-9bdbe903f247', 'HOCKEY',   'Finland',
        ['https://www.flashscore.com/hockey/finland/liiga/']),
    ('DEL',              '7a85d30d-5bdf-46b6-a682-bc658e64783b', 'HOCKEY',   'Germany',
        ['https://www.flashscore.com/hockey/germany/del/']),
    ('Torneo Betano',    '3dc916f0-cbd8-4073-aaea-b6c06216c254', 'FOOTBALL', 'Argentina',
        ['https://www.flashscore.com/football/argentina/torneo-betano/',
         'https://www.flashscore.com/football/argentina/liga-profesional/']),
    # bonus: la 5ª no mapeable (tarjeta no_statistics)
    ('European Cup of Nations', 'f3682be9-6626-4b5e-aefd-eb90c362b18b', 'HOCKEY', 'Europe',
        ['https://www.flashscore.com/hockey/europe/european-cup-of-nations/']),
]


def _txt(driver, by, sel):
    try:
        return driver.find_element(by, sel).text.strip()
    except Exception:
        return '(n/a)'


def read_heading(driver):
    """Lee deporte/país/liga/temporada del container__heading (igual que milestone2)."""
    block = driver.find_element(By.CLASS_NAME, 'container__heading')
    sport   = block.find_element(By.XPATH, './/h2[@class= "breadcrumb"]/a[1]').text.strip()
    try:
        country = block.find_element(By.XPATH, './/h2[@class= "breadcrumb"]/a[2]').text.strip()
    except Exception:
        country = '(sin a[2])'
    league  = _txt(driver, By.CLASS_NAME, 'heading__title')
    season  = _txt(driver, By.CLASS_NAME, 'heading__info')
    return sport, country, league, season


def main():
    driver = get_driver()
    print('[OK] driver vivo:', driver.current_url)
    print('=' * 80)

    for label, lid, exp_sport, exp_country, urls in CANDIDATES:
        print(f'\n### {label}  (league_id BD={lid})')
        print(f'    esperado: deporte={exp_sport}  país={exp_country}')
        for url in urls:
            print(f'  → navegando: {url}')
            try:
                wait_update_page(driver, url, 'container__heading')
                final = driver.current_url
                sport, country, league, season = read_heading(driver)
                redirect = '  ⚠️REDIRECT' if final.rstrip('/') != url.rstrip('/') else ''
                print(f'     URL final : {final}{redirect}')
                print(f'     deporte   : {sport}')
                print(f'     país      : {country}')
                print(f'     liga      : {league}')
                print(f'     temporada : {season}')
                ok = (exp_sport.lower() in sport.lower()) and (exp_country.lower() in country.lower())
                print(f'     >>> {"✅ COINCIDE deporte+país" if ok else "❌ NO coincide / revisar"}')
            except Exception as e:
                print(f'     ❌ no se pudo cargar (URL inválida / 404 / sin heading): {type(e).__name__}: {str(e)[:120]}')
        print('-' * 80)

    print('\n[done] driver vivo intacto (sin quit).')


if __name__ == '__main__':
    main()
