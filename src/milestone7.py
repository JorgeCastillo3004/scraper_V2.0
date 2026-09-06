from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.common.exceptions import InvalidSessionIdException, WebDriverException
import time
import psycopg2
import shutil
from IPython.display import clear_output

from common_functions import *
from data_base import *
from milestone6 import *
from milestone8 import give_click_on_live
from live_missing import record_missing_league
from live_windows import compute_sport_windows, should_poll, window_label


def get_live_result(row):
	try:
		# work for: FOOTBALL
		home_participant = row.find_element(By.XPATH, './/*[contains(@class, "event__homeParticipant")]').text.strip()
		away_participant = row.find_element(By.XPATH, './/*[contains(@class, "event__awayParticipant")]').text.strip()
	except:
		# work for: BASKETBALL, 
		home_participant = row.find_element(By.XPATH, './/*[contains(@class, "event__participant--home")]').text.strip()
		away_participant = row.find_element(By.XPATH, './/*[contains(@class, "event__participant--away")]').text.strip()

	home_result = row.find_element(By.XPATH, './/*[contains(@class, "event__score--home")]').text.strip()
	away_result = row.find_element(By.XPATH, './/*[contains(@class, "event__score--away")]').text.strip()


	match_id = random_id()
	result_dict = {'match_id':match_id,'match_date':'','start_time':'', 'end_time':'',\
						'name':home_participant + '~' + away_participant,'home':home_participant,'visitor':away_participant,\
						'home_result':home_result,  'visitor_result':away_result, 'place':''}
	return result_dict

# def give_click_on_live(driver, sport_name):
# 	# CLICK ON LIVE BUTTON
# 	if sport_name =='GOLF':
# 		section_title = "Click for player card!"
# 	else:
# 		section_title = "Click for match detail!"

# 	wait = WebDriverWait(driver, 10)
# 	# get list of games section all
# 	xpath_expression_game = '//div[@title="{}"]'.format(section_title)
# 	current_tab = driver.find_elements(By.XPATH, xpath_expression_game)

# 	# give click
# 	xpath_expression = '//div[@class="filters__tab" and contains(.,"LIVE")]'
# 	livebutton = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_expression)))
# 	livebutton.click()
# 	time.sleep(0.3)
# 	# after click, check results or empy page.
# 	try:
# 		nomatchs = driver.find_element(By.CLASS_NAME, 'nmf__title')
# 		print(nomatchs.text)
# 		option = 1
# 	except:		
# 		current_tab = driver.find_elements(By.XPATH, xpath_expression_game)
# 		option = 2

# 	# Continue option 2
# 	if option == 2:
# 		if len(current_tab) == 0:

# 			current_tab = wait.until(EC.presence_of_all_elements_located((By.XPATH, xpath_expression_game)))
# 		# else:
# 		# 	element_updated = wait.until(EC.staleness_of(current_tab[-1]))
# 		return True
# 	else:
# 		return False

def get_live_match(driver, sport_name='FOOTBALL', max_count=10):
	if sport_name=='FOOTBALL':
		sport_name = 'soccer'
	else:
		sport_name = sport_name.lower()		
	
	rows = driver.find_elements(By.XPATH, '//div[@class="sportName {}"]/div'.format(sport_name))
	enable_load = False
	list_match = []
	_leagues_total = 0; _leagues_pinned = 0   # verificación del filtro de pin (logging)
	for index, row in enumerate(rows):
		count = 0
		while count < max_count:
			try:
				try:			
					title = row.find_element(By.XPATH, './/span[contains(@class, "headerLeague__title-text")]').text.strip()			
					enable_load = False
					league_name = row.find_element(By.XPATH, './/a[@class="headerLeague__title"]').text
					league_country= row.find_element(By.XPATH, './/span[@class="headerLeague__category-text"]').text			
					pinned_element = row.find_element(By.XPATH, './/div[@data-testid="wcl-headerLeague"]')
					
					is_pinned = pinned_element.get_attribute("data-pinned") == "true"; _leagues_total += 1; _leagues_pinned += (1 if is_pinned else 0)
					# is_pinned = True # DELETE

					if is_pinned:
						enable_load = True
						# print("PIN ACTIVATED")
					count = max_count
				except:
					# try:
					if enable_load:
						game_results = get_live_result(row)
						game_results['league_name'] = league_name
						game_results['league_country'] = league_country
						game_results['status'] = update_status(row)
						list_match.append(game_results)
					count = max_count
			except:
				count += 1
	if _leagues_total:
		print(f'  [pin] ligas vistas={_leagues_total} pineadas={_leagues_pinned} → partidos en vivo (de pineadas)={len(list_match)}')
	return list_match

