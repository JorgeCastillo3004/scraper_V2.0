from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException,
    StaleElementReferenceException, WebDriverException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import time
import psycopg2
import shutil

# Excepciones que indican problema de carga — recuperables con reload
RETRY_EXCEPTIONS = (TimeoutException, StaleElementReferenceException,
                    WebDriverException, NoSuchElementException)

MATCH_MAX_ATTEMPTS           = 3   # intentos por match
LEAGUE_MAX_RETRIES           = 2   # reintentos ante RETRY_EXCEPTIONS en get_complete_match_info
LEAGUE_NAV_RETRIES           = 3   # reintentos para navegación + creación de rondas
RETRY_BASE_DELAY             = 5   # segundos base (se multiplica por intento)
INIT_MAX_RETRIES             = 3   # reintentos para inicialización (DB/archivo al arrancar)
LEAGUE_MAX_CONSECUTIVE_FAILS = 4   # ligas fallidas consecutivas → warning de driver roto

from common_functions import *
from data_base import get_match_by_league_id, get_stadium_id, check_stadium, get_match_ready, check_match_duplicate, get_team_id_pilot, get_team_id_db, check_player_duplicates, check_player_duplicates_id, check_team_duplicates, check_team_duplicates_id, check_team_season_duplicates, save_player_info, save_team_info, save_team_players_entity, save_league_team_entity, save_math_info, save_details_math_info, save_score_info, save_stadium_in_db, get_dict_sport_id, claim_league, release_league, cleanup_stale_leagues, update_league_checkpoint, get_league_checkpoint, get_math_details_ids, get_score_by_match_detail_id, get_league_match_team_count
from milestone6 import *


def retry_match(driver, url, fn, max_attempts=MATCH_MAX_ATTEMPTS, base_delay=RETRY_BASE_DELAY):
    """
    Ejecuta fn(driver) con reintentos ante errores de carga.
    - Intento 1: sin delay (no penaliza el caso exitoso).
    - Intentos 2+: recarga la URL del match + backoff (base_delay * intento).
    - Si todos fallan: retorna None (el match se salta y se registra en issues).
    El driver nunca se cierra.
    """
    for attempt in range(max_attempts):
        try:
            if attempt > 0:
                delay = base_delay * attempt
                print(f'[WARN] Reintento {attempt}/{max_attempts - 1} — espera {delay}s — recargando URL')
                time.sleep(delay)
                driver.get(url)
                dismiss_cookies(driver)
            return fn(driver)
        except RETRY_EXCEPTIONS as e:
            if attempt == max_attempts - 1:
                print(f'[ERROR] Match fallido tras {max_attempts} intentos: {e}')
                return None
    return None


local_time_naive = datetime.now()
utc_time_naive = datetime.utcnow()
time_difference_naive = utc_time_naive - local_time_naive

#% common funcion
def update_league_stats_json(sport_name, league_id, checkpoint_path='check_points/leagues_info.json'):
    """Query DB and update matches/teams count for the given league in leagues_info.json."""
    try:
        match_count, team_count = get_league_match_team_count(league_id)
        data = load_check_point(checkpoint_path)
        for lg_key, lg_info in data.get(sport_name, {}).items():
            if lg_info.get('league_id') == league_id:
                lg_info['matches'] = match_count
                lg_info['teams'] = team_count
                save_check_point(checkpoint_path, data)
                print(f"[INFO] leagues_info.json updated: {lg_key} matches={match_count} teams={team_count}")
                return
        print(f"[WARN] update_league_stats_json: no entry found for league_id={league_id} in {sport_name}")
    except Exception as e:
        print(f"[WARN] update_league_stats_json failed: {e}")

def complete_info(league_info, league_name, sport_name, dict_sport_id):
    league_info['league_name'] = league_name
    league_info['sport_name'] = sport_name
    league_info['sport_id'] = dict_sport_id[sport_name]

def get_time_date_format(date, section=None):
    year_ = datetime.now().year
    try:
        cleaned_text = re.findall(r'\d+\.\d+\.\d+\s+\d+\:\d+', date)[0]
        dt_object = datetime.strptime(cleaned_text, '%d.%m.%Y %H:%M')
    except:
        try:
            cleaned_text = re.findall(r'\d+\.\d+\.\s+\d+\:\d+', date)[0]
            dt_object = datetime.strptime(cleaned_text, '%d.%m. %H:%M')
            dt_object = dt_object.replace(year=year_)
        except:
            cleaned_text = ''.join(re.findall(r'(\d+\.\d+\.)\-\d+\.\d+\.(\d+)', date)[0])
            dt_object = datetime.strptime(cleaned_text, '%d.%m.%Y')
    dt_object = dt_object + time_difference_naive
    # Extract date and time
    date = dt_object.date()
    time = dt_object.time()
    return date, time

def get_result(row, country_id, section = 'results'):
    home_xpath_expression = ".//div[contains(@class, 'homeParticipant')]"
    away_xpath_expression = ".//div[contains(@class, 'awayParticipant')]"
    match_date = row.find_element(By.CLASS_NAME, 'event__time').text    
    try:
        # home_participant = row.find_element(By.CLASS_NAME, 'event__participant.event__participant--home.fontExtraBold').text        
        home_participant = row.find_element(By.XPATH, home_xpath_expression).text
    except:
        home_participant = row.find_element(By.CLASS_NAME, 'event__participant.event__participant--home').text
    try:
        away_participant = row.find_element(By.XPATH, away_xpath_expression).text
        # away_participant = row.find_element(By.CLASS_NAME, 'event__participant.event__participant--away.fontExtraBold').text
    except:
        away_participant = row.find_element(By.CLASS_NAME, 'event__participant.event__participant--away').text

    if section == 'results':
        home_result = row.find_element(By.CLASS_NAME, 'event__score.event__score--home').text
        away_result = row.find_element(By.CLASS_NAME, 'event__score.event__score--away').text
    else:
        home_result = ''
        away_result = ''
    html_block = row.get_attribute('outerHTML')
    link_id = re.findall(r'id="[a-z]_\d_(.+?)\"', html_block)[0]
    url_details = "https://www.flashscore.com/match/{}/#/match-summary/match-summary".format(link_id)
    match_id = generate_uuid()
    result_dict = {'match_id':match_id,'match_date':match_date,'start_time':'', 'end_time':'',\
                    'name':home_participant + '~' + away_participant,'home':home_participant,'visitor':away_participant,\
                    'home_result':home_result,  'visitor_result':away_result, 'link_details':url_details,'place':'',
                    'country_id':country_id}
    return result_dict

def get_unique_key(id_section_new, list_keys):
    id_section_new = id_section_new.replace(' ','_').replace('/','*-*')
    # Sections with the same name.
    if id_section_new in list_keys:
        id_section_base = id_section_new
        count_sub_rounds = 1
        id_section_new = id_section_base +'_' +str(count_sub_rounds)
        while id_section_new in list_keys:
            count_sub_rounds += 1
            id_section_new = id_section_base +'_' +str(count_sub_rounds)
    return id_section_new

def extract_info_results_old(driver, start_index, results_block, section_name, country_league, list_rounds):
    global count_sub_section, event_number, current_id_section, dict_rounds, new_section_name
    dict_rounds = {}
    round_enable = False
    for processed_index, row in enumerate(results_block[start_index:]):     
        try:
            # SECTION MAIN TITLE, ONLY FIND TITLE, IT IS NOT USED
            HTML = row.get_attribute('outerHTML')
            title_section = re.findall(r'icon--flag.event__title fl_\d+', HTML)[0].replace(' ', '.')
        except:
            try:
                # SECTION TO FIND MATCH INFO, EXTRACT DETAILS               
                result = get_result(row, section_name = section_name)
                if round_enable:                    
                    dict_rounds[current_round_name][event_number] = result
                    event_number += 1
            except:
                # SECTION TO FIND ROUND NAME.
                try:
                    round_name = row.find_element(By.CLASS_NAME, 'event__title--name').text.replace(' ','_').replace('/','*-*')

                except:
                    round_name = get_unique_key(row.text, dict_rounds.keys())
                # SECTION TO CHECK ROUND SAVED PREVIOUSLY
                round_name = '_'.join(round_name.split())
                print("round_name: ", round_name)               
                if round_name in list_rounds:
                    round_enable = False
                else:
                    print("New round: ", round_name)
                    round_enable = True             
                # IF round dictionary IS FILLED PROCEED TO SAVE DICT FOR PROCESSING IN THE NEXT STAGE
                if len (dict_rounds)!= 0 and len(dict_rounds[current_round_name]) != 0:                 
                    list_rounds.append(current_round_name)                  
                    file_name = 'check_points/{}/{}/{}.json'.format(section_name, country_league, current_round_name)
                    folder_name = 'check_points/{}/{}/'.format(section_name, country_league)                    
                    print(file_name)
                    if not os.path.exists(folder_name):
                        os.mkdir(folder_name)
                    save_check_point(file_name, dict_rounds[current_round_name])
                    webdriver.ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
                # RESTAR NEW DICTIONARY AND UPDATE CURRENT NAMES
                current_round_name = round_name
                dict_rounds[current_round_name] = {}
                count_sub_section += 1
                event_number = 0
    print(round_enable)
    return start_index + processed_index, round_enable

