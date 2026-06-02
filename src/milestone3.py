from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import time
import psycopg2
import shutil

from common_functions import *
from data_base import *

def buil_dict_map_values(driver):
	block = driver.find_element(By.CLASS_NAME, 'ui-table__header')
	cell_names = block.find_elements(By.XPATH,'.//div')
	dict_map_cell = {}
	for index, cell_name in enumerate(cell_names[2:]):
		cell_name = cell_name.get_attribute('title').replace(' ', '_')    
		dict_map_cell[index] = cell_name
	return dict_map_cell 

def get_teams_info_part1(driver):
	wait = WebDriverWait(driver, 10)
	# teams_availables = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, 'ui-table__row')))
	xpath_expression = '//*[@id="tournament-table-tabs-and-content"]/div/div/div/div/div/div/span'	
	# all_cells = driver.find_elements(By.XPATH, xpath_expression)
	# print("All cells found: ", len(all_cells))
	dict_map_cell = {}
	try:
		all_cells = wait.until(EC.presence_of_all_elements_located((By.XPATH, xpath_expression)))
		dict_map_cell = buil_dict_map_values(driver)
	except:
		print("--")
	teams_availables = driver.find_elements(By.CLASS_NAME, 'ui-table__row')	
	# time.sleep(5)
	dict_teams_availables = {}

	for team in teams_availables:
		team_name = team.find_element(By.XPATH, './/div[@class="tableCellParticipant"]').text
		team_position = team.find_element(By.XPATH, './/div[@class="tableCellRank"]').text
		team_position = int(re.search(r'\d+',team_position).group(0))
		try:
			games_hist = team.find_element(By.XPATH, './/div[contains(@class,"table__cell--form")]').text.split('\n')
		except Exception:
			games_hist = ''
		
		team_url = team.find_element(By.XPATH, './/a[@class="tableCellParticipant__name"]')
		team_statistic = team.find_elements(By.XPATH, './/span[@class=" table__cell table__cell--value   "]')    
		dict_statistic = {}
		print("-", team_name, end = ' ')
		for index, cell_value in enumerate(team_statistic):
			if index in dict_map_cell:
				dict_statistic[dict_map_cell[index]] = cell_value.text
		
		dict_teams_availables[team_name] = {'team_url': team_url.get_attribute('href'), 'statistics':dict_statistic,\
										   'position':team_position, 'last_results': games_hist}
	return dict_teams_availables

def get_teams_info_part2(driver, league_inf, team_info):
	block_ligue_team = driver.find_element(By.CLASS_NAME, 'container__heading')
	# sport = block_ligue_team.find_element(By.XPATH, './/h2[@class= "breadcrumb"]/a[1]').text
	try:
		team_country = block_ligue_team.find_element(By.XPATH, './/h2[@class= "breadcrumb"]/a[2]').text
	except:
		team_country = block_ligue_team.find_element(By.XPATH, './/h2[@class= "breadcrumb"]/span[2]').text
	team_name = block_ligue_team.find_element(By.CLASS_NAME,'heading__title').text
	team_name = clean_field(team_name)	
	try:
		stadium = block_ligue_team.find_element(By.CLASS_NAME, 'heading__info').text
	except:
		stadium = ''
	image_url = block_ligue_team.find_element(By.XPATH, './/div[@class= "heading"]/img').get_attribute('src')
	image_path = random_name_logos(team_name, folder = 'images/logos/')
	save_image(driver, image_url, image_path)
	logo_path = image_path.replace('images/logos/','')
	# team_id = random_id_text(league_inf['sport_name'] + league_inf['league_name'] + team_name)
	team_id = generate_uuid()
	instance_id = generate_uuid()
	meta_dict = str({'statistics':team_info['statistics'], 'last_results':team_info['last_results']})
	team_info = {"team_id":team_id,"team_position":team_info['position'], "team_country":team_country,"team_desc":'', 'team_logo':logo_path,\
			 'team_name': team_name,'sport_id': league_inf['sport_id'], 'league_id':league_inf['league_id'], 'season_id':league_inf['season_id'],\
			 'instance_id':instance_id, 'team_meta':meta_dict, 'stadium':stadium, 'player_meta' :''}
	return team_info

def add_league_info(sport_name, sport_id, country_league, legue_info):
	legue_info['sport_name'] = sport_name
	legue_info['sport_id'] = sport_id
	legue_info['league_name'] = country_league


def create_folder(path):
	if not os.path.exists(path):
		os.mkdir(path)

