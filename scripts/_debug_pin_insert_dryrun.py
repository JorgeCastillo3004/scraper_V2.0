"""
_debug_pin_insert_dryrun.py — DRY-RUN (no escribe en DB)
========================================================
Para cada partido de LIGA PINEADA (vista ALL) que NO esté en la DB, muestra
EXACTAMENTE qué se insertaría con save_math_info(), pero SIN ejecutarlo.

Reusa SOLO funciones existentes (todas SELECT, read-only):
  - detección de pin: data-pinned + milestone7.get_live_result  (sin update_status)
  - data_base.get_dict_results        -> league_id por país+liga
  - data_base.get_country_id          -> country_id
  - data_base.get_season_id_by_league -> season_id
  - data_base.check_match_duplicate   -> anti-duplicado
  - common_functions.generate_uuid    -> match_id (solo para mostrar)
NO llama save_math_info (eso es la implementación real, tras aprobación).
"""
import os, sys, time
from datetime import datetime
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from driver_session import get_driver
from common_functions import load_json, wait_update_page, dismiss_cookies, generate_uuid
from milestone7 import get_live_result
from data_base import (getdb, get_country_id,
                       get_season_id_by_league, check_match_duplicate,
                       strip_phase_suffix)

SPORT = sys.argv[1] if len(sys.argv) > 1 else 'FOOTBALL'


def row_time(row):
    try:
        return row.find_element(By.XPATH, './/div[contains(@class,"event__time")]').text.strip()
    except Exception:
        return ''


def resolve_league_id(con, country, league, sport=None):
    """league_id por país+liga usando el MISMO JOIN probado de get_match_id
    (league ⋈ country). Tolera el sufijo de fase del DOM: si el match exacto
    falla, reintenta con el nombre base (sin '- Apertura/- Play Offs/...').
    Si igual no hay match, devuelve candidatos del MISMO país cuyo nombre es
    prefijo del nombre del DOM (para diagnosticar diferencias reales).

    sport (opcional, sport.name de la DB en Title Case): filtra por deporte para
    NO resolver la liga homónima de otro deporte (TURKEY 'Super Lig' básquet vs
    fútbol). Si es None -> sin filtro (comportamiento previo)."""
    cur = con.cursor()
    _sport_join = "JOIN sport ON sport.sport_id = league.sport_id" if sport else ""
    _sport_cond = "AND sport.name = %s" if sport else ""

    def _exact(name):
        params = (country, name, sport) if sport else (country, name)
        cur.execute(
            f"""SELECT league.league_id FROM league
               JOIN country ON league.country_id = country.country_id
               {_sport_join}
               WHERE country.country_name = %s AND league.league_name = %s {_sport_cond}""",
            params)
        rows = [r[0] for r in cur.fetchall()]
        return rows[0] if rows else None

    # 1) match exacto con el nombre tal cual viene del DOM
    lid = _exact(league)
    if lid:
        return lid, None
    # 2) reintento con el nombre base (recortando el sufijo de fase)
    base = strip_phase_suffix(league)
    if base != league:
        lid = _exact(base)
        if lid:
            return lid, None
    # 3) diagnóstico: liga del mismo país cuyo nombre es prefijo del DOM
    #    (dirección correcta del ILIKE: DB es prefijo del texto largo del DOM)
    cur.execute(
        """SELECT country.country_name, league.league_name, league.league_id
           FROM league JOIN country ON league.country_id = country.country_id
           WHERE country.country_name = %s AND %s ILIKE league.league_name || '%%'""",
        (country, league))
    cands = [(r[0], r[1], r[2]) for r in cur.fetchall()]
    return None, cands


def main():
    drv = get_driver()
    today = datetime.now().date()
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    url = dict_sports_url[SPORT]
    print(f'[DRY-RUN] {SPORT} vista ALL -> {url} | fecha={today}\n')

    con = getdb()

    wait_update_page(drv, url, 'container__heading')
    dismiss_cookies(drv)
    for _ in range(12):
        if drv.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-headerLeague"][data-pinned="true"]'):
            break
        time.sleep(1)

    sn = 'soccer' if SPORT == 'FOOTBALL' else SPORT.lower()
    rows = drv.find_elements(By.XPATH, f'//div[@class="sportName {sn}"]/div')

    enable_load = False
    league_name = league_country = ''
    would_insert = exists = no_league = 0

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
                    print(f'\n=== LIGA PINEADA: {league_country} / {league_name} ===')
            except Exception:
                pass
            continue

        if not enable_load:
            continue

        try:
            info = get_live_result(row)
        except Exception:
            continue
        name = info['name']
        hora = row_time(row)

        league_id, cands = resolve_league_id(con, league_country, league_name)
        if not league_id:
            no_league += 1
            print(f'  [{hora}] {name}')
            print(f'    -> LIGA NO ENCONTRADA en DB: country="{league_country}" league="{league_name}"')
            if cands:
                print(f'       candidatos (país / liga / id): {cands}')
            else:
                print(f'       (sin candidatos: la liga no está creada en DB)')
            continue

        dup = check_match_duplicate(league_id, today, name)
        if dup:
            exists += 1
            print(f'  [{hora}] {name}  -> YA EXISTE (match_id={dup}) — no se insertaría')
            continue

        would_insert += 1
        try:
            country_id = get_country_id(league_country)
        except Exception as e:
            country_id = f'<error get_country_id: {e}>'
        try:
            season_id = get_season_id_by_league(league_id)
        except Exception as e:
            season_id = f'<error get_season_id: {e}>'

        dict_match = {
            'match_id': generate_uuid(),
            'country_id': country_id,
            'end_time': '',
            'match_date': str(today),
            'name': name,
            'place': '',
            'start_time': hora,
            'league_id': league_id,
            'stadium_id': None,
            'tournament_id': None,
            'rounds': '',
            'season_id': season_id,
            'statistic': None,
            'status': 'SCHEDULED',
        }
        print(f'  [{hora}] {name}  -> SE INSERTARÍA:')
        for k, v in dict_match.items():
            print(f'        {k:12s}: {v}')

    print(f'\n{"="*60}')
    print(f'RESUMEN DRY-RUN: insertaría={would_insert} | ya existen={exists} | '
          f'liga no encontrada={no_league}')
    print('NO se tocó la base de datos. [done] driver vivo intacto.')


if __name__ == '__main__':
    main()