def extract_info_results(driver, start_index, results_block, section_name, country_league, country_id):
     # list to save round name, index_start index_end
    dict_rounds_index = {}
    all_list_results = []
    count = 0
    #########################################################
    #               LOOP OVER ALL MATCH                     #
    #########################################################
    for processed_index, result in enumerate(results_block[start_index:]):
        HTML = result.get_attribute('outerHTML')
        if 'event__round event__round--static' in HTML or 'event__header' in HTML: # TAKE ROUND NAME            
            if count == 1:
                list_index[1] = processed_index
                dict_rounds_index[round_name] = list_index
                count = 0
            if count == 0:
                list_index = [0, 0]
                round_name = get_unique_key(result.text, dict_rounds_index.keys())
                list_index[0] = processed_index + 1
                if not 'event__header' in HTML:
                    count = 1
        if 'Click for match detail!' in HTML or 'Click for details!' in HTML: # EXTRACT MATCH INFO
            result = get_result(result, country_id, section = section_name)
            all_list_results.append(result)
        else:
            all_list_results.append('')

    #######################################################################
    #  SAVE FILES BY ROUNDS AND ORGANIZE THEM ACCORDING TO THE MATCH      #
    #######################################################################
    if len(dict_rounds_index) != 0:
        for round_name, index_star_end in dict_rounds_index.items():            
            # CREATE FOLDER AND FILE NAME.
            file_name = 'check_points/{}/{}/{}.json'.format(section_name, country_league, round_name.replace('*', '').replace('-', '')) 
            folder_name = 'check_points/{}/{}/'.format(section_name, country_league)        
            if not os.path.exists(folder_name):
                os.mkdir(folder_name)
            # CREATE DICT WITH ALL ENVENTS INFO.
            event_number = 0
            dict_round = {}
            for index in range(index_star_end[0], index_star_end[1]):                   
                if all_list_results[index] !='':
                    dict_round[event_number] = all_list_results[index]
                    event_number += 1
            # SAVE ROUND DICT
            save_check_point(file_name, dict_round)             
            envent_number = 0            
    #######################################################################
    #                       CASE 2 UNIQUE ROUND                           #
    ####################################################################### 
    else:
        event_number = 0
        dict_round = {}
        for index, match_info in enumerate(all_list_results):
            if match_info != '':
                dict_round[index] = match_info

        # CREATE FOLDER AND FILE NAME.
        file_name = 'check_points/{}/{}/{}.json'.format(section_name, country_league, 'UNIQUE')
        folder_name = 'check_points/{}/{}/'.format(section_name, country_league)        
        if not os.path.exists(folder_name):
            os.mkdir(folder_name)
        
        # SAVE ROUND DICT        
        save_check_point(file_name, dict_round)

    return start_index + processed_index

def click_show_more_rounds(driver, current_results, section_name):
    wait = WebDriverWait(driver, 10)
    webdriver.ActionChains(driver).send_keys(Keys.END).perform()
    time.sleep(0.3)
    webdriver.ActionChains(driver).send_keys(Keys.PAGE_UP).perform()
    time.sleep(0.3)
    webdriver.ActionChains(driver).send_keys(Keys.PAGE_UP).perform()
    time.sleep(1.5)
    
    show_more_list = driver.find_elements(By.XPATH, "//*[contains(.,'Show more matches') and (self::button or self::a)]")
    old_len = len(current_results)
    xpath_expression = '//div[contains(@class,"leagues--static event--leagues")]/div'
    max_try = 0
    if len(show_more_list) != 0:
        driver.execute_script("arguments[0].scrollIntoView(true);", show_more_list[0])
        driver.execute_script("arguments[0].click();", show_more_list[0])
        new_len = old_len
        while new_len == old_len and max_try < 10:
            time.sleep(0.3)
            new_len = len(driver.find_elements(By.XPATH, xpath_expression))
            max_try += 1
        return True
    else:
        return False

def confirm_results(driver, section_name, max_count=10):
    wait = WebDriverWait(driver, 10)
    xpath_expression = f'//div[contains(@class,"leagues--static event--leagues")]/div'
    
    for attempt in range(max_count):
        try:
            if driver.find_elements(By.ID, 'no-match-found'):
                return []
            
            # Case 3: results found
            results_block = wait.until(
                EC.presence_of_all_elements_located((By.XPATH, xpath_expression))
            )
            if results_block:
                return results_block

        except TimeoutException:
            pass  # wait more
        
        time.sleep(0.3)
    
    return []

def navigate_through_rounds(driver, league_info, section_name = 'results'):
    country_league = league_info['league_name']
    country_id = league_info['country_id']

    global count_sub_section, event_number
    xpath_expression = '//div[contains(@class,"leagues--static event--leagues")]/div'
    last_procesed_index = 0
    print(f"[RONDAS] Iniciando creación de rondas: {country_league}")
    current_results = confirm_results(driver, section_name, max_count = 5)
    count_sub_section = 0
    event_number = 0
    while last_procesed_index < len(current_results):
        more_rounds_loaded = False
        last_procesed_index = extract_info_results(driver, last_procesed_index,
                             current_results, section_name, country_league, country_id)
        click_more_enable = True
        if click_more_enable:
            more_rounds_loaded = click_show_more_rounds(driver, current_results, section_name)
        if more_rounds_loaded:
            current_results = driver.find_elements(By.XPATH, xpath_expression)
        last_procesed_index += 1

def get_match_info(driver, event_info):
    # Extract details about matchs
    # match_country = driver.find_element(By.XPATH, '//span[@class="tournamentHeader__country"]').text.split(":")[0]
    event_info['match_country'] = ''#match_country 
    match_info_elements = driver.find_elements(By.XPATH, '//div[@class="matchInfoData"]/div')

    # GET MATCH DATE COMPLETE.
    event_info['match_date'] = driver.find_element(By.CLASS_NAME, 'duelParticipant__startTime').text

    for element in match_info_elements:
        print(element.text)
        field_name = element.find_element(By.CLASS_NAME, 'matchInfoItem__name').text.replace(':','')
        field_value = element.find_element(By.CLASS_NAME, 'matchInfoItem__value').text
        event_info[field_name] = field_value
    return event_info

def create_stadium(dict_country_league_season, event_info, league_info, team_id_home):
    sport_name = league_info['sport_name']
    league_name = league_info['league_name']
    try:
        stadium_id = dict_country_league_season[event_info['home']].get('stadium_id', '')
        if not stadium_id:
            raise KeyError
        event_info['stadium_id'] = stadium_id
    except:
        event_info['stadium_id'] = generate_uuid()                  

        if 'CAPACITY' in list(event_info.keys()):
            capacity = int(''.join(event_info['CAPACITY'].split()))
        else:
            capacity = 0

        if 'VENUE' in list(event_info.keys()):
            name_stadium = event_info['VENUE']
        else:
            name_stadium = ''

        dict_stadium = {'stadium_id':event_info['stadium_id'],'country':event_info['match_country'],\
                        'capacity':capacity,'desc_i18n':'', 'name':name_stadium, 'photo':''}
        print_section("STADIUM INFO")
        print(dict_stadium)
        if event_info['home'] not in dict_country_league_season:
            dict_country_league_season[event_info['home']] = {'team_id': team_id_home, 'team_url': '', 'stadium_id': ''}
        dict_country_league_season[event_info['home']]['stadium_id'] = event_info['stadium_id']
        json_name = 'check_points/leagues_season/{}/{}.json'.format(sport_name, league_name)
        save_check_point(json_name, dict_country_league_season)
        save_stadium_in_db(dict_stadium)

def _complete_match_if_partial(event_info, dict_home, dict_visitor, section):
    """
    Verifica si un match que ya existe en DB tiene sus registros de
    match_detail y score_entity completos. Si faltan, los crea.

    Escenario típico: ejecución anterior insertó el match (save_math_info)
    pero fue interrumpida antes de guardar match_detail o score_entity,
    y el checkpoint no se actualizó, por lo que el match se vuelve a intentar.

    Estructura esperada por match:
      - 2 registros en match_detail  (home=True y home=False)
      - 1 registro en score_entity   por cada match_detail
    """
    match_id         = event_info['match_id']
    existing_details = get_math_details_ids(match_id)  # {match_detail_id: home_flag}

    home_detail_id    = next((mid for mid, h in existing_details.items() if h),     None)
    visitor_detail_id = next((mid for mid, h in existing_details.items() if not h), None)

    print(f"  [CHECK] match_detail encontrados: {len(existing_details)}/2")

    # Ajustar puntos para fixtures (mismo criterio que match_creation_save)
    if section != "results":
        dict_home['points']    = -1
        dict_visitor['points'] = -1

    for label, d, existing_detail_id in [
        ('home',    dict_home,    home_detail_id),
        ('visitor', dict_visitor, visitor_detail_id),
    ]:
        if existing_detail_id is None:
            # Falta el match_detail completo → crear match_detail + score_entity
            save_details_math_info(d)
            save_score_info(d)
            print(f"  [FIX ] match_detail + score_entity creados ({label}): {event_info['name']}")
        else:
            # match_detail existe → verificar si tiene score_entity
            score = get_score_by_match_detail_id(existing_detail_id)
            if score is None:
                # Falta solo el score_entity → usar el match_detail_id existente
                d['match_detail_id'] = existing_detail_id
                save_score_info(d)
                print(f"  [FIX ] score_entity creado ({label}, match_detail existente): {event_info['name']}")
            else:
                print(f"  [OK  ] {label}: completo (match_detail + score_entity)")