def create_team_in_db(dict_teams_db, sport_id, dict_team):
	country_id = dict_team['country_id']
	team_name  = dict_team['team_name']

	# get_dict_league_ready builds 4 levels: {sport_id: {team.country_id: {league.country_id: {team_name: ...}}}}
	# Iteramos el sub-nivel intermedio (league.country_id) para encontrar el equipo
	dict_team_db = {}
	for _, teams in dict_teams_db.get(sport_id, {}).get(country_id, {}).items():
		if team_name in teams:
			dict_team_db = teams[team_name]
			break

	if len(dict_team_db) != 0:
		print("TEAM FOUND IN DATA_BASE")
		team_id = dict_team_db['team_id']
	else:
		print(" TEAM DON'T FOUND IN DATA_BASE")
		# Bug fix: pasar country_id (hash) en lugar de team_country (nombre)
		team_id_db = get_list_id_teams(sport_id, dict_team['country_id'], dict_team['team_name'])
		if len(team_id_db) == 0:
			print("TEAM CREATED AND SAVED IN DATA BASE")
			save_team_info(dict_team)
			save_league_team_entity(dict_team)
			team_id = dict_team['team_id']
		else:
			print("TEAM HAS BEEN SAVED PREVIOUSLY")
			team_id = team_id_db[0]
			# Asegurar vínculo league_team para esta liga/temporada.
			# El equipo existe en `team` pero puede no estar vinculado a esta liga/season.
			existing = check_team_season_duplicates(
				dict_team['league_id'], dict_team['season_id'], team_id
			)
			if not existing:
				dict_team['team_id']     = team_id
				dict_team['instance_id'] = generate_uuid()
				save_league_team_entity(dict_team)
				print("LEAGUE_TEAM ENTITY CREATED FOR EXISTING TEAM")

	# Actualizar cache en memoria → futuros lookups usan Layer 1 sin query a DB
	(dict_teams_db
		.setdefault(sport_id, {})
		.setdefault(country_id, {})
		.setdefault(country_id, {})
		.__setitem__(team_name, {'team_id': team_id}))

	return team_id




def get_links_divisiones(driver, standings_url):
    """
    Navega a standings_url y retorna los hrefs de todos los tabs de división
    (wcl-tabs data-type="secondary").
    Si no existen tabs → retorna lista vacía (la liga tiene una sola tabla).

    Flujo:
      1. wait_update_page navega y espera staleness del DOM anterior.
      2. Segunda espera explícita para container__heading en el nuevo DOM
         (wait_update_page solo detecta staleness, no carga del nuevo DOM).
      3. WebDriverWait(5s) para wcl-tabs que carga de forma asíncrona.
    """
    wait_update_page(driver, standings_url, 'container__heading')
    # Condición personalizada: espera tabs con href válido.
    # presence_of_all_elements_located puede retornar elementos sin href (skeleton),
    # por eso verificamos explícitamente que existan hrefs antes de retornar.
    def tabs_with_hrefs(d):
        elems = d.find_elements(By.XPATH,
            '//div[@data-testid="wcl-tabs" and @data-type="secondary"]/a')
        hrefs = [e.get_attribute('href') for e in elems if e.get_attribute('href')]
        return hrefs if hrefs else False

    try:
        urls = WebDriverWait(driver, 5).until(tabs_with_hrefs)
        tabs = driver.find_elements(By.XPATH,
            '//div[@data-testid="wcl-tabs" and @data-type="secondary"]/a'
        )
        for i, url in enumerate(urls):
            label = tabs[i].find_element(By.XPATH, './/button').text
            print(f'[DIV] tab {i+1}: {label} → {url}')
        return urls
    except Exception:
        print('[DIV] sin divisiones — tabla única')
        return []


def rows_have_text(d):	
	time.sleep(2)
	rows = d.find_elements(By.CLASS_NAME, 'ui-table__row')
	print(len(rows))
	if not rows:
		return False
	return all(r.text.strip() for r in rows)


def get_all_teams_from_standings(driver, standings_url):
	"""
	Wrapper sobre get_teams_info_part1 que soporta ligas con múltiples divisiones.

	Flujo:
		1. Navega a standings_url y busca tabs de división.
		2. Si hay tabs: navega a cada href y espera que las filas tengan texto.
		3. Si no hay tabs: llama get_teams_info_part1 una sola vez sobre la página actual.
		4. Deduplica por team_url (más confiable que team_name — evita variaciones
			de nombre entre tabs para el mismo equipo).

	Retorna dict unificado: { team_name: { team_url, statistics, ... } }
	"""
	# Navega a la página de standings de la liga
	driver.get(standings_url)
	WebDriverWait(driver, 120).until(rows_have_text)
	try:
		# Busca tabs de división (ej: "East", "West", "Conference A")
		# Si no existen en 40s → la liga no tiene divisiones → fallback directo
		tabs_container = WebDriverWait(driver, 40).until(
			EC.presence_of_all_elements_located((
				By.XPATH,
				'//div[@data-testid="wcl-tabs" and @data-type="secondary"]/a'
			))
		)
		# Construye dict { nombre_division: href } desde los elementos encontrados
		tabs = {
			tab.find_element(By.XPATH, './/button[@data-testid="wcl-tab"]').text: tab.get_attribute('href')
			for tab in tabs_container
		}
		print(f'[DIV] {len(tabs)} divisiones encontradas: {list(tabs.keys())}')
	except Exception:
		# Sin tabs de división → extrae equipos directamente de la página actual
		teams = get_teams_info_part1(driver)
		print(f'[DIV] sin divisiones — {len(teams)} equipos encontrados en página única')
		return teams

	seen_urls = set()
	merged    = {}

	for text, href in tabs.items():
		print(f'[DIV] navegando a división "{text}": {href}')
		# Navega a la URL de cada división y espera que las filas carguen con texto
		driver.get(href)
		try:
			WebDriverWait(driver, 120).until(rows_have_text)
		except Exception:
			print(f'[DIV] "{text}" — TEAMS DON\'T FOUND (timeout esperando filas)')
			continue
		# Extrae equipos de esta división y los acumula evitando duplicados por team_url
		try:
			teams = get_teams_info_part1(driver)
		except Exception:
			print(f'[DIV] "{text}" — ERROR extrayendo equipos')			
			teams = {}			
		new_teams = []
		for team_name, team_info in teams.items():
			team_url = team_info.get('team_url', '')
			if team_url and team_url not in seen_urls:
				seen_urls.add(team_url)
				merged[team_name] = team_info
				new_teams.append(team_name)
		print(f'[DIV] "{text}" — {len(new_teams)} equipos nuevos: {new_teams}')

	print(f'[DIV] total acumulado: {len(merged)} equipos en {len(tabs)} divisiones')
	return merged


