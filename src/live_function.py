"""
live_function.py
================
Funciones del scraper LIVE.

Contiene SOLO las funciones que el live usa y que antes vivían en
`milestone7.py` / `milestone8.py` (esos módulos se eliminarán una vez validado
esto). Lo demás (lanzar driver, login, utilidades de página y acceso a DB) se
**importa** de `common_functions` / `data_base` — no se duplica.

Funciones movidas:
    - give_click_on_live   (antes milestone8.py)
    - get_live_result      (antes milestone7.py)
    - update_status        (antes milestone7.py)
    - get_live_match       (antes milestone7.py)
    - live_games           (antes milestone7.py)  — loop standalone, conservado
    - process_sport_live   (NUEVO: extrae el cuerpo "1 deporte por ciclo" del
                            loop original a una función reutilizable, para que
                            live_runner.py lo invoque sin reescribir lógica)
"""

import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException

# Dependencias IMPORTADAS (no se copian)
from common_functions import load_json, wait_update_page, dismiss_cookies, random_id, classify_live_status, red_box_warning
from data_base import (
    get_match_id,
    get_all_match_ids,
    get_math_details_ids,
    update_score,
    update_match_status,
)

_DB_SPORT_NAME = None
def _db_sport_name(sport_project):
    """Deporte como lo guarda la DB (sport.name, Title Case) desde el nombre de
    PROYECTO (UPPER). Filtra get_match_id por deporte para no actualizar una liga
    homónima de otro deporte (TURKEY 'Super Lig' básquet vs fútbol). None si no
    está en el mapa -> sin filtro."""
    global _DB_SPORT_NAME
    if _DB_SPORT_NAME is None:
        _DB_SPORT_NAME = {v: k for k, v in
                          load_json('check_points/sport_name_map.json').get('db_to_project', {}).items()}
    return _DB_SPORT_NAME.get(sport_project)


# ── click sección LIVE (antes milestone8.give_click_on_live) ─────────────────
def give_click_on_live(driver, sport_name, section="LIVE"):
    # CLICK ON LIVE BUTTON
    if sport_name == 'GOLF':
        section_title = "Click for player card!"
    else:
        section_title = "Click for match detail!"

    wait = WebDriverWait(driver, 10)

    # give click en el tab LIVE
    webdriver.ActionChains(driver).send_keys(Keys.HOME).perform()
    xpath_expression = f'//div[@class="filters__tab" and contains(.,"{section}")]'
    livebutton = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_expression)))
    livebutton.click()
    time.sleep(0.5)

    # FlashScore colapsa las ligas en la vista LIVE; ya no hay tabs
    # "Click for match detail!" hasta expandir. Detectamos si hay contenido live
    # por la presencia de cabeceras de liga (data-testid=wcl-headerLeague).
    # Si no hay cabeceras -> no hay partidos en vivo -> devolver False (sin crash).
    headers = driver.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-headerLeague"]')
    return len(headers) > 0


def expand_all_live_leagues(driver, max_passes=3):
    """
    Expande todas las ligas colapsadas ('display matches (N)') de la vista LIVE
    para que sus filas de partido entren al DOM. Devuelve cuántos acordeones
    abrió en total. Hace varias pasadas porque al expandir pueden aparecer más.
    """
    total = 0
    for _ in range(max_passes):
        buttons = driver.find_elements(
            By.CSS_SELECTOR,
            'button[data-testid="wcl-accordionButton"][aria-expanded="false"]')
        if not buttons:
            break
        clicked = 0
        for b in buttons:
            try:
                driver.execute_script('arguments[0].click()', b)
                clicked += 1
            except Exception:
                continue
        total += clicked
        if clicked:
            time.sleep(1)
        else:
            break
    return total