def match_creation_save(event_info, team_id_home, team_id_visitor, section):
    match_detail_id = generate_uuid()
    score_id = generate_uuid()
    dict_home = {'match_detail_id':match_detail_id, 'home':True, 'visitor':False, 'match_id':event_info['match_id'],\
                'team_id':team_id_home, 'points':event_info['home_result'], 'score_id':score_id}
    match_detail_id = generate_uuid()
    score_id = generate_uuid()
    dict_visitor = {'match_detail_id':match_detail_id, 'home':False, 'visitor':True, 'match_id':event_info['match_id'],\
                'team_id':team_id_visitor, 'points':event_info['visitor_result'], 'score_id':score_id}

    # USED FOR FILES NOT COMPLETELY PROCESSED
    match_created = get_match_ready(event_info['match_id'])             
    
    # CHECK IF MATCH WAS CREATED PREVIOUSLY
    match_duplicate = check_match_duplicate(event_info['league_id'], event_info['match_date'], event_info['name'])
    if len(match_created) != 0:
        print(f"[SKIP] Match ya existe en DB (match_id={event_info['match_id']}): {event_info['name']}")
        _complete_match_if_partial(event_info, dict_home, dict_visitor, section)
        return
    if len(match_duplicate) != 0:
        print(f"[DUP] Match duplicado: {event_info['name']}")
    if len(match_created) == 0 and len(match_duplicate) == 0:
        
        if section =="results":
            # SET EVENT STATE
            event_info['status'] = 'COMPLETED'
        elif section =="fixtures":
            # SET EVENT STATE
            event_info['status'] = 'SCHEDULED'
        save_math_info(event_info)
        save_details_math_info(dict_home)
        save_details_math_info(dict_visitor)

        if section !="results":
            dict_home['points'] = -1
            dict_visitor['points'] = -1
        save_score_info(dict_home)
        save_score_info(dict_visitor)
        # verificar que realmente se creó en la DB
        match_verified = get_match_ready(event_info['match_id'])
        if match_verified:
            print(f"[OK ] Match creado y verificado: {event_info['name']}")
        else:
            print(f"[WARN] Match NO encontrado en DB tras INSERT: {event_info['name']}")

_DETAIL_PAGE_XPATH = (
    '//div[@class="matchInfoData"] | '
    '//div[contains(@class,"duelParticipant")] | '
    '//div[contains(@class,"matchInfo")]'
)

def wait_load_details(driver, url_details):
    wait = WebDriverWait(driver, 10)
    block_info_before = driver.find_elements(By.XPATH, _DETAIL_PAGE_XPATH)
    driver.get(url_details)
    dismiss_cookies(driver)
    try:
        wait.until(EC.visibility_of_element_located((By.XPATH, _DETAIL_PAGE_XPATH)))
        return True
    except Exception:
        if block_info_before:
            try:
                wait.until(EC.staleness_of(block_info_before[0]))
            except Exception:
                pass
        return False

_JS_STATS = """
    return Array.from(document.querySelectorAll('[data-testid="wcl-statistics"]')).map(el => ({
        category: (el.querySelector('[data-testid="wcl-statistics-category"]') || {}).textContent || '',
        home: (el.querySelector('[class*="homeValue"]') || {}).textContent || '',
        away: (el.querySelector('[class*="awayValue"]') || {}).textContent || ''
    }));
"""


def _stats_con_texto(items):
    return [it for it in items if it.get('category') and
            ((it.get('home') or '').strip() or (it.get('away') or '').strip())]


def _intentar_leer_stats(driver, max_wait=8):
    """Click en 'Stats' y espera (hasta max_wait s) a que aparezca TEXTO.
    Retorna:
      None  -> no hay pestaña de estadísticas (genuino, no reintentar)
      []    -> hay pestaña pero no cargó texto (timing -> conviene refrescar)
      [..]  -> indicadores con valores
    """
    button_stats = driver.find_elements(By.XPATH, '//button[contains(.,"Stats")]')
    if not button_stats:
        return None
    driver.execute_script("arguments[0].click();", button_stats[0])
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, '//div[@data-testid="wcl-statistics"]')))
    except Exception:
        return []
    deadline = time.time() + max_wait
    raw = []
    prev_count = -1
    while time.time() < deadline:
        time.sleep(0.5)
        cur = driver.execute_script(_JS_STATS)
        raw = cur
        count = len(_stats_con_texto(cur))
        if count > 0 and count == prev_count:   # estabilizó
            break
        prev_count = count
    return _stats_con_texto(raw)


def get_statistics_game(driver):
    statistics_info = {}
    raw = _intentar_leer_stats(driver)
    if raw is None:
        return str(statistics_info)            # sin pestaña de stats (genuino)
    if not raw:
        # Recuperación barata: refrescar la página UNA vez antes de recurrir al
        # reload completo de la URL (retry_match). Evita esperas largas por match.
        try:
            driver.refresh()
            dismiss_cookies(driver)
        except Exception:
            pass
        raw = _intentar_leer_stats(driver)
        if raw is None:
            return str(statistics_info)
    if not raw:
        # Último recurso: que retry_match recargue la URL completa y reintente.
        raise TimeoutException('Estadisticas vacias tras refresh — recargar URL')

    for item in raw:
        if item.get('category'):
            statistics_info[item['category']] = {'home': item['home'], 'away': item['away']}
    return str(statistics_info)

def get_links_participants(driver):
    # main_m2(driver)
    home_links, away_links = [], []
    block_participants = driver.find_element(By.CLASS_NAME,'duelParticipant')
    block_participants.text
    # //*[contains(@class, 'home')]

    home_participant = block_participants.find_element(By.XPATH, './/div[contains(@class, "home")]')    
    participant_links = home_participant.find_elements(By.XPATH, './/a[@class="participant__participantLink"]')

    for link in participant_links:      
        home_links.append(link.get_attribute('href'))

    away_participant = block_participants.find_element(By.XPATH, './/div[contains(@class, "away")]')    
    participant_links = away_participant.find_elements(By.XPATH, './/a[@class="participant__participantLink"]')

    for link in participant_links:
        away_links.append(link.get_attribute('href'))

    return home_links, away_links

def save_participants_info(driver, player_links, sport_id, league_id, season_id, dict_players_ready):
    
    if len(player_links)==1:
        wait_update_page(driver, player_links[0], 'container__heading')
        player_dict = get_player_data_tennis(driver)        
        player_dict['season_id'] = season_id        
        player_dict['team_id'] = player_dict['player_id']
        player_dict['team_country'] = player_dict['player_country']
        player_dict['team_desc'] = ''
        player_dict['team_logo'] = player_dict['player_photo']
        player_dict['team_name'] = player_dict['player_name']
        player_dict['sport_id'] = sport_id
        player_dict['instance_id'] = generate_uuid()
        player_dict['player_meta'] = ''
        player_dict['team_meta'] = ''
        player_dict['team_position'] = 0
        player_dict['league_id'] = league_id
        print("Save player info in database")

        team_name = player_dict['player_name']
        print("Save player info:")
        if not team_name in list((dict_players_ready.keys() ) ):            
            dict_players_ready[team_name] = {'team_id':player_dict['team_id']}
        player_list = check_player_duplicates(player_dict['player_country'], player_dict['player_name'], player_dict['player_dob'])
                
        if len(player_list) == 0:
            save_player_info(player_dict) # player
        save_team_info(player_dict) # team
        save_team_players_entity(player_dict) # team_players_entity             
        save_league_team_entity(player_dict) # league_team
        if len(player_list) != 0:
            print("PLAYER PREVIOUSLY CREATED ")
                

    if len(player_links)!=1:
        team_name = []
        for player_link in player_links:

            wait_update_page(driver, player_link, 'container__heading')
            player_dict = get_player_data_tennis(driver)
            player_dict['season_id'] = season_id            
            player_dict['team_country'] = player_dict['player_country']
            player_dict['team_desc'] = ''
            player_dict['team_logo'] = player_dict['player_photo']          
            player_dict['sport_id'] = sport_id
            player_dict['instance_id'] = generate_uuid()
            player_dict['player_meta'] = ''
            player_dict['team_meta'] = ''
            player_dict['team_position'] = 0
            player_dict['league_id'] = league_id
            print("Save player info in database")
            
            team_name.append(player_dict['player_name'])
            name_ = player_dict['player_name']
            if not name_ in list((dict_players_ready.keys() ) ):
                dict_players_ready[name_] = {'team_id':player_dict['team_id']}
                save_player_info(player_dict) # player                  

        team_name = '-' .join(team_name)
        player_dict['team_id'] = generate_uuid()
        dict_players_ready[team_name] = {'team_id':player_dict['team_id']}
        if not team_name in list((dict_players_ready.keys() ) ):
            save_team_info(player_dict)                 # team
            save_league_team_entity(player_dict)        # league_team
            save_team_players_entity(player_dict)       # team_players_entity
            
    return dict_players_ready, team_name
#             save_check_point('check_points/players_ready.json', dict_players_ready)