def teams_creation(driver, list_sports):

	# LOAD DATA SOURCES
	li_file           = 'check_points/leagues_info.json'
	leagues_info_json = load_json(li_file)

	# MAPPING: DB sport names (Title Case) → project sport names (UPPERCASE)
	sport_name_map = {
		'Football': 'FOOTBALL', 'Basketball': 'BASKETBALL', 'Baseball': 'BASEBALL',
		'Hockey': 'HOCKEY', 'Tennis': 'TENNIS', 'Golf': 'GOLF',
		'Boxing': 'BOXING', 'American Football': 'AM._FOOTBALL',
	}
	dict_sport_id = {sport_name_map.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}

	#############################################################
	# 				MAIN LOOP OVER LIST SPORTS 					#
	#############################################################
	for sport_name in list_sports:
		print_section("SPORT: {}".format(sport_name))

		if sport_name not in dict_sport_id or sport_name in ['TENNIS', 'GOLF']:
			print(f'[SKIP] {sport_name} — not in DB or individual sport')
			continue

		sport_id      = dict_sport_id[sport_name]
		dict_teams_db = get_dict_league_ready(sport_id=sport_id)


		for country_league, legue_info in leagues_info_json[sport_name].items():
			add_league_info(sport_name, sport_id, country_league, legue_info)

			# CONTROL DE EXTRACCIÓN — verificar flag en leagues_info.json
			league_cp = legue_info.get('teams_creation', {})
			if not league_cp.get('extract', False):
				print(f'[SKIP] {country_league} — teams_creation.extract=false')
				continue

			# RESUME — nivel equipo: leer último equipo creado para esta liga
			resume_team = league_cp.get('last_team_created', '')
			skip_team   = bool(resume_team)
			if resume_team:
				print(f"[RESUME] {country_league} | Equipo: {resume_team}")

			create_folder('check_points/leagues_season/{}/'.format(sport_name))
			print("#"*30, "START PROCESS LEAGUE {}".format(country_league), "#"*30)

			# SYNC season_id FROM DB
			season_id_db = get_season_id_by_league(legue_info['league_id'])
			if season_id_db:
				legue_info['season_id'] = season_id_db

			# NAVIGATE TO STANDINGS OR DRAW
			url = legue_info.get('standings', legue_info.get('draw'))

			dict_teams_availables      = get_all_teams_from_standings(driver, url)
			dict_country_league_season = {}

			for team_name, team_info_url in dict_teams_availables.items():

				# RESUME — nivel equipo: saltar hasta llegar al checkpoint
				if skip_team:
					if team_name != resume_team:
						print(f"[SKIP TEAM] {team_name}")
						continue
					skip_team = False  # llegamos al equipo del checkpoint

				wait_update_page(driver, team_info_url['team_url'], 'heading')
				dict_team = get_teams_info_part2(driver, legue_info, team_info_url)

				dict_team['country_id'] = get_country_id(dict_team['team_country']) or \
										  insert_country(dict_team['team_country'])

				print_section("dict team")
				print(dict_team)
				team_id = create_team_in_db(dict_teams_db, sport_id, dict_team)

				dict_country_league_season[team_name] = {'team_id': team_id, 'team_url': team_info_url['team_url']}
				league_cp['last_team_created'] = team_name
				save_check_point(li_file, leagues_info_json)

			# Liga completada — reset checkpoint y marcar status
			league_cp['last_team_created'] = ''
			league_cp['status'] = 'completed'
			save_check_point(li_file, leagues_info_json)

			print("#"*30, " TEAMS FROM LEAGUE {} ADDED".format(country_league), "#"*30)
			print("# TEAMS: ", len(dict_country_league_season))
			if dict_teams_availables:
				json_name = 'check_points/leagues_season/{}/{}.json'.format(sport_name, country_league)
				save_check_point(json_name, dict_country_league_season)

