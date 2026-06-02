"""
run_fix_live.py
---------------
Cierra partidos varados en LIVE usando el driver activo del notebook.

Flujo:
  1. Lee tmp/driver_session.json y se conecta al driver existente
  2. Consulta DB: partidos con status=LIVE y fecha pasada
  3. Por cada liga: navega a results, carga hasta la fecha del partido
  4. Encuentra el partido, extrae score + estadísticas
  5. Actualiza DB: score, status=COMPLETED, statistic

Uso:
    cd /home/jorge/work/scraper_V2.0
    sports_env/bin/python scripts/run_fix_live.py
"""

import sys, os, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

# ── Conexión al driver activo ──────────────────────────────────────────────────
SESSION_FILE = os.path.join(ROOT, 'tmp', 'driver_session.json')

def get_driver():
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.firefox.options import Options

    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            f'No se encontró sesión en {SESSION_FILE}\n'
            'Ejecuta primero las celdas 4 y 5 del notebook main_depuracion.ipynb'
        )
    with open(SESSION_FILE) as f:
        data = json.load(f)

    session_id   = data['session_id']
    executor_url = data['executor_url']

    original_execute = WebDriver.execute
    def patched_execute(self, driver_command, params=None):
        if driver_command == 'newSession':
            return {
                'success': 0,
                'value': {'sessionId': session_id, 'capabilities': {}},
                'sessionId': session_id
            }
        return original_execute(self, driver_command, params)

    WebDriver.execute = patched_execute
    driver = WebDriver(command_executor=executor_url, options=Options())
    WebDriver.execute = original_execute
    driver.session_id = session_id

    print(f'[OK] Driver conectado — URL: {driver.current_url}')
    return driver

# ── Imports del proyecto ───────────────────────────────────────────────────────
import psycopg2
from collections import defaultdict
from selenium.webdriver.common.by import By

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from common_functions import load_json, wait_update_page, dismiss_cookies
from data_base import get_math_details_ids, update_score, update_match_status
from fix_live_matches import (
    get_pending_live_matches, find_results_url,
    load_until_date, scan_results_page, get_last_visible_date
)
from milestone4 import get_result, get_match_info, get_statistics_game, wait_load_details, retry_match

LEAGUES_INFO_PATH = os.path.join(ROOT, 'check_points', 'leagues_info.json')

# ── Actualización en DB (sin confirmación) ─────────────────────────────────────
def update_match(driver, db_match, scraped):
    match_id       = db_match['match_id']
    match_name     = db_match['name']
    home_result    = scraped['home_result']
    visitor_result = scraped['visitor_result']
    link           = scraped['link_details']

    print(f'\n  Extrayendo detalle: {match_name}')

    event_info = {'home': scraped.get('home', ''), 'visitor': scraped.get('visitor', '')}
    def _extract(drv):
        wait_load_details(drv, link)
        get_match_info(drv, event_info)
        return get_statistics_game(drv)

    statistic = '{}'
    try:
        result = retry_match(driver, link, _extract)
        if result:
            statistic = result
    except Exception as e:
        print(f'  [WARN] Sin estadísticas: {e}')

    dict_detail = get_math_details_ids(match_id)

    # Actualizar score por equipo
    for detail_id, home_flag in dict_detail.items():
        points = home_result if home_flag else visitor_result
        update_score({'match_detail_id': detail_id, 'points': points})

    # Actualizar status
    update_match_status({'status': 'COMPLETED', 'match_id': match_id})

    # Guardar estadísticas
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute("UPDATE match SET statistic = %s WHERE match_id = %s", (str(statistic), match_id))
    con.commit(); cur.close(); con.close()

    try:
        stats_count = len(eval(str(statistic)))
    except Exception:
        stats_count = 0

    print(f'  [DONE] {match_name} | {home_result}-{visitor_result} | stats: {stats_count} indicadores')
    return True


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print('=' * 60)
    print('run_fix_live.py — cerrando partidos LIVE pendientes')
    print('=' * 60)

    driver       = get_driver()
    matches      = get_pending_live_matches()
    leagues_info = load_json(LEAGUES_INFO_PATH)

    if not matches:
        print('\nSin partidos LIVE pendientes. Todo OK.')
        return

    by_league = defaultdict(list)
    for m in matches:
        by_league[(m['sport_name'], m['country_name'], m['league_name'])].append(m)

    stats = {'ok': 0, 'not_found': 0, 'error': 0}

    for (sport, country, league), league_matches in by_league.items():
        results_url = find_results_url(leagues_info, sport, country, league)

        print(f'\n{"─" * 60}')
        print(f'[{sport}] {country} — {league} ({len(league_matches)} partido/s)')

        if not results_url:
            print(f'  [WARN] URL no encontrada en leagues_info')
            stats['not_found'] += len(league_matches)
            continue

        try:
            wait_update_page(driver, results_url, 'container__heading')
            dismiss_cookies(driver)
        except Exception as e:
            print(f'  [ERROR] navegando a la página: {e}')
            stats['error'] += len(league_matches)
            continue

        oldest = min(m['match_date'] for m in league_matches)
        load_until_date(driver, oldest)
        found = scan_results_page(driver, league_matches)

        for m in league_matches:
            if m['match_id'] not in found:
                print(f'  [NOT FOUND] {m["name"]}')
                stats['not_found'] += 1
                continue
            try:
                update_match(driver, m, found[m['match_id']])
                stats['ok'] += 1
            except Exception as e:
                print(f'  [ERROR] {m["name"]}: {e}')
                stats['error'] += 1

    print(f'\n{"=" * 60}')
    print('RESUMEN:')
    print(f'  Actualizados → COMPLETED : {stats["ok"]}')
    print(f'  No encontrados           : {stats["not_found"]}')
    print(f'  Errores                  : {stats["error"]}')
    print('=' * 60)


if __name__ == '__main__':
    main()
