"""
pin_leagues_match_count.py — Conteo de partidos en DB por LIGA PINEADA
======================================================================
Carga las LIGAS PINEADAS mostradas en la vista ALL del deporte (mismas que
detecta el flujo live: header con data-pinned="true") y, para cada una,
cuenta cuántos partidos tiene creados en la base de datos.

La búsqueda en DB se hace con los campos que -segun verificamos- son
suficientes: PAIS + NOMBRE DE LIGA (el deporte se registra como referencia).

Reusa SOLO funciones/lógica ya existentes (todas read-only):
  - detección de pin: data-pinned + milestone7.get_live_result   (igual que el live)
  - resolve_league_id(): el JOIN league⋈country del dry-run probado
  - common_functions.load_json / wait_update_page / dismiss_cookies
  - data_base.getdb()

Salida: por pantalla + archivo log con  sport | pais | liga | nº partidos.
NO escribe ni borra en DB (solo SELECT/count). NO cierra ni relanza el driver.

Uso:
  env_sports/bin/python scripts/pin_leagues_match_count.py            # FOOTBALL
  env_sports/bin/python scripts/pin_leagues_match_count.py BASKETBALL
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
from data_base import getdb
# reuso del resolver probado (JOIN league⋈country) del dry-run
from _debug_pin_insert_dryrun import resolve_league_id

SPORT = sys.argv[1] if len(sys.argv) > 1 else 'FOOTBALL'


def count_matches(con, league_id, today):
    """(total, hoy) partidos de la liga en DB. Solo SELECT/count."""
    cur = con.cursor()
    cur.execute('SELECT count(*) FROM match WHERE league_id = %s', (league_id,))
    total = cur.fetchone()[0]
    cur.execute('SELECT count(*) FROM match WHERE league_id = %s AND match_date = %s',
                (league_id, today))
    hoy = cur.fetchone()[0]
    return total, hoy


def main():
    drv = get_driver()
    today = datetime.now().date()
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    url = dict_sports_url[SPORT]

    stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    log_path = os.path.join(ROOT, 'logs', f'pin_match_count_{SPORT}_{stamp}.log')
    logf = open(log_path, 'w', encoding='utf-8')

    def out(line=''):
        print(line)
        logf.write(line + '\n')
        logf.flush()

    out(f'[{SPORT}] vista ALL -> {url}  | fecha={today}')
    out(f'log: {log_path}')

    con = getdb()
    wait_update_page(drv, url, 'container__heading')
    dismiss_cookies(drv)

    # esperar render de ligas pineadas
    for _ in range(12):
        if drv.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-headerLeague"][data-pinned="true"]'):
            break
        time.sleep(1)

    sn = 'soccer' if SPORT == 'FOOTBALL' else SPORT.lower()
    rows = drv.find_elements(By.XPATH, f'//div[@class="sportName {sn}"]/div')

    out(f'\n{"DEPORTE":<10} | {"PAIS":<22} | {"LIGA":<32} | {"TOTAL":>6} | {"HOY":>4}')
    out('-' * 90)

    n_ligas = total_partidos = 0
    seen = set()
    for row in rows:
        # ¿es header de liga?
        try:
            row.find_element(By.XPATH, './/span[contains(@class,"headerLeague__title-text")]')
        except Exception:
            continue

        try:
            league_name = row.find_element(By.XPATH, './/a[@class="headerLeague__title"]').text
            league_country = row.find_element(By.XPATH, './/span[@class="headerLeague__category-text"]').text
            pinned = row.find_element(By.XPATH, './/div[@data-testid="wcl-headerLeague"]')
            if pinned.get_attribute('data-pinned') != 'true':
                continue
        except Exception:
            continue

        key = (league_country, league_name)
        if key in seen:
            continue
        seen.add(key)
        n_ligas += 1

        league_id, cands = resolve_league_id(con, league_country, league_name)
        if not league_id:
            out(f'{SPORT:<10} | {league_country:<22} | {league_name:<32} | '
                f'{"N/D":>6} | {"-":>4}   <- LIGA NO ENCONTRADA EN DB')
            if cands:
                out(f'           candidatos (pais/liga/id): {cands}')
            continue

        total, hoy = count_matches(con, league_id, today)
        total_partidos += total
        out(f'{SPORT:<10} | {league_country:<22} | {league_name:<32} | '
            f'{total:>6} | {hoy:>4}')

    out('-' * 90)
    out(f'RESUMEN: {n_ligas} ligas pineadas | {total_partidos} partidos creados (total)')
    out('(read-only: no se modificó la base de datos)')
    logf.close()
    print(f'\n[done] log guardado en: {log_path}  (driver vivo intacto)')


if __name__ == '__main__':
    main()