def get_complete_match_info(driver, league_info, dict_country_league_season,
                            checkpoint_round, checkpoint_match,
                            section='results'):
    league_name = league_info['league_name']
    sport_name  = league_info['sport_name']
    league_id   = league_info['league_id']
    season_id   = league_info['season_id']

    skip_round  = bool(checkpoint_round)
    skip_match  = bool(checkpoint_match)
    checkpoint_match_found = not bool(checkpoint_match)  # si no hay checkpoint, ya "encontrado"

    match_issues  = load_check_point('check_points/issues/issues_match.json')
    league_folder = 'check_points/{}/{}/'.format(section, league_name)
    round_files   = sorted(os.listdir(league_folder)) if os.path.exists(league_folder) else []

    league_fully_processed = True

    for round_file in round_files:
        if skip_round:
            if round_file != checkpoint_round:
                continue
            skip_round = False
        else:
            # Rounds posteriores al checkpoint: procesar todos los matches sin excepción
            skip_match = False

        file_path  = os.path.join(league_folder, round_file)
        round_info = load_json(file_path)

        for match_key, event_info in round_info.items():
            if skip_match:
                if event_info['name'] != checkpoint_match:
                    continue
                # Match del checkpoint encontrado — marcarlo y saltarlo
                # (ya fue procesado y guardado antes de la interrupción)
                skip_match             = False
                checkpoint_match_found = True
                continue  # no re-procesar

            url_details = event_info['link_details']
            print(f"[INFO] Cargando detalles: {event_info['name']}")

            # ── NIVEL B: retry por match ──────────────────────────────
            def _extract(driver):
                wait_load_details(driver, url_details)
                info = get_match_info(driver, event_info)
                info['statistic'] = get_statistics_game(driver)
                print(info)
                return info

            result = retry_match(driver, url_details, _extract)

            if result is None:
                # Todos los intentos fallaron → registrar y saltar match
                match_issues[event_info.get('name', url_details)] = {
                    'league_name': league_name,
                    'league_id':   league_id,
                    'season_id':   season_id,
                    'url':         url_details,
                    'round':       round_file,
                    'timestamp':   datetime.now().isoformat(),
                }
                save_check_point('check_points/issues/issues_match.json', match_issues)
                # Log de texto para revisión posterior
                os.makedirs('logs/failed_matches', exist_ok=True)
                with open('logs/failed_matches/failed_matches.log', 'a', encoding='utf-8') as _flog:
                    _flog.write(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                        f"league={league_name} | league_id={league_id} | season_id={season_id} | "
                        f"match={event_info.get('name','?')} | round={round_file} | url={url_details}\n"
                    )
                print(f'[WARN] Match saltado tras {MATCH_MAX_ATTEMPTS} intentos — registrado en logs/failed_matches/failed_matches.log')
                league_fully_processed = False
                continue
            # ─────────────────────────────────────────────────────────

            event_info.update(result)
            event_info['tournament_id'] = ''
            event_info['league_id']     = league_id
            event_info['season_id']     = season_id
            event_info['match_date'], event_info['start_time'] = get_time_date_format(event_info['match_date'])
            event_info['end_time'] = event_info['start_time']
            event_info['rounds']   = round_file.replace('.json', '')
            try:
                team_id_home    = dict_country_league_season[event_info['home']]['team_id']
                team_id_visitor = dict_country_league_season[event_info['visitor']]['team_id']
            except KeyError as e:
                print(f"[WARN] Team no encontrado en archivos: {e}")
                team_id_home    = get_team_id_db(event_info['home'], league_id, season_id)
                team_id_visitor = get_team_id_db(event_info['visitor'], league_id, season_id)

            create_stadium(dict_country_league_season, event_info, league_info, team_id_home)
            match_creation_save(event_info, team_id_home, team_id_visitor, section)
            print("MATCH CREATION EXECUTED")
            # Guardar checkpoint en DB después de cada match exitoso
            update_league_checkpoint(league_id, section, round_file, event_info['name'])
            print("UPDATE CHECKPOINT EXECUTED")

    if not checkpoint_match_found:
        print(f'[WARN] Checkpoint match "{checkpoint_match}" no encontrado en '
              f'"{checkpoint_round}". Algunos matches pudieron haberse saltado. '
              f'Liga: {league_name}')

    return league_fully_processed

def save_team_player_single(driver, player_link , league_info):
    # LOAD PLAYER URL    
    if league_info['sport_name'] == 'GOLF':
        wait_update_page(driver, player_link, 'tournamentHeader__participantHeaderWrap')
        player_dict = get_player_data_golf(driver)
    if league_info['sport_name'] == 'TENNIS':
        wait_update_page(driver, player_link, 'container__heading')
        player_dict = get_player_data_tennis(driver)
    if league_info['sport_name'] =='BOXING':
        wait_update_page(driver, player_link, 'container__heading')
        player_dict = get_player_data_boxing(driver)

    player_dict['team_id'] = player_dict['player_id']
    player_dict['season_id'] = league_info['season_id']
    player_dict['team_country'] = player_dict['player_country']
    player_dict['team_name'] = player_dict['player_name']
    player_dict['team_desc'] = ''
    player_dict['team_logo'] = player_dict['player_photo']
    player_dict['sport_id'] = league_info['sport_id']
    player_dict['instance_id'] = generate_uuid()
    player_dict['player_meta'] = ''
    player_dict['team_meta'] = ''
    player_dict['team_position'] = 0
    player_dict['league_id'] = league_info['league_id']
    from data_base import get_country_id, insert_country
    player_dict['country_id'] = get_country_id(player_dict['player_country']) or insert_country(player_dict['player_country'])
    
    # CHECK IF PLAYER WAS CREATED PREVIOUSLY
    # player_id_list = check_player_duplicates(player_dict['player_country'], player_dict['player_name'], player_dict['player_dob'])
    player_id_duplicate = check_player_duplicates_id(player_dict['player_id'])
    print("Result player duplicate: ", player_id_duplicate)
    if not player_id_duplicate:
        save_player_info(player_dict) # player
    else:
        print('Player created previously')

    # CHECK IF TEAM WAS CREATED 
    # team_id_list = check_team_duplicates(player_dict['team_name'], player_dict['sport_id'])
    team_id_list = check_team_duplicates_id(player_dict['team_id'])
    print("team_id_list: ", team_id_list)
    if not team_id_list:
        save_team_info(player_dict) # team
        save_team_players_entity(player_dict) # team_players_entity     
    else:
        print('Team created previously')
        player_dict['team_id'] =  team_id_list[0]


    # CHECK IF TEAM WAS SAVED ON THIS SEASON
    team_season = check_team_season_duplicates(player_dict['league_id'], player_dict['season_id'], player_dict['team_id'])
    if not team_season:
        save_league_team_entity(player_dict) # league_team
    return player_dict['team_id']

def save_team_player_doubles(driver, player_links , league_info):
    # LOAD PLAYER URL
    team_members = []
    for player_link in player_links:
        wait_update_page(driver, player_link, 'container__heading')
        player_dict = get_player_data_tennis(driver)        
        player_dict['season_id'] = league_info['season_id']
        player_dict['team_country'] = player_dict['player_country']     
        player_dict['team_desc'] = ''
        player_dict['team_logo'] = player_dict['player_photo']          
        player_dict['sport_id'] = league_info['sport_id']
        player_dict['instance_id'] = generate_uuid()
        player_dict['player_meta'] = ''
        player_dict['team_meta'] = ''
        player_dict['team_position'] = 0
        player_dict['league_id'] = league_info['league_id']
        team_members.append(player_dict['player_name'])
        # CHECK IF PLAYER WAS CREATED PREVIOUSLY
        player_id_list = check_player_duplicates(player_dict['player_country'], player_dict['player_name'], player_dict['player_dob'])
        if not player_id_list:
            save_player_info(player_dict) # player
        else:
            print('Player created previously')          
    
    # TEAM CREATION
    player_dict['team_id'] = generate_uuid()
    player_dict['team_name'] = '-'.join(team_members)
    
    team_id_list = check_team_duplicates(player_dict['team_name'], player_dict['sport_id'])
    if not team_id_list:
        save_team_info(player_dict) # team
        save_team_players_entity(player_dict) # team_players_entity     
    else:
        print('Team created previously')
        player_dict['team_id'] =  team_id_list[0]


    # CHECK IF TEAM WAS SAVED ON THIS SEASON
    team_season = check_team_season_duplicates(player_dict['league_id'], player_dict['season_id'], player_dict['team_id'])
    if not team_season:
        save_league_team_entity(player_dict) # league_team
    return player_dict['team_id']