# ── lectura de un partido (antes milestone7.get_live_result) ─────────────────
def get_live_result(row):
    try:
        # work for: FOOTBALL
        home_participant = row.find_element(
            By.XPATH, './/*[contains(@class, "event__homeParticipant")]').text.strip()
        away_participant = row.find_element(
            By.XPATH, './/*[contains(@class, "event__awayParticipant")]').text.strip()
    except Exception:
        # work for: BASKETBALL, ...
        home_participant = row.find_element(
            By.XPATH, './/*[contains(@class, "event__participant--home")]').text.strip()
        away_participant = row.find_element(
            By.XPATH, './/*[contains(@class, "event__participant--away")]').text.strip()

    home_result = row.find_element(
        By.XPATH, './/*[contains(@class, "event__score--home")]').text.strip()
    away_result = row.find_element(
        By.XPATH, './/*[contains(@class, "event__score--away")]').text.strip()

    match_id = random_id()
    result_dict = {
        'match_id': match_id, 'match_date': '', 'start_time': '', 'end_time': '',
        'name': home_participant + '~' + away_participant,
        'home': home_participant, 'visitor': away_participant,
        'home_result': home_result, 'visitor_result': away_result, 'place': '',
    }
    return result_dict


# ── status del partido (antes milestone7.update_status) ──────────────────────
def update_status(row, max_count=10):
    count = 0
    match_status = None
    while count < max_count:
        try:
            match_status = row.find_element(By.XPATH, './/div[@class="event__stage"]').text
            count = max_count
        except Exception:
            time.sleep(1)
            count += 1
    # 'COMPLETED' | 'LIVE' | etiqueta NO-live ('POSTPONED', ...). Antes 'no es Finished'
    # => LIVE, marcando LIVE a partidos aplazados/cancelados.
    return classify_live_status(match_status)


# ── lista de partidos live de un deporte (antes milestone7.get_live_match) ───
def get_live_match(driver, sport_name='FOOTBALL', max_count=10):
    if sport_name == 'FOOTBALL':
        sport_name = 'soccer'
    else:
        sport_name = sport_name.lower()

    rows = driver.find_elements(By.XPATH, '//div[@class="sportName {}"]/div'.format(sport_name))
    enable_load = False
    list_match = []
    league_name = ''
    league_country = ''
    for index, row in enumerate(rows):
        count = 0
        while count < max_count:
            try:
                try:
                    title = row.find_element(
                        By.XPATH, './/span[contains(@class, "headerLeague__title-text")]').text.strip()
                    enable_load = False
                    league_name = row.find_element(
                        By.XPATH, './/a[@class="headerLeague__title"]').text
                    league_country = row.find_element(
                        By.XPATH, './/span[@class="headerLeague__category-text"]').text
                    # Antes solo se leían ligas pinneadas (data-pinned=true).
                    # Ahora se expanden todas (expand_all_live_leagues) y se leen
                    # TODAS las ligas live, así que habilitamos siempre la carga.
                    enable_load = True
                    count = max_count
                except Exception:
                    if enable_load:
                        game_results = get_live_result(row)
                        game_results['league_name'] = league_name
                        game_results['league_country'] = league_country
                        game_results['status'] = update_status(row)
                        list_match.append(game_results)
                    count = max_count
            except Exception:
                count += 1
    return list_match