def update_status(row, max_count = 10):
	# match_status = row.find_element(By.CLASS_NAME, 'event__stage').text
	count = 0
	match_status = ''
	while count < max_count:
		try:
			match_status = row.find_element(By.XPATH, './/div[@class="event__stage"]').text
			count = max_count
		except:
			time.sleep(1)
			count += 1
	# 'COMPLETED' | 'LIVE' | etiqueta NO-live ('POSTPONED', 'CANCELLED', ...).
	# Antes 'no es Finished' => LIVE, marcando LIVE a partidos aplazados/cancelados.
	return classify_live_status(match_status)
		
# def give_click_on_live_golf(driver):

def live_games(driver, list_sports, interval=60, check_control=None, save_screenshot=None,
			   maybe_recycle=None, sports_provider=None, interval_provider=None):
	dict_sports_url = load_json('check_points/sports_url_m2.json')
	# Mapa deporte PROYECTO (UPPER, ej. 'BASKETBALL') -> deporte DB (sport.name,
	# Title Case, ej. 'Basketball'). Se usa para filtrar get_match_id por deporte y
	# NO confundir ligas homónimas de deportes distintos (TURKEY 'Super Lig' existe
	# en básquet Y fútbol). Si un deporte no está en el mapa -> sport=None (sin filtro).
	_sport_db_map = {v: k for k, v in
					 load_json('check_points/sport_name_map.json').get('db_to_project', {}).items()}
	_shot = save_screenshot if callable(save_screenshot) else (lambda d, l: None)
	_recycle = maybe_recycle if callable(maybe_recycle) else (lambda d: d)
	_get_sports = sports_provider if callable(sports_provider) else (lambda: None)
	_get_interval = interval_provider if callable(interval_provider) else (lambda: None)
	list_sports = list(list_sports)
	_cycle = 0

	while True:
		# Reciclado por memoria (entre ciclos): si el árbol del driver supera el
		# umbral, lo detiene+relanza y devuelve el driver re-enganchado.
		driver = _recycle(driver)

		_cycle += 1
		_new = _get_sports()
		if _new and list(_new) != list_sports:
			print(f'[CICLO {_cycle}] seleccion de deportes actualizada: {list_sports} -> {_new}')
			list_sports = list(_new)
		# Intervalo editable en caliente: se aplica a la pausa del fin de ESTE ciclo.
		_new_iv = _get_interval()
		if _new_iv and _new_iv != interval:
			print(f'[CICLO {_cycle}] intervalo actualizado: {interval}s -> {_new_iv}s')
			interval = _new_iv
		print(f'[CICLO {_cycle}] inicio {datetime.now():%H:%M:%S} — {len(list_sports)} deportes')
		# Fechas en UTC: el scraper persiste match_date/start_time en UTC.
		current_date = datetime.utcnow().date()
		# Ventanas por deporte (RL2): navegar solo deportes con partidos en franja o
		# con un partido LIVE. fail-open: si el cálculo falla -> _windows=None -> pollear todo.
		_windows = compute_sport_windows()

		start_time = time.time()
		for sport_name in list_sports:
			try:
				sport_db = _sport_db_map.get(sport_name)   # nombre DB (ventanas + filtro homónimos)
				if not should_poll(sport_db, _windows):
					print(f'[VENTANA] {sport_name} fuera de ventana {window_label(sport_db, _windows)} — se saltea')
					continue
				wait_update_page(driver, dict_sports_url[sport_name], "container__heading")
				dismiss_cookies(driver)
				_shot(driver, f'live_{sport_name}')

				live_games_found = give_click_on_live(driver, sport_name)

				if live_games_found:
					list_live_match = get_live_match(driver, sport_name=sport_name)
					list_live_match and print(f'[{sport_name}] {len(list_live_match)} partido(s) en vivo:')
					_shot(driver, f'live_{sport_name}_matches')
					for match_info in list_live_match:
						try:
							print(f'  {match_info["home"]} {match_info["home_result"]} - {match_info["visitor_result"]} {match_info["visitor"]}  ({match_info["status"]})')
							# Filtrar por el deporte EN CURSO: así no se matchea/actualiza
							# una liga homónima de otro deporte (evita escrituras erróneas).
							sport_db = _sport_db_map.get(sport_name)   # None si no está en el mapa
							if sport_db is None:
								# NUNCA debería pasar: los 9 deportes están en sport_name_map.json.
								red_box_warning(
									f'LIVE: sport_db=None para sport_name={sport_name!r}',
									['NO se resuelve el partido SIN deporte (evita colision cross-deporte).',
									 f"liga={match_info.get('league_name')!r}  match={match_info.get('name')!r}",
									 'Se SALTEA este partido. El proceso CONTINUA. Revisar sport_name_map.json.'])
								continue
							_status = match_info['status']
							# WORLD CUP: el mismo partido vive en las 7 ligas de confederación
							# (FlashScore lo muestra en todas) → actualizar TODAS las copias, no
							# solo la del país que vemos. Para el resto, comportamiento normal (1).
							_lname = match_info.get('league_name') or ''
							# FlashScore muestra el Mundial como "World Championship"; la BD lo tiene
							# como "World Cup". Reconocer ambos y consultar con el nombre de la BD.
							if ('world cup' in _lname.lower()) or ('world championship' in _lname.lower()):
								match_ids = get_all_match_ids('World Cup', current_date, match_info['name'], sport_db)
							else:
								_one = get_match_id(match_info['league_country'],
									_lname, current_date, match_info['name'], sport=sport_db)
								match_ids = [_one] if _one else []
							if not match_ids:
								print(f'  [DB-SKIP] Partido NO EXISTENTE en la BD (no se actualiza): {match_info["name"]}')
								# Registrar la liga para que Inconsistencias/otro script la extraiga.
								record_missing_league(
									sport_name, match_info.get('league_country'),
									match_info.get('league_name'), match_info.get('name'),
								)
							elif _status not in ('LIVE', 'COMPLETED'):
								# Postponed/Cancelled/Abandoned/Awaiting/etc.: en la BD el estado
								# debe quedar 'SCHEDULED' (NO se marca LIVE ni se toca el score).
								for _mid in match_ids:
									update_match_status({'match_id': _mid, 'status': 'SCHEDULED'})
								print(f'  [NO-LIVE] {match_info["name"]}: FlashScore={_status} '
									  f'-> BD=SCHEDULED ({len(match_ids)} copia/s)')
							else:
								for _mid in match_ids:
									dict_match_detail_id = get_math_details_ids(_mid)
									for match_detail_id, home_flag in dict_match_detail_id.items():
										if home_flag:
											update_score({'match_detail_id': match_detail_id, 'points': match_info['home_result']})
										else:
											update_score({'match_detail_id': match_detail_id, 'points': match_info['visitor_result']})
									update_match_status({'match_id': _mid, 'status': _status})
								print(f'  [OK] {match_info["name"]} | score {match_info["home_result"]}-{match_info["visitor_result"]} | '
									  f'status={_status} | {len(match_ids)} copia/s actualizada/s')
						except Exception as e:
							print(f'  [WARN] {match_info.get("name","?")}: {e}')
							continue

			except InvalidSessionIdException as e:
				# Sesion del driver MUERTA -> que main_live re-adquiera/recicle.
				_shot(driver, f'error_{sport_name}')
				raise
			except WebDriverException as e:
				# Error TRANSITORIO por deporte (overlay que tapa el boton LIVE, timeout,
				# elemento no interactuable, etc.) -> NO reiniciar el driver; omitir este
				# deporte y seguir. Antes se re-lanzaba y causaba cascada de reinicios.
				_shot(driver, f'error_{sport_name}')
				print(f'[WARN] {sport_name}: {type(e).__name__} (omito el deporte, sin reiniciar)')
				continue
			except Exception as e:
				_shot(driver, f'error_{sport_name}')
				print(f'[WARN] {sport_name}: {type(e).__name__}: {e}')
				continue

		elapsed_time = time.time() - start_time
		_check = check_control if callable(check_control) else (lambda d=None: None)
		# Tras recorrer TODOS los deportes, pausar el intervalo COMPLETO del panel
		# (no se descuenta el tiempo de lectura).
		print(f'[CICLO {_cycle}] fin {datetime.now():%H:%M:%S} — leído en {elapsed_time:.0f}s; '
			  f'pausa {interval}s (intervalo del panel) tras recorrer todos los deportes')
		waited = 0
		while waited < interval:
			slice_ = min(2, interval - waited)
			time.sleep(slice_)
			waited += slice_
			_check(driver)
