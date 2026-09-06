"""
_debug_pin_check.py — scratchpad de CONFIRMACIÓN (metodología notebook)
======================================================================
Objetivo (pedido por Jorge): en el driver vivo, en la sección ALL del link
inicial del deporte, detectar los partidos de las LIGAS PINEADAS (data-pinned)
y mostrar NOMBRE (home~visitor) + HORA de juego. Con esto confirmamos que la
detección de pin es la correcta (la misma que usa el flujo live de milestone7).

Reusa SOLO lo existente:
  - common_functions.load_json / wait_update_page / dismiss_cookies
  - milestone7.get_live_result   (extrae name=home~visitor, home, visitor, scores)
La única lectura extra es la HORA (event__time), que get_live_result no trae.
NO hace click en LIVE (es la vista ALL). NO escribe en DB. NO cierra nada.
"""
import os, sys, time
from datetime import datetime
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from driver_session import get_driver
from common_functions import load_json, wait_update_page, dismiss_cookies
from milestone7 import get_live_result   # reuso exacto del flujo live
from data_base import get_match_id, strip_phase_suffix   # get_match_id ya normaliza la liga

SPORT = sys.argv[1] if len(sys.argv) > 1 else 'FOOTBALL'


def row_time(row):
    """Hora de juego de la fila (event__time); '' si no la tiene."""
    try:
        return row.find_element(By.XPATH, './/div[contains(@class,"event__time")]').text.strip()
    except Exception:
        return ''


def main():
    drv = get_driver()
    today = datetime.now().date()
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    url = dict_sports_url[SPORT]
    print(f'[{SPORT}] vista ALL -> {url}  | fecha={today}')
    wait_update_page(drv, url, 'container__heading')
    dismiss_cookies(drv)

    # esperar a que rendericen las ligas pineadas (antes leí demasiado pronto)
    for _ in range(12):
        if drv.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-headerLeague"][data-pinned="true"]'):
            break
        time.sleep(1)

    sn = 'soccer' if SPORT == 'FOOTBALL' else SPORT.lower()
    rows = drv.find_elements(By.XPATH, f'//div[@class="sportName {sn}"]/div')
    print(f'filas en el bloque: {len(rows)}')

    # MISMA lógica de detección que milestone7.get_live_match: header con
    # data-pinned="true" habilita la carga de sus partidos.
    enable_load = False
    league_name = league_country = ''
    total = in_db = missing = 0
    for row in rows:
        try:
            row.find_element(By.XPATH, './/span[contains(@class,"headerLeague__title-text")]')
            is_header = True
        except Exception:
            is_header = False

        if is_header:
            enable_load = False
            try:
                league_name = row.find_element(By.XPATH, './/a[@class="headerLeague__title"]').text
                league_country = row.find_element(By.XPATH, './/span[@class="headerLeague__category-text"]').text
                pinned = row.find_element(By.XPATH, './/div[@data-testid="wcl-headerLeague"]')
                if pinned.get_attribute('data-pinned') == 'true':
                    enable_load = True
                    print(f'\n*** LIGA PINEADA: {league_country} / {league_name} ***')
            except Exception:
                pass
            continue

        if enable_load:
            try:
                info = get_live_result(row)
            except Exception:
                continue
            total += 1
            # verificación en DB con código existente: por name (home~visitor) + fecha
            # MISMOS 4 campos que usa el flujo live -> get_match_id(
            #   league_country, league_name, match_date, match_name)
            # get_match_id ya normaliza la liga (recorta el sufijo de fase) e
            # imprime las palabras exactas usadas; pasamos el nombre crudo.
            league_db = strip_phase_suffix(league_name)   # solo para mostrarlo aquí
            mid = get_match_id(league_country, league_name, today, info['name'])
            estado = f'IN DB (match_id={mid})' if mid else '*** FALTA EN DB ***'
            if mid:
                in_db += 1
            else:
                missing += 1
            print(f'  {row_time(row):>6}  {info["name"]}  -> {estado}')
            # campos EXACTOS enviados a la solicitud get_match_id (DB):
            print(f'         pais        = "{league_country}"')
            print(f'         liga (DOM)  = "{league_name}"')
            print(f'         liga (DB)   = "{league_db}"   <- usado en el match')
            print(f'         match_date  = "{today}"')
            print(f'         match_name  = "{info["name"]}"')

    print(f'\nTOTAL pineados: {total}  |  en DB: {in_db}  |  faltan: {missing}')
    print('[done] driver vivo intacto.')


if __name__ == '__main__':
    main()