def get_complete_match_info_tennis(driver, league_info, section='results'):
    league_id = league_info['league_id']

    # CLAIM LEAGUE — prevents concurrent worker collisions
    if not claim_league(league_id, section):
        print(f"[SKIP] Liga ocupada por otro worker: {league_info['league_name']}")
        return

    league_final_status = 'completed'
    try:
        # READ CHECKPOINT — resume from last successfully processed match
        cp_round, cp_match, cp_status = get_league_checkpoint(league_id, section)
        checkpoint_match_found = (cp_round == '' and cp_match == '')  # True when no checkpoint exists

        # LOAD ROUNDS FILES PREVIOUSLY CREATED
        league_folder = 'check_points/{}/{}/'.format(section, league_info['league_name'])
        if os.path.exists(league_folder):
            round_files = os.listdir(league_folder)
        else:
            round_files = []

        print(round_files, '\n')

        for round_file in round_files:
            # SKIP ROUNDS BEFORE CHECKPOINT
            if cp_round and not checkpoint_match_found and round_file != cp_round:
                print(f"[SKIP] Round anterior al checkpoint: {round_file}")
                continue

            file_path = os.path.join(league_folder, round_file)
            print(file_path)
            round_info = load_json(file_path)
            for event_index, event_info in round_info.items():
                # SKIP MATCHES BEFORE CHECKPOINT IN THE CHECKPOINT ROUND
                if cp_round and not checkpoint_match_found:
                    if round_file == cp_round and event_info.get('name') != cp_match:
                        print(f"[SKIP] Match anterior al checkpoint: {event_info.get('name', '')}")
                        continue
                    else:
                        checkpoint_match_found = True  # found the checkpoint match, process from here

                # SKIP IF MATCH ALREADY SAVED IN DB
                if get_match_ready(event_info['match_id']):
                    print(f"Match already in DB, skipping: {event_info.get('name', '')}")
                    continue
                # GET MATCH DATA
                url_details = event_info['link_details']
                print("Current URL: ", url_details)
                wait_load_details(driver, url_details)
                event_info = get_match_info(driver, event_info)
                print("event_info tennis: ", event_info)

                event_info['statistic'] = get_statistics_game(driver)
                event_info['league_id'] = league_info['league_id']
                event_info['country_id'] = league_info['country_id']

                print("event_info['match_date']", event_info['match_date'])

                event_info['match_date'] = driver.find_element(By.CLASS_NAME, 'duelParticipant__startTime').text
                event_info['match_date'], event_info['start_time'] = get_time_date_format(event_info['match_date'], section='results')
                event_info['end_time'] = event_info['start_time']

                if section == "results" and not '-' in event_info['home_result']:
                    event_info['status'] = 'COMPLETED'
                elif section == "fixtures" or '-' in event_info['home_result']:
                    event_info['status'] = 'SCHEDULED'
                    event_info['home_result'] = -1
                    event_info['visitor_result'] = -1

                home_links, away_links = get_links_participants(driver)
                print('home_links, away_links')
                print(home_links, away_links)

                # CASE SINGLES
                if len(home_links) == 1:
                    team_id_home = save_team_player_single(driver, home_links[0], league_info)
                    team_id_away = save_team_player_single(driver, away_links[0], league_info)
                else:
                    # CASE DOUBLES
                    team_id_home = save_team_player_doubles(driver, home_links, league_info)
                    team_id_away = save_team_player_doubles(driver, away_links, league_info)

                print("Salida del dict: ")

                # LOAD PLACE OR STADIUM INFO AND SAVE IN DB.
                event_info['stadium_id'] = generate_uuid()
                capacity = int(''.join(event_info['CAPACITY'].split())) if 'CAPACITY' in event_info else 0
                name_stadium = event_info.get('VENUE', '')
                dict_stadium = {'stadium_id': event_info['stadium_id'], 'country': event_info['match_country'],
                                'capacity': capacity, 'desc_i18n': '', 'name': name_stadium, 'photo': ''}

                stadium_results = get_stadium_id(name_stadium)
                if len(stadium_results) == 0:
                    print("############ Save stadium info ###################")
                    save_stadium_in_db(dict_stadium)
                if len(stadium_results) != 0:
                    event_info['stadium_id'] = stadium_results[0]

                print("#" * 80, '\n' * 2)
                match_detail_id = generate_uuid()
                score_id = generate_uuid()
                dict_home = {'match_detail_id': match_detail_id, 'home': True, 'visitor': False,
                             'match_id': event_info['match_id'], 'team_id': team_id_home,
                             'points': event_info['home_result'], 'score_id': score_id}
                match_detail_id = generate_uuid()
                score_id = generate_uuid()
                dict_visitor = {'match_detail_id': match_detail_id, 'home': False, 'visitor': True,
                                'match_id': event_info['match_id'], 'team_id': team_id_away,
                                'points': event_info['visitor_result'], 'score_id': score_id}

                event_info['season_id'] = league_info['season_id']
                event_info['tournament_id'] = ''
                event_info['rounds'] = round_file.replace('.json', '')
                print("Event info:")
                print(event_info)
                print("dict_home: ", dict_home)
                save_math_info(event_info)
                save_details_math_info(dict_home)
                save_details_math_info(dict_visitor)
                save_score_info(dict_home)
                save_score_info(dict_visitor)
                # UPDATE CHECKPOINT in DB after each successful match
                update_league_checkpoint(league_id, section, round_file, event_info['name'])
                print("SAVED IN DB ...", end='')

    except Exception as e:
        print(f"[ERROR] get_complete_match_info_tennis: {e}")
        league_final_status = 'interrupted'
        raise
    finally:
        release_league(league_id, section, league_final_status)
        print(f"[{league_final_status.upper()}] Liga liberada: {league_info['league_name']}")

def pending_to_process(dict_country_league_check_point, sport_id, country_league):
    list_sports = list(dict_country_league_check_point.keys())
    if sport_id in list_sports:
        if country_league in list(dict_country_league_check_point[sport_id].keys()):
            return dict_country_league_check_point[sport_id]
        else:
            return dict_country_league_check_point[sport_id]
    else:
        return {}


def results_fixtures_extraction(driver, list_sports, name_section='results',
                                leagues_subset=None):
    sport_name_map = {
        'Football': 'FOOTBALL', 'Basketball': 'BASKETBALL', 'Baseball': 'BASEBALL',
        'Hockey': 'HOCKEY', 'Tennis': 'TENNIS', 'Golf': 'GOLF',
        'Boxing': 'BOXING', 'American Football': 'AM._FOOTBALL',
    }
    dict_sport_id = {sport_name_map.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}
    li_file           = 'check_points/leagues_info.json'
    leagues_info_json = load_check_point(li_file)
    extract_key       = 'extract_results' if name_section == 'results' else 'extract_fixtures'


    SUPPORTED_SPORTS = ['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY']
    SPECIAL_SPORTS   = ['TENNIS', 'GOLF', 'BOXING']

    #############################################################
    #               MAIN LOOP OVER LIST SPORTS                  #
    #############################################################
    for sport_name in list_sports:
        if sport_name not in SUPPORTED_SPORTS:
            continue

        for league_name, league_info in leagues_info_json[sport_name].items():

            if leagues_subset is not None:
                if league_name not in leagues_subset:
                    continue
            else:
                if not league_info.get(extract_key, {}).get('extract', False):
                    continue

            league_id = league_info.get('league_id', '')

            # Claim en DB — reemplaza el flag 'running' del JSON
            if not claim_league(league_id, name_section):
                print(f'[INFO] Liga en uso: {league_name}')
                continue

            league_final_status = 'interrupted'

            try:
                complete_info(league_info, league_name, sport_name, dict_sport_id)

                # Leer checkpoint desde DB
                cp_round, cp_match, cp_status = get_league_checkpoint(league_id, name_section)
                if cp_status == 'interrupted' and (cp_round or cp_match):
                    print(f'[INFO] Retomando desde checkpoint: round={cp_round} match={cp_match}')

                match_number     = get_match_by_league_id(league_info['league_id'])
                path_league_info = 'check_points/leagues_season/{}/{}.json'.format(sport_name, league_name)
                dict_league      = load_check_point(path_league_info)

                league_fully_processed = True

                if name_section in list(league_info.keys()):
                    wait_update_page(driver, league_info[name_section], "container__heading")
                    if not round_files_exist(sport_name, league_name, name_section):
                        navigate_through_rounds(driver, league_info, section_name=name_section)

                    league_fully_processed = get_complete_match_info(
                        driver, league_info, dict_league,
                        cp_round, cp_match,
                        section=name_section
                    )

                match_number = get_match_by_league_id(league_info['league_id'])
                league_info['matches'] = match_number
                league_info[extract_key]['extract'] = False
                save_check_point(li_file, leagues_info_json)

                league_final_status = 'completed' if league_fully_processed else 'interrupted'

            except Exception as e:
                print(f'[ERROR] {league_name}: {type(e).__name__}: {e}')
                raise

            finally:
                release_league(league_id, name_section, league_final_status)