# ── procesar 1 deporte en 1 ciclo ────────────────────────────────────────────
# Extrae el cuerpo del loop original (milestone7.live_games) a una función
# reutilizable. Imprime los 5 campos (status, home, score home, visitante,
# score visitante), actualiza score/status en DB, y DEVUELVE la lista de
# partidos encontrados (para resúmenes / detección de problemas).
def process_sport_live(driver, sport_name, current_date=None, dict_sports_url=None,
                       save_screenshot=None):
    if current_date is None:
        current_date = datetime.now().date()
    if dict_sports_url is None:
        dict_sports_url = load_json('check_points/sports_url_m2.json')
    _shot = save_screenshot if callable(save_screenshot) else (lambda d, l: None)

    wait_update_page(driver, dict_sports_url[sport_name], "container__heading")
    dismiss_cookies(driver)
    _shot(driver, f'live_{sport_name}')

    live_games_found = give_click_on_live(driver, sport_name)
    if not live_games_found:
        return []

    # FlashScore colapsa las ligas en LIVE: expandir todas antes de leer.
    n_expanded = expand_all_live_leagues(driver)
    if n_expanded:
        print(f'[{sport_name}] expandidas {n_expanded} ligas')

    list_live_match = get_live_match(driver, sport_name=sport_name)
    print(f'[{sport_name}] {len(list_live_match)} partidos en vivo')
    _shot(driver, f'live_{sport_name}_matches')

    for match_info in list_live_match:
        try:
            # Req 4: status, home, score home, visitante, score visitante
            print(f'  [{match_info["status"]}] {match_info["home"]} '
                  f'{match_info["home_result"]} - {match_info["visitor_result"]} '
                  f'{match_info["visitor"]}')
            _sport_db = _db_sport_name(sport_name)
            if _sport_db is None:
                # NUNCA debería pasar (sport_name_map.json cubre los 9 deportes).
                red_box_warning(
                    f'LIVE: _db_sport_name=None para sport_name={sport_name!r}',
                    ['NO se resuelve el partido SIN deporte (evita colision cross-deporte).',
                     f"liga={match_info.get('league_name')!r}  match={match_info.get('name')!r}",
                     'Se SALTEA este partido. El proceso CONTINUA. Revisar sport_name_map.json.'])
                continue
            # WORLD CUP: el mismo partido vive en las 7 ligas de confederación →
            # actualizar TODAS las copias. Resto: comportamiento normal (1 copia).
            _lname = match_info.get('league_name') or ''
            if ('world cup' in _lname.lower()) or ('world championship' in _lname.lower()):
                match_ids = get_all_match_ids('World Cup', current_date, match_info['name'], _sport_db)
            else:
                _one = get_match_id(match_info['league_country'], _lname, current_date,
                                    match_info['name'], sport=_sport_db)
                match_ids = [_one] if _one else []
            _status = match_info['status']
            if match_ids and _status not in ('LIVE', 'COMPLETED'):
                # Postponed/Cancelled/etc.: en la BD el estado queda 'SCHEDULED'.
                for _mid in match_ids:
                    update_match_status({'match_id': _mid, 'status': 'SCHEDULED'})
                print(f'  [NO-LIVE] {match_info["name"]}: FlashScore={_status} -> BD=SCHEDULED ({len(match_ids)})')
            elif match_ids:
                for _mid in match_ids:
                    dict_match_detail_id = get_math_details_ids(_mid)
                    for match_detail_id, home_flag in dict_match_detail_id.items():
                        if home_flag:
                            update_score({'match_detail_id': match_detail_id,
                                          'points': match_info['home_result']})
                        else:
                            update_score({'match_detail_id': match_detail_id,
                                          'points': match_info['visitor_result']})
                    update_match_status({'match_id': _mid, 'status': _status})
        except Exception as e:
            print(f'  [WARN] {match_info.get("name", "?")}: {e}')
            continue

    return list_live_match


# ── loop standalone (antes milestone7.live_games), conservado ────────────────
# Reescrito para delegar en process_sport_live y no duplicar el cuerpo.
def live_games(driver, list_sports, interval=60, check_control=None, save_screenshot=None):
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    _shot = save_screenshot if callable(save_screenshot) else (lambda d, l: None)

    while True:
        current_date = datetime.now().date()
        start_time = time.time()
        for sport_name in list_sports:
            try:
                process_sport_live(driver, sport_name, current_date,
                                   dict_sports_url=dict_sports_url,
                                   save_screenshot=save_screenshot)
            except (InvalidSessionIdException, WebDriverException):
                _shot(driver, f'error_{sport_name}')
                raise
            except Exception as e:
                _shot(driver, f'error_{sport_name}')
                print(f'[WARN] {sport_name}: {type(e).__name__}: {e}')
                continue

        elapsed_time = time.time() - start_time
        _check = check_control if callable(check_control) else (lambda d=None: None)
        remaining = max(0, interval - elapsed_time)
        waited = 0
        while waited < remaining:
            slice_ = min(2, remaining - waited)
            time.sleep(slice_)
            waited += slice_
            _check(driver)