def extraction_by_dict(driver, sport_leagues_dict, name_section='results'):
    """
    Extrae resultados o fixtures para un subconjunto explícito de ligas.

    Args:
        driver:             WebDriver activo.
        sport_leagues_dict: Dict con sport_name → lista de league_names.
                            Ej: {'FOOTBALL': ['BRAZIL_Serie A Betano', 'COLOMBIA_Primera A']}
        name_section:       'results' o 'fixtures'.
    """
    sport_name_map = {
        'Football': 'FOOTBALL', 'Basketball': 'BASKETBALL', 'Baseball': 'BASEBALL',
        'Hockey': 'HOCKEY', 'Tennis': 'TENNIS', 'Golf': 'GOLF',
        'Boxing': 'BOXING', 'American Football': 'AM._FOOTBALL',
    }
    li_file     = 'check_points/leagues_info.json'
    extract_key = 'extract_results' if name_section == 'results' else 'extract_fixtures'

    SUPPORTED_SPORTS = ['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY']
    SPECIAL_SPORTS   = ['TENNIS', 'GOLF', 'BOXING']

    # ── INICIALIZACIÓN CON RETRY ──────────────────────────────────────────────
    # get_dict_sport_id() y load_check_point() hacen I/O (DB y disco).
    # Si fallan en el primer intento (DB transitoriamente caída, archivo bloqueado),
    # se reintenta con backoff antes de abortar todo el worker.
    dict_sport_id     = None
    leagues_info_json = None
    for _init_attempt in range(INIT_MAX_RETRIES):
        try:
            dict_sport_id     = {sport_name_map.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}
            leagues_info_json = load_check_point(li_file)
            break
        except Exception as e:
            if _init_attempt == INIT_MAX_RETRIES - 1:
                print(f'[ERROR] Inicialización fallida tras {INIT_MAX_RETRIES} intentos: {e}')
                raise
            delay = 15 * (_init_attempt + 1)
            print(f'[WARN] Error de inicialización (intento {_init_attempt + 1}/{INIT_MAX_RETRIES}), reintentando en {delay}s: {e}')
            time.sleep(delay)

    consecutive_fails = 0  # contador de ligas fallidas consecutivas (señal de driver roto)

    for sport_name, league_list in sport_leagues_dict.items():
        if sport_name not in SUPPORTED_SPORTS:
            continue

        for league_name in league_list:

            # ── RECARGAR leagues_info DESDE DISCO ────────────────────────────
            # Garantiza que ligas ya marcadas extract=False por otro worker o
            # por una iteración anterior no sean reprocesadas.
            try:
                leagues_info_json = load_check_point(li_file)
            except Exception as e:
                print(f'[WARN] No se pudo recargar leagues_info ({league_name}): {e} — usando copia en memoria')

            league_info = leagues_info_json.get(sport_name, {}).get(league_name)
            if not league_info:
                print(f'[WARN] Liga no encontrada en leagues_info: {sport_name}/{league_name}')
                continue

            # ── SKIP SI YA FUE PROCESADA ─────────────────────────────────────
            if not league_info.get(extract_key, {}).get('extract', False):
                print(f'[INFO] Liga ya procesada (extract=False): {league_name}')
                continue

            league_id = league_info.get('league_id', '')

            # ── CLAIM CON PROTECCIÓN ──────────────────────────────────────────
            # claim_league hace una escritura en DB; si la DB está transitoriamente
            # caída lanza excepción. Sin este try/except propagaría y mataría todo.
            try:
                if not claim_league(league_id, name_section):
                    print(f'[INFO] Liga en uso (otro worker): {league_name}')
                    continue
            except Exception as e:
                print(f'[WARN] Error al reclamar liga {league_name}: {type(e).__name__}: {e} — saltando')
                continue

            league_final_status = 'interrupted'  # default si algo falla

            try:
                print(f'[LIGA] {sport_name} / {league_name}')

                # Verificar sesión activa — re-login si el botón LOGIN es visible
                try:
                    from config import FS_EMAIL, FS_PASSWORD
                    login_btn = driver.find_elements(By.XPATH, '//*[contains(@class,"login") or text()="LOGIN" or text()="Login"]')
                    if login_btn:
                        print(f'[WARN] Sesión expirada detectada — re-login...')
                        login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
                        dismiss_cookies(driver)
                except Exception as _login_err:
                    print(f'[WARN] Error en verificación de sesión: {_login_err}')

                complete_info(league_info, league_name, sport_name, dict_sport_id)

                # Leer checkpoint desde DB (resume si fue interrumpida)
                cp_round, cp_match, cp_status = get_league_checkpoint(league_id, name_section)
                if cp_status == 'interrupted' and (cp_round or cp_match):
                    print(f'[INFO] Retomando desde checkpoint: round={cp_round} match={cp_match}')

                prev_match_number = get_match_by_league_id(league_id)
                path_league_info  = 'check_points/leagues_season/{}/{}.json'.format(sport_name, league_name)
                dict_league       = load_check_point(path_league_info)

                league_fully_processed = True

                if name_section in list(league_info.keys()):

                    # ── NIVEL A: retry de navegación inicial ──────────────────
                    # wait_update_page y navigate_through_rounds pueden fallar por
                    # timeout o elemento stale; se reintenta antes de abortar la liga.
                    for nav_attempt in range(LEAGUE_NAV_RETRIES):
                        try:
                            wait_update_page(driver, league_info[name_section], "container__heading")
                            dismiss_cookies(driver)
                            break
                        except RETRY_EXCEPTIONS as e:
                            if nav_attempt == LEAGUE_NAV_RETRIES - 1:
                                raise
                            print(f'[WARN] Error de navegación (intento {nav_attempt + 1}/{LEAGUE_NAV_RETRIES}): {e}')
                            time.sleep(5 * (nav_attempt + 1))

                    if not round_files_exist(sport_name, league_name, name_section):
                        # ── NIVEL B: retry de creación de rondas ──────────────
                        for nav_attempt in range(LEAGUE_NAV_RETRIES):
                            try:
                                navigate_through_rounds(driver, league_info, section_name=name_section)
                                break
                            except RETRY_EXCEPTIONS as e:
                                if nav_attempt == LEAGUE_NAV_RETRIES - 1:
                                    raise
                                print(f'[WARN] Error creando rondas (intento {nav_attempt + 1}/{LEAGUE_NAV_RETRIES}): {e}')
                                time.sleep(5 * (nav_attempt + 1))
                                driver.get(league_info[name_section])

                    # ── NIVEL C: retry de extracción completa ─────────────────
                    for league_attempt in range(LEAGUE_MAX_RETRIES + 1):
                        try:
                            league_fully_processed = get_complete_match_info(
                                driver, league_info, dict_league,
                                cp_round, cp_match,
                                section=name_section
                            )
                            break  # éxito → salir del retry
                        except RETRY_EXCEPTIONS as e:
                            if league_attempt == LEAGUE_MAX_RETRIES:
                                raise
                            delay = 10 * (league_attempt + 1)
                            print(f'[WARN] Error en liga {league_name}, reintento {league_attempt + 1}/{LEAGUE_MAX_RETRIES} en {delay}s')
                            time.sleep(delay)
                            driver.get(league_info[name_section])
                            # Re-leer checkpoint de DB (puede haberse actualizado en este intento)
                            cp_round, cp_match, _ = get_league_checkpoint(league_id, name_section)

                new_match_number = get_match_by_league_id(league_id)
                league_info[extract_key]['extract'] = False
                if new_match_number != prev_match_number:
                    league_info['matches'] = new_match_number

                # Limpiar claves temporales inyectadas por complete_info
                for k in ('sport_name', 'sport_id', 'league_name'):
                    league_info.pop(k, None)

                # ── GUARDAR CON PROTECCIÓN ────────────────────────────────────
                # Si falla el guardado, extract=False queda solo en memoria.
                # Se loguea pero no se relanza — la liga ya fue procesada.
                try:
                    save_check_point(li_file, leagues_info_json)
                except Exception as e:
                    print(f'[WARN] No se pudo persistir leagues_info tras {league_name}: {e}')

                league_final_status = 'completed' if league_fully_processed else 'interrupted'
                consecutive_fails   = 0  # reset: procesamiento exitoso

            except Exception as e:
                consecutive_fails += 1
                for k in ('sport_name', 'sport_id', 'league_name'):
                    league_info.pop(k, None)
                print(f'[ERROR] {league_name} (fallo #{consecutive_fails}): {type(e).__name__}: {e}')

                # Screenshot al fallar la liga
                try:
                    ss_dir = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'logs', 'parallel', 'screenshots'
                    )
                    os.makedirs(ss_dir, exist_ok=True)
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    safe_name = league_name.replace('/', '_').replace(' ', '_')
                    ss_path = os.path.join(ss_dir, f'league_error_{safe_name}_{ts}.png')
                    driver.save_screenshot(ss_path)
                    print(f'[WARN] Screenshot guardado: {ss_path}')
                except Exception:
                    pass

                # Alerta si hay demasiados fallos seguidos (posible driver roto)
                if consecutive_fails >= LEAGUE_MAX_CONSECUTIVE_FAILS:
                    print(f'[ERROR] {consecutive_fails} ligas fallidas consecutivas — posible driver roto o sitio caído')

                # NO raise — siempre continuar con la siguiente liga

            finally:
                # ── RELEASE CON PROTECCIÓN ────────────────────────────────────
                # Si release_league lanza (DB caída), sin este try/except la excepción
                # del finally reemplazaría la del except y el worker colapsaría.
                try:
                    release_league(league_id, name_section, league_final_status)
                except Exception as e:
                    print(f'[WARN] No se pudo liberar liga {league_name} en DB: {e}')


def extraction_special_sports(driver, sport_leagues_dict, name_section='results'):
    """
    Extrae resultados/fixtures para deportes especiales: TENNIS, GOLF, BOXING.
    Mismo patrón de claim/release que extraction_by_dict.
    Tennis y Golf soportan distribución multi-worker desde paralel_execution.py.

    Args:
        driver:             WebDriver activo.
        sport_leagues_dict: Dict sport_name → lista de league_names.
                            Ej: {'TENNIS': ['ATP_Wimbledon', 'WTA_Roland Garros']}
        name_section:       'results' o 'fixtures'.
    """
    sport_name_map = {
        'Football': 'FOOTBALL', 'Basketball': 'BASKETBALL', 'Baseball': 'BASEBALL',
        'Hockey': 'HOCKEY', 'Tennis': 'TENNIS', 'Golf': 'GOLF',
        'Boxing': 'BOXING', 'American Football': 'AM._FOOTBALL',
    }
    li_file     = 'check_points/leagues_info.json'
    extract_key = 'extract_results' if name_section == 'results' else 'extract_fixtures'

    SPECIAL_SPORTS_LOCAL = ['TENNIS', 'GOLF', 'BOXING']

    dict_sport_id     = None
    leagues_info_json = None
    for _init_attempt in range(INIT_MAX_RETRIES):
        try:
            dict_sport_id     = {sport_name_map.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}
            leagues_info_json = load_check_point(li_file)
            break
        except Exception as e:
            if _init_attempt == INIT_MAX_RETRIES - 1:
                print(f'[ERROR] Inicialización fallida tras {INIT_MAX_RETRIES} intentos: {e}')
                raise
            delay = 15 * (_init_attempt + 1)
            print(f'[WARN] Error de inicialización (intento {_init_attempt + 1}/{INIT_MAX_RETRIES}), reintentando en {delay}s: {e}')
            time.sleep(delay)

    for sport_name, league_names in sport_leagues_dict.items():
        if sport_name not in SPECIAL_SPORTS_LOCAL:
            print(f'[INFO] {sport_name} no es deporte especial — saltando')
            continue

        for league_name in league_names:
            league_info = leagues_info_json.get(sport_name, {}).get(league_name)
            if not league_info:
                print(f'[WARN] Liga no encontrada en leagues_info: {sport_name}/{league_name}')
                continue

            if not league_info.get(extract_key, {}).get('extract', False):
                print(f'[INFO] Liga ya procesada (extract=False): {league_name}')
                continue

            league_id = league_info.get('league_id', '')

            try:
                if not claim_league(league_id, name_section):
                    print(f'[INFO] Liga en uso (otro worker): {league_name}')
                    continue
            except Exception as e:
                print(f'[WARN] Error al reclamar liga {league_name}: {type(e).__name__}: {e} — saltando')
                continue

            league_final_status = 'interrupted'

            try:
                print(f'[LIGA] {sport_name} / {league_name}')

                # Verificar sesión activa — re-login si expiró
                try:
                    from config import FS_EMAIL, FS_PASSWORD
                    login_btn = driver.find_elements(By.XPATH, '//*[contains(@class,"login") or text()="LOGIN" or text()="Login"]')
                    if login_btn:
                        print(f'[WARN] Sesión expirada detectada — re-login...')
                        login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
                        dismiss_cookies(driver)
                except Exception as _login_err:
                    print(f'[WARN] Error en verificación de sesión: {_login_err}')

                complete_info(league_info, league_name, sport_name, dict_sport_id)

                if sport_name == 'TENNIS':
                    if name_section in league_info:
                        for nav_attempt in range(LEAGUE_NAV_RETRIES):
                            try:
                                wait_update_page(driver, league_info[name_section], 'container__heading')
                                dismiss_cookies(driver)
                                break
                            except RETRY_EXCEPTIONS as e:
                                if nav_attempt == LEAGUE_NAV_RETRIES - 1:
                                    raise
                                time.sleep(5 * (nav_attempt + 1))
                        if not round_files_exist(sport_name, league_name, name_section):
                            navigate_through_rounds(driver, league_info, section_name=name_section)
                        get_complete_match_info_tennis(driver, league_info, section=name_section)

                elif sport_name == 'GOLF':
                    get_complete_match_info_golf(driver, league_info, section=name_section)

                elif sport_name == 'BOXING':
                    extract_info_boxing(driver, league_info)

                league_info[extract_key]['extract'] = False
                for k in ('sport_name', 'sport_id', 'league_name'):
                    league_info.pop(k, None)
                try:
                    save_check_point(li_file, leagues_info_json)
                except Exception as e:
                    print(f'[WARN] No se pudo persistir leagues_info tras {league_name}: {e}')

                league_final_status = 'completed'

            except Exception as e:
                print(f'[ERROR] {sport_name}/{league_name}: {type(e).__name__}: {e}')

            finally:
                try:
                    release_league(league_id, name_section, league_final_status)
                except Exception as e:
                    print(f'[WARN] No se pudo liberar liga {league_name}: {e}')


def extraction_special_sports_list(driver, sport_list, name_section='results'):
    """
    Wrapper de extraction_special_sports que acepta una lista de deportes.
    Lee leagues_info.json, filtra las ligas habilitadas para cada deporte
    de la lista y ejecuta la extracción secuencialmente.

    Args:
        driver:       WebDriver activo.
        sport_list:   Lista de deportes especiales. Ej: ['TENNIS', 'GOLF']
        name_section: 'results' o 'fixtures'.

    Uso:
        extraction_special_sports_list(driver, ['TENNIS', 'GOLF'], name_section='results')
    """
    extract_key   = 'extract_results' if name_section == 'results' else 'extract_fixtures'
    li_file       = 'check_points/leagues_info.json'
    leagues_info  = load_check_point(li_file)

    sport_leagues_dict = {}
    for sport_name in sport_list:
        sport_name = sport_name.upper()
        leagues = leagues_info.get(sport_name, {})
        enabled = [
            league_name for league_name, league_info in leagues.items()
            if league_info.get(extract_key, {}).get('extract', False)
        ]
        if enabled:
            sport_leagues_dict[sport_name] = enabled
            print(f'[INFO] {sport_name}: {len(enabled)} ligas habilitadas')
        else:
            print(f'[INFO] {sport_name}: sin ligas habilitadas para {name_section}')

    if not sport_leagues_dict:
        print(f'[INFO] No hay ligas habilitadas para {sport_list} en [{name_section}]')
        return

    extraction_special_sports(driver, sport_leagues_dict, name_section=name_section)


def build_detail_score_dict(racer, dict_match):
    position, name, team, points = racer.find_elements(By.XPATH, './div')
    name = name.find_element(By.XPATH, './div/div/a').text
    position = position.text.replace('.','').replace(' ','')
    points.text
    team_id = generate_uuid_text("MOTOR SPORT" + team.text+ name)
    dict_detail_score = {'match_detail_id': generate_uuid() , 'home': False, 'visitor': False,
                             'match_id':dict_match['match_id'],'team_id':'',
                         'points':points, 'score_id':generate_uuid()
                            }
    return dict_detail_score

def build_match_dict(driver, block_match, season_year, category):
    # DATE TIME AND STATUS
    try:
        status_text = block_match.find_element(By.XPATH, './/div[contains(@class,"headerLeague__actions")]').text
    except Exception:
        status_text = ''

    race_info = block_match.find_element(By.CLASS_NAME, "event__header.event__header--info").text.split(',')

    if len(race_info)== 4:
        date_time, place, descr, descr2  = race_info
        descr = descr + ',' + descr2

    if len(race_info)== 3:
        date_time, place, descr  = race_info

    match_date, start_time = get_time_date_format(date_time, section='results')
    if 'Finished' in status_text:
        status = 'COMPLETED'
        place = clean_text(place)
        descr = clean_text(descr)
    else:
        status = 'SCHEDULED'

    place = clean_text(place)
    descr = clean_text(descr)

    grand_prix_title = block_match.find_element(By.XPATH, './/a[contains(@class,"headerLeague__title")]').text
    grand_prix_title = ' '.join(grand_prix_title.split())
    match_country =  re.findall( r'\((.*?)\)', grand_prix_title)[0]
    
    
    
    # BUILD STADIUM DICT = AUTODROME_DICT
    autodrome_dict = {"stadium_id": generate_uuid_text(place),
                        "capacity": 0,
                        "country": match_country,
                        "desc_i18n": descr,
                        "name": place,
                        "photo": ""
                        }
    
    # BUILD MATCH DICT
    dict_match = {'match_id':generate_uuid_text(grand_prix_title + season_year), 'match_country':match_country, 'end_time':start_time,
                  'match_date':match_date, 'name':grand_prix_title,'start_time':start_time, 
                  'place':place, 'rounds':'',
                  'season_id':generate_uuid_text(category + season_year),
                  'status':status, 'statistic':'',
                  'league_id':generate_uuid_text("MOTOR SPORT" + category), 'stadium_id': autodrome_dict['stadium_id'],
                  'country_id': '', 'tournament_id': ''
                 }
    return autodrome_dict, dict_match

def create_events_f1(driver, category = 'FORMULA 1', season_year = '2024'):

    block_matchs = driver.find_elements(By.CLASS_NAME, "sportName--noDuel.motorsport-auto-racing")

    print(len(block_matchs))
    
    for block_match in block_matchs:
        try:
            title_event = block_match.find_element(By.XPATH, './/a[contains(@class,"headerLeague__title")]').text
        except Exception:
            title_event = ''
        if 'Race' in title_event:
            print("title_event: ", title_event)
            # GET AUTODROME=STADIUM_ID, MATCH DICT
            list_fields = block_match.find_elements(By.XPATH, './div[@class="event__match event__main event__match--noDuel"]/div')
            list_fields = [field.text for field in list_fields]

            autodrome_dict, dict_match = build_match_dict(driver, block_match, season_year, category)
            print_section(f"{dict_match['name']} {dict_match['match_id']} ")
            if not check_stadium(autodrome_dict['stadium_id']):
                print("Create new stadium autodrome")
                save_stadium_in_db(autodrome_dict)

            # CHECK DUPLICATES AND SAVE AUTODROME AND MATCH.
            if not get_match_ready(dict_match['match_id']):
                print("Create new match")
                save_math_info(dict_match)

            # GET PARTICIPANS MATCH DETAILS MATCH SCORE.
            racer_rows = block_match.find_elements(By.XPATH, './div[contains(@class,"event__match--withRowLink")]')
            for racer in racer_rows:
                list_contain = racer.find_elements(By.XPATH, './div')
                list_contain = [field.text for field in list_contain]
                if len(list_contain)==8:
                    list_contain = list_contain[1:]

                dict_result = {k.upper(): v for k, v in zip(list_fields, list_contain)}

                print_section("crear team id")
                print(f"#{dict_result['TEAM']}#")
                if dict_result['TEAM'] == 'RB':
                    dict_result['TEAM'] = 'RB (F1 Team)'
                team_id = get_team_id_pilot(dict_result['DRIVER'], dict_result['TEAM'])
                print(dict_result)

    #             print(f"TEAM: {dict_result['#']} {dict_result['TEAM']} driver: {dict_result['DRIVER']}")
                print("team_id: ", team_id)
                dict_match_detail = {'match_detail_id':generate_uuid(),'home':False, 'visitor':False,
                                    'match_id':dict_match['match_id'], 'team_id':team_id,
                                    'score_id':generate_uuid(), 'points':f1_puntuation(dict_result['#'])}

                # INPUT VAR: team_id, match_id, dict_match['match_id']
                save_details_math_info(dict_match_detail)
                save_score_info(dict_match_detail)

    f1_league_id = generate_uuid_text("MOTOR SPORT" + category)
    update_league_stats_json('MOTOR SPORT', f1_league_id)

def get_grand_prix_links(driver):
    list_links = driver.find_elements(By.XPATH, '//td[@class="seasonCalendar__name"]/a')
    grand_prix_links = []
    for link in list_links:    
        grand_prix_links.append(link.get_attribute('href'))
    return grand_prix_links

def get_match_link(driver, match):
    dict_match = {}
    html_block = match.get_attribute('outerHTML')
#     link_id = re.findall(r'id="[a-z]_\d_(.+?)\"', html_block)[0] # old regular expression
    link_id = re.findall(r'id="[a-z]_\d+\_(.+?)\"', html_block)[0]
    url_details = "https://www.flashscore.com/match/{}/#/match-summary/match-summary".format(link_id)
    dict_match['url'] = url_details    
    return dict_match

def get_result_boxig(driver):
    home_result = -1
    away_result = -1
    status = 'SCHEDULED'
    try:
        home_participant = driver.find_element(By.CLASS_NAME, 'duelParticipant__home.duelParticipant--winner').text
        home_result = 1
        away_result = 0
        status = 'COMPLETED'
    except:
        home_participant = driver.find_element(By.CLASS_NAME, 'duelParticipant__home').text
    try:
        away_participant = driver.find_element(By.CLASS_NAME, 'duelParticipant__away.duelParticipant--winner').text
        home_result = 0
        away_result = 1
        status = 'COMPLETED'
    except:
        away_participant = driver.find_element(By.CLASS_NAME, 'duelParticipant__away').text
    match_id = generate_uuid()
    result_dict = {'match_id':match_id,'name':home_participant + '-' + away_participant,\
                   'home':home_participant,'visitor':away_participant,\
                   'home_result':home_result,  'visitor_result':away_result,\
                   'status':status, 'place':''
                  }
    return result_dict

def extract_info_boxing(driver, league_info):
    dict_stadium = {'stadium_id':'BOXING97943','country':'',\
             'capacity':0,'desc_i18n':'', 'name':'', 'photo':''}
    if check_stadium('BOXING97943'):
        print("BOXING stadium created")
    else:
        save_stadium_in_db(dict_stadium)

    results_url = league_info.get('results') or league_info['url'].rstrip('/') + '/results/'
    driver.get(results_url)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//div[@data-event-row="true"]'))
        )
    except Exception:
        time.sleep(4)

    # EXTRACT ALL MATCH BLOCKS
    list_match = driver.find_elements(By.XPATH, '//div[contains(@class,"event__match") and @data-event-row="true"]')
    dict_matchs_link = {}
    # for event_block in event_blocks:
    for key, match in enumerate(list_match):
        
        dict_matchs_link[key]= get_match_link(driver, match)# INSIDE MATCH GET COMPLETE INFO

    for key, match in dict_matchs_link.items():

        wait_load_details(driver, match['url'])
        event_info = get_result_boxig(driver)
        event_info['stadium_id'] = dict_stadium['stadium_id']
        event_info['match_country'] = ''
        event_info['statistic'] = get_statistics_game(driver)
        event_info['league_id'] = league_info['league_id']
        event_info['country_id'] = league_info['country_id']

        event_info['match_date'] = driver.find_element(By.CLASS_NAME, 'duelParticipant__startTime').text
        event_info['match_date'], event_info['start_time'] = get_time_date_format(event_info['match_date'], section='results')
        event_info['end_time'] = event_info['start_time']
        event_info['season_id'] = league_info['season_id']
        event_info['tournament_id'] = ''
        event_info['rounds'] = ''

        # Deterministic match_id to prevent duplicates on re-run
        event_info['match_id'] = generate_uuid_text(
            league_info['league_id'] + event_info['name'] + str(event_info['match_date'])
        )

        if check_match_duplicate(league_info['league_id'], event_info['match_date'], event_info['name']):
            print(f"[SKIP] Match ya existe: {event_info['name']}")
            continue

        print_section("BOXING MATCH INFO")
        print("Event info:", event_info)

        home_links, away_links = get_links_participants(driver)
        team_id_home = save_team_player_single(driver, home_links[0], league_info)
        team_id_away = save_team_player_single(driver, away_links[0], league_info)

        match_detail_id = generate_uuid()
        score_id = generate_uuid()
        dict_home = {'match_detail_id':match_detail_id, 'home':False, 'visitor':False, 'match_id':event_info['match_id'],\
                    'team_id':team_id_home, 'points':event_info['home_result'], 'score_id':score_id}
        match_detail_id = generate_uuid()
        score_id = generate_uuid()
        dict_visitor = {'match_detail_id':match_detail_id, 'home':False, 'visitor':False, 'match_id':event_info['match_id'],\
                    'team_id':team_id_away, 'points':event_info['visitor_result'], 'score_id':score_id}

        save_math_info(event_info)
        save_details_math_info(dict_home)
        save_details_math_info(dict_visitor)
        save_score_info(dict_home)
        save_score_info(dict_visitor)

    update_league_stats_json(league_info.get('sport_name', 'BOXING'), league_info['league_id'])

def get_first_date_with_year(text):
    # Regular expression pattern to find the date in the specified format
    date_pattern = r'(\d{2}\.\d{2})\.-(\d{2}\.\d{2})\.(\d{4})'
    
    # Search for matches of the regular expression pattern in the text
    match = re.search(date_pattern, text)   

    if match:
        # Extract the found dates
        first_date_str, second_date_str, year = match.groups()
        
        # Split the date range
        first_date_parts = first_date_str.split('.')
        second_date_parts = second_date_str.split('.')
        
        # Take only the first date from the range and add the year
        first_date = f"{first_date_parts[0]}.{first_date_parts[1]}.{year}"
        
        # Convert the date string into a datetime object
        dt_object = datetime.strptime(first_date, '%d.%m.%Y')
        
        # Extract date and time
        date = dt_object.date()
        time = dt_object.time()
        
        return date, time
    else:
        return None, None

def get_tournament(driver, league_info, event_block):

    dict_match = {}
    # STATISTIC 
    statistic_dict = {}
    valores = event_block.find_element(By.CLASS_NAME, 'event__header--info').text.split('\n')
    
    for valor in valores:
        clave, valor = valor.split(': ')
        statistic_dict[clave] = valor

    print("statistic_dict")
    print(statistic_dict)
    # EXTRACT DATE_TIME
    date_time = event_block.find_element(By.XPATH, './/div[contains(@class,"headerLeague__actions")]/span').text
    print('#'*100)
    print(date_time)
    if 'Finished' in date_time:
        dict_match['match_date'], dict_match['start_time'] = get_first_date_with_year(statistic_dict['Dates'])
        dict_match['status'] = 'COMPLETED'
    else:
        dict_match['match_date'], dict_match['start_time'] = get_time_date_format(date_time, section ='results')
        dict_match['status'] = 'SCHEDULED'    
    
    dict_match['match_id'] = generate_uuid()
    dict_match['match_country'] = ''
    
    dict_match['end_time'] = dict_match['start_time']
    dict_match['name'] = event_block.find_element(By.CLASS_NAME, 'headerLeague__title-text').text
    dict_match['place'] = '*'
    
    dict_match['rounds'] = dict_match['name']
    dict_match['season_id'] = league_info['season_id']      
    dict_match['statistic'] = str(statistic_dict)
    dict_match['league_id'] = league_info['league_id']  
    dict_match['stadium_id'] = None
    dict_match['country_id'] = league_info['country_id']
    dict_match['tournament_id'] = ''
    return dict_match

def buil_dict_map_values_golf(event_block):
    block = event_block.find_element(By.CSS_SELECTOR, '.event__match.event__main.event__match--noDuel')
    cell_names = block.find_elements(By.XPATH,'.//div')
    dict_map_cell = {}
    for index, cell_name in enumerate(cell_names):
        cell_name = cell_name.get_attribute('title').replace(' ', '_')    
        dict_map_cell[index] = cell_name
    return dict_map_cell 

def get_player_result(player_block, dict_map_cell):
    dict_player = {}
    cell_values = player_block.find_elements(By.XPATH, './/div')    
    for index, cell_value in enumerate(cell_values):
        dict_player[dict_map_cell[index]] = cell_value.text
    return dict_player

def get_player_url(player_block):
    html_block = player_block.get_attribute('outerHTML')    
    link_id = re.findall(r'id="[a-z]\_\d+\_(.+?)"', html_block)[0]
    url_details = "https://www.flashscore.com/match/{}/p/#/match-summary".format(link_id)
    return url_details

def get_dict_players(event_block):

    dict_map_cell = buil_dict_map_values_golf(event_block)
    players = event_block.find_elements(By.XPATH, './/div[@data-event-row="true"]')
    print(len(players))
    dict_players = {}
    
    for index, player_block in enumerate(players):
        print(index, end = '-')
        dict_players[index] = {'statistic': get_player_result(player_block, dict_map_cell), 'player_url' : get_player_url(player_block)} 
    return dict_players


def get_complete_match_info_golf(driver, league_info, section='results'):
    """
    Extrae torneos y participantes de una liga de Golf.
    No usa archivos de ronda — navega directamente a la URL de la liga
    y procesa cada bloque de torneo en la página.
    """
    if section not in league_info:
        print(f'[WARN] No URL para {section} en liga golf: {league_info.get("league_name")}')
        return

    driver.get(league_info[section])
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, 'sportName--noDuel'))
        )
    except Exception:
        time.sleep(5)
    dismiss_cookies(driver)

    event_blocks = driver.find_elements(By.CLASS_NAME, 'sportName--noDuel')
    print(f'[GOLF] {len(event_blocks)} torneos encontrados en {league_info.get("league_name")}')

    for event_block in event_blocks:
        try:
            dict_match = get_tournament(driver, league_info, event_block)

            match_created = check_match_duplicate(
                league_info['league_id'],
                dict_match['match_date'],
                dict_match['name']
            )
            if match_created:
                print(f'[SKIP] Torneo ya existe: {dict_match["name"]}')
                continue

            dict_players = get_dict_players(event_block)
            print(f'[GOLF] {dict_match["name"]} — {len(dict_players)} jugadores')

            save_math_info(dict_match)

            for idx, player_info in dict_players.items():
                player_url = player_info.get('player_url', '')
                if not player_url:
                    continue
                try:
                    team_id = save_team_player_single(driver, player_url, league_info)
                    match_detail_id = generate_uuid()
                    score_id        = generate_uuid()
                    dict_detail = {
                        'match_detail_id': match_detail_id,
                        'home':     False,
                        'visitor':  False,
                        'match_id': dict_match['match_id'],
                        'team_id':  team_id,
                        'points':   player_info['statistic'].get('', 0),
                        'score_id': score_id,
                    }
                    save_details_math_info(dict_detail)
                    save_score_info(dict_detail)
                except Exception as e:
                    print(f'[WARN] Golf jugador {idx}: {type(e).__name__}: {e}')
                    continue

        except Exception as e:
            print(f'[ERROR] Golf torneo: {type(e).__name__}: {e}')
            continue


if __name__ == "__main__":
    driver = launch_navigator('https://www.flashscore.com', headless = True)
    login(driver, email_= "FS_EMAIL", password_ = "FS_PASSWORD")

    results_fixtures_extraction(driver, list_sports=["FOOTBALL","BASKETBALL","BASEBALL",
                                                        "AM._FOOTBALL", "HOCKEY", "TENNIS"
                                                        ,"GOLF"], name_section='results')
    