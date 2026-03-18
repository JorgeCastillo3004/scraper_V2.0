from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import time
from common_functions import *
from data_base import *

# ── Selectores (FlashScore usa clases wcl-* con sufijos aleatorios) ───────────
XPATH_ARTICLES     = '//div[@class="fsNews"]//a[contains(@class,"wcl-article")]'
XPATH_TITLE        = './/*[contains(@class,"wcl-headline") or @role="heading"]'
XPATH_META         = './/*[contains(@class,"wcl-newsMeta")]'
XPATH_IMAGE        = './/figure//img'
SHOW_MORE_ARTICLES = '//span[text()="Show more"]'


# =============================================================================
#  FASE 1 — RECOLECCIÓN DE LINKS Y METADATA DE NOTICIAS
#
#  Objetivo: construir un dict con los datos básicos de cada noticia
#            (link, título, fecha, imagen) sin entrar a cada URL todavía.
#
#  Funciones:
#    1a. get_list_recent_news   — itera el bloque visible en DOM desde last_index
#    1b. click_show_more_news   — expande el DOM clickeando "show more"
#    1c. update_recent_news_found — actualiza el checkpoint de fecha por deporte
# =============================================================================

def get_list_recent_news(driver, max_older_news, last_index, last_date_saved):
	"""
	Itera sobre los bloques de noticias ya cargados en pantalla comenzando
	desde last_index, sin solapamiento con bloques procesados anteriormente.

	Parámetros:
	  driver          — WebDriver activo
	  max_older_news  — días máximos hacia atrás (usado si no hay last_date_saved)
	  last_index      — índice absoluto desde donde continuar en container_news
	  last_date_saved — fecha ISO de la última noticia guardada en DB (o None)

	Retorna:
	  dict_upate_news   — {absolute_index: {title, published, image, news_link}}
	  new_last_index    — posición del último artículo procesado en este bloque
	  enable_more_click — True si aún puede haber noticias válidas más abajo
	"""
	print(f"max_older_news: {max_older_news}  |  last_index: {last_index}  |  last_date_saved: {last_date_saved}")

	# ── 1. SCROLL Y CARGA DEL CONTENEDOR ─────────────────────────────────────
	# Desplaza al fondo para asegurar que el DOM refleje todos los artículos
	# cargados hasta este punto antes de hacer find_elements.
	webdriver.ActionChains(driver).send_keys(Keys.END).perform()
	container_news = driver.find_elements(By.XPATH, XPATH_ARTICLES)
	print(f"  Total artículos en DOM: {len(container_news)}  — procesando desde [{last_index}]")

	# ── 2. LÍMITE TEMPORAL — calculado UNA VEZ antes del loop ────────────────
	# Si existe checkpoint de fecha se usa como frontera exacta; en caso
	# contrario se retrocede max_older_news días desde ahora (UTC).
	if last_date_saved:
		old_date = datetime.strptime(last_date_saved, '%Y-%m-%d %H:%M:%S')
	else:
		old_date = utc_time_naive - timedelta(days=max_older_news)
	print(f"  Fecha límite: {old_date}")

	# ── 3. INICIALIZACIÓN DE RESULTADOS ──────────────────────────────────────
	dict_upate_news   = {}
	enable_more_click = False
	new_last_index    = last_index  # se actualiza con cada noticia válida encontrada

	# ── 4. ITERACIÓN EN BLOQUE (sin solapamiento) ─────────────────────────────
	# container_news[last_index:] garantiza que sólo se procesan artículos nuevos.
	# absolute_index preserva la posición real en el DOM para que el caller
	# pueda continuar exactamente donde este bloque terminó.
	for relative_index, block in enumerate(container_news[last_index:]):
		absolute_index = last_index + relative_index

		# ── 4a. EXTRACCIÓN DE CAMPOS DEL BLOQUE ──────────────────────────────
		news_link      = block.get_attribute('href')
		news_date      = block.find_element(By.XPATH, XPATH_META).text.split('\n')[0].strip()
		news_timestamp = process_date(news_date)  # convierte a UTC naive
		title          = block.find_element(By.XPATH, XPATH_TITLE).text
		try:
			image = block.find_element(By.XPATH, XPATH_IMAGE).get_attribute('src')
		except Exception:
			image = ''
		print(f"  [{absolute_index}] {news_date}  →  {news_timestamp}")

		# ── 4b. VERIFICACIÓN DE FECHA ─────────────────────────────────────────
		# Se resta 1 segundo para tolerar pequeñas imprecisiones en el timestamp
		# reportado por el sitio vs. el almacenado en DB.
		if news_timestamp - timedelta(seconds=1) > old_date:
			# Noticia dentro del rango permitido → se agrega al batch
			image_path_small = img_path(title, folder='images/news/small_images', termination='.avif')
			image_name_file  = image_path_small.split('/')[-1]
			dict_upate_news[absolute_index] = {
				'title':     title,
				'published': news_date,
				'image':     image_name_file,
				'news_link': news_link,
			}
			enable_more_click = True   # puede haber más noticias válidas abajo
			new_last_index    = absolute_index
			print(f"    ✓ agregada  (total batch: {len(dict_upate_news)})")
		else:
			# Noticia fuera del rango → detenemos el procesamiento de este bloque
			enable_more_click = False
			new_last_index    = len(container_news)  # indica al caller que no hay más
			print(f"    ✗ fuera de rango — deteniendo iteración")
			break

	print(f"  Bloque finalizado: {len(dict_upate_news)} noticias  |  new_last_index: {new_last_index}  |  enable_more_click: {enable_more_click}")
	return dict_upate_news, new_last_index, enable_more_click


def make_scroll_to_bottom(driver):
	"""
	Realiza un scroll al fondo de la página para asegurar que el DOM cargue
	todos los artículos disponibles hasta ese punto antes de hacer find_elements.
	"""
	  # ── 2a. SCROLL AL FONDO (con rebote para activar lazy-load) ──────────────────
	driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
	time.sleep(0.5)
	driver.execute_script("window.scrollBy(0, -300);")
	time.sleep(0.3)
	driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
	time.sleep(0.5)

def click_show_more_news(driver, max_older_news, max_click_more=5):
	"""
	Expande la lista del DOM haciendo scroll al fondo y clickeando "show more".
	Repite hasta max_click_more veces o hasta que:
	  - el botón no esté disponible (no hay más contenido), o
	  - la última noticia cargada supere el umbral de antigüedad.

	Parámetros:
	  driver         — WebDriver activo
	  max_older_news — días máximos hacia atrás permitidos
	  max_click_more — número máximo de clics al botón "show more"

	Retorna:
	  container_news — lista actualizada de elementos de noticias en el DOM
	"""
	# ── 1. make scroll to bottom ─────────────────────────────────────────────────────
	make_scroll_to_bottom(driver)
	# ── 2. ESTADO INICIAL ─────────────────────────────────────────────────────
	container_news = driver.find_elements(By.XPATH, XPATH_ARTICLES)
	current_len    = len(container_news)

	if not container_news:
		print("  No hay noticias en el DOM — saliendo")
		return container_news

	print(f"  Noticias iniciales en DOM: {current_len}")

	# ── 3. LOOP DE CARGA ──────────────────────────────────────────────────────
	for click_count in range(1, max_click_more + 1):
		print(f"\n  [CLICK {click_count}/{max_click_more}] — {current_len} noticias actuales")

		# ── 3a. SCROLL AL FONDO ───────────────────────────────────────────────
		# Necesario para que el botón "show more" entre en el viewport y que
		# cualquier lazy-load previo haya terminado antes de intentar el click.
		driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
		time.sleep(0.8)  # pausa mínima para que el DOM se estabilice tras el scroll

		# ── 3b. BUSCAR Y HACER CLICK EN "SHOW MORE" ───────────────────────────
		# Se espera hasta 5 segundos a que el botón sea clickeable.
		# Si no aparece, no hay más contenido disponible y se detiene el loop.
		try:
			show_more_btn = WebDriverWait(driver, 5).until(
				EC.element_to_be_clickable((By.XPATH, SHOW_MORE_ARTICLES))
			)
			show_more_btn.click()
			print(f"    ✓ botón 'show more' clickeado")
		except Exception:
			print(f"    ✗ botón 'show more' no disponible — no hay más contenido")
			break

		# ── 3c. ESPERAR HASTA QUE EL NÚMERO DE NOTICIAS CAMBIE ───────────────
		# Espera activa en lugar de sleep fijo: el loop continúa sólo cuando
		# el DOM confirma que new_len > current_len, con timeout de 10 segundos.
		make_scroll_to_bottom(driver)
		try:
			WebDriverWait(driver, 10).until(
				lambda d: len(d.find_elements(By.XPATH, XPATH_ARTICLES)) > current_len
			)
		except Exception:
			print(f"    ✗ timeout: el DOM no cambió tras el click — deteniendo")
			break

		# ── 3d. ACTUALIZAR CONTADORES ─────────────────────────────────────────
		container_news = driver.find_elements(By.XPATH, XPATH_ARTICLES)
		new_len        = len(container_news)
		print(f"    ✓ {new_len - current_len} noticias nuevas cargadas (total: {new_len})")

		# ── 3e. VERIFICAR FECHA DE LA ÚLTIMA NOTICIA CARGADA ─────────────────
		# Si la noticia más antigua ya supera el umbral de días, no tiene
		# sentido seguir cargando más — todo lo que venga será más viejo aún.
		try:
			last_date_text = container_news[-1].find_element(By.XPATH, XPATH_META).text.split('\n')[0].strip()
			last_timestamp = process_date(last_date_text)
			limit_date     = utc_time_naive - timedelta(days=max_older_news)
			if last_timestamp < limit_date:
				print(f"    — última noticia ({last_date_text}) fuera del rango permitido — deteniendo")
				break
		except Exception:
			pass  # si no se puede leer la fecha se continúa con el siguiente ciclo
		# stop_validate(message = 'Ingresa s para detener el proceso')
		current_len = new_len

	# ── 3. RESULTADO FINAL ────────────────────────────────────────────────────
	# find_elements final garantiza que la lista retornada siempre refleja el
	# estado actual del DOM, independientemente de por dónde se salió del loop.
	container_news = driver.find_elements(By.XPATH, XPATH_ARTICLES)
	print(f"\n  Total noticias tras carga: {len(container_news)}")
	return container_news


def update_recent_news_found(sport_name, last_news_saved, list_upate_news, new_date_update):
	"""
	Actualiza new_date_update con la fecha de la noticia más reciente del batch
	(sólo en la primera llamada con noticias, cuando new_date_update aún está vacío).
	Persiste el checkpoint de fecha por deporte en disco.

	Estructura guardada en last_saved_news.json:
	  { sport_name: { "last_date": "YYYY-MM-DD HH:MM:SS", "phase2": {...} } }

	Retorna new_date_update (actualizado o sin cambios).
	"""
	if new_date_update == '' and len(list_upate_news) != 0:
		new_date_update = process_date(next(iter(list_upate_news.values()))['published'])
		new_date_update = new_date_update.strftime('%Y-%m-%d %H:%M:%S')

		# Asegurar que la entrada del deporte sea un dict (compat. con formato antiguo string)
		if not isinstance(last_news_saved.get(sport_name), dict):
			last_news_saved[sport_name] = {}
		last_news_saved[sport_name]['last_date'] = new_date_update

		save_check_point('check_points/last_saved_news.json', last_news_saved)
		print(f"  Fecha más reciente registrada: {new_date_update}")
	return new_date_update


# =============================================================================
#  FASE 2 — EXTRACCIÓN DE DETALLE DE CADA NOTICIA
#
#  Objetivo: entrar a cada URL recolectada en FASE 1, extraer el cuerpo
#            completo, resumen, imagen y menciones, y guardar en DB.
#
#  Funciones:
#    2a. get_news_info_part2  — extrae campos de una noticia ya abierta en el driver
#    2b. extract_news_info — loop sobre checkpoints JSON, navega y guarda en DB
# =============================================================================

def get_news_info_part2(driver, dict_news):
	"""
	Extrae el cuerpo, resumen, imagen y menciones de una noticia ya abierta
	en el driver. Completa y retorna dict_news con los campos adicionales.
	"""
	wait = WebDriverWait(driver, 10)

	# ── IMAGEN PRINCIPAL ──────────────────────────────────────────────────────
	image     = wait.until(EC.visibility_of_element_located((By.XPATH, '//article//figure//img | //article//img')))
	image_url = image.get_attribute('src')

	# ── RESUMEN (perex) ───────────────────────────────────────────────────────
	summary = driver.find_element(By.XPATH, '//article//*[contains(@class,"fp-perex") or contains(@class,"wcl-news-perex")]')

	# ── CUERPO DEL ARTÍCULO ───────────────────────────────────────────────────
	body      = driver.find_element(By.XPATH, '//article//*[contains(@class,"fp-body") or @itemprop="articleBody"]')
	body_html = body.get_attribute('outerHTML')

	# ── GUARDAR IMAGEN EN DISCO ───────────────────────────────────────────────
	image_path = 'images/news/full_images/' + dict_news['image'].replace('.avif', '.png')
	save_image(driver, image_url, image_path)

	# ── ARMAR DICT COMPLETO ───────────────────────────────────────────────────
	mentions = get_mentions(driver)
	dict_news['news_id']      = generate_uuid()
	dict_news['news_summary'] = summary.text
	dict_news['news_content'] = body_html
	dict_news['image']        = dict_news['image'].replace('.avif', '.png')
	dict_news['news_tags']    = mentions
	return dict_news


def extract_news_info(driver, sport_name, last_news_saved):
	"""
	Lee los archivos JSON de check_points/news/ (generados en FASE 1),
	entra a la URL de cada noticia, extrae los detalles con get_news_info_part2
	y guarda el registro en DB.

	Crea y mantiene un checkpoint de FASE 2 en last_saved_news.json para poder
	reanudar exactamente en el mismo punto si el proceso se interrumpe:
	  { sport_name: { "last_date": "...", "phase2": {
	      "files": [...lista ordenada...],
	      "current_file": "ruta/al/archivo.json",
	      "current_index": N  ← posición dentro del archivo actual
	  }}}
	Al finalizar, elimina la clave "phase2" del checkpoint.
	"""

	# ── 1. PREPARAR LISTA DE ARCHIVOS ORDENADA ───────────────────────────────
	# Los archivos de cada deporte se almacenan en su propia subcarpeta
	# check_points/news/{sport_name}/ para evitar mezcla entre deportes.
	# Se ordena para garantizar un orden determinista en cada ejecución.
	sport_news_dir = f'check_points/news/{sport_name}'
	os.makedirs(sport_news_dir, exist_ok=True)

	file_paths = sorted([
		os.path.join(sport_news_dir, f)
		for f in os.listdir(sport_news_dir)
		if f.endswith('.json')
	])

	if not file_paths:
		print(f"  No hay archivos pendientes en {sport_news_dir}")
		return

	print(f"  Archivos a procesar ({len(file_paths)}): {[os.path.basename(f) for f in file_paths]}")

	# ── 2. INICIALIZAR O RETOMAR CHECKPOINT DE FASE 2 ────────────────────────
	# Asegurar que la entrada del deporte sea un dict
	if not isinstance(last_news_saved.get(sport_name), dict):
		last_news_saved[sport_name] = {'last_date': last_news_saved.get(sport_name)}
	sport_data = last_news_saved[sport_name]
	cp         = sport_data.get('phase2')

	if cp is None or cp.get('files') != file_paths:
		# Primera vez o lista cambió → inicializar checkpoint desde el principio
		cp = {'files': file_paths, 'current_file': file_paths[0], 'current_index': 0}
		sport_data['phase2'] = cp
		save_check_point('check_points/last_saved_news.json', last_news_saved)
		print(f"  Checkpoint FASE 2 inicializado")
	else:
		print(f"  Retomando FASE 2 — archivo: {os.path.basename(cp['current_file'])} | índice: {cp['current_index']}")

	# ── 3. PROCESAR ARCHIVOS ──────────────────────────────────────────────────
	# Saltar archivos ya completados en una ejecución anterior
	start_file_idx = file_paths.index(cp['current_file']) if cp['current_file'] in file_paths else 0

	for file_path in file_paths[start_file_idx:]:
		file_num   = file_paths.index(file_path) + 1
		input_dict = load_check_point(file_path)
		items      = list(input_dict.items())
		print(f"\n  [{file_num}/{len(file_paths)}] {os.path.basename(file_path)} — {len(items)} noticias")

		# En el primer archivo retomado se salta hasta current_index;
		# en los siguientes siempre se empieza desde 0.
		resume_from = cp['current_index'] if file_path == cp['current_file'] else 0

		for list_pos, (index, current_dict) in enumerate(items):
			if list_pos < resume_from:
				continue

			print(f"  - noticia [{list_pos + 1}/{len(items)}]", end=' ')

			# ── Guardar posición ANTES de procesar ───────────────────────────
			# Si el proceso se cae aquí, al reiniciar retomará desde esta noticia.
			cp['current_file']  = file_path
			cp['current_index'] = list_pos
			save_check_point('check_points/last_saved_news.json', last_news_saved)

			# ── Navegar, extraer y guardar en DB (con reintentos) ─────────────
			count_max = 0
			while True:
				try:
					wait_load_detailed_news(driver, current_dict['news_link'])
					print(f"Title: {current_dict['title']}")
					dict_news              = get_news_info_part2(driver, current_dict)
					dict_news['published'] = process_date(dict_news['published'])
					try:
						save_news_database(dict_news)
						print("  ✓ guardado en DB")
					except Exception as e:
						print(f"  Error guardando en DB: {e}")
					break
				except Exception as e:
					print(f'  Reintentando... ({e})')
					if count_max == 3:
						break
					count_max += 1

		# ── Archivo completado: eliminar y avanzar checkpoint al siguiente ────
		os.remove(file_path)
		remaining = [f for f in file_paths if os.path.exists(f)]
		if remaining:
			cp['current_file']  = remaining[0]
			cp['current_index'] = 0
		save_check_point('check_points/last_saved_news.json', last_news_saved)
		# print(f"  ✓ Archivo completado y eliminado: {os.path.basename(file_path)}")

	# ── 4. LIMPIAR CHECKPOINT DE FASE 2 ──────────────────────────────────────
	# Se elimina la clave "phase2" para indicar que no hay trabajo pendiente.
	sport_data.pop('phase2', None)
	save_check_point('check_points/last_saved_news.json', last_news_saved)
	print(f"  ✓ FASE 2 completada para {sport_name}")


# =============================================================================
#  CONTROL DE DUPLICADOS
#
#  Verifica si un título ya fue guardado recientemente para evitar reinserción.
# =============================================================================

def check_enable_add_news(title, last_news_saved_sport):
	"""
	Retorna True si el título no está en la lista de noticias recientes guardadas.
	Usa variables globales para contar coincidencias y limitar la lista de recientes.
	"""
	global count_match, count_recent_news, more_recent_news
	if 'count_match' not in globals():
		count_match, count_recent_news, more_recent_news = 0, 0, []

	enable_save_new = False

	if len(last_news_saved_sport) != 0 and count_match < 3:
		if title in last_news_saved_sport:
			print("Title found in list ")
			enable_save_new = False
			count_match += 1
		else:
			enable_save_new = True
			if count_recent_news < 5:
				more_recent_news.append(title)
				count_recent_news += 1

	if len(last_news_saved_sport) == 0:
		print("NOT PREVIOUS LIST: ")
		enable_save_new = True
		if count_recent_news < 5:
			more_recent_news.append(title)
			count_recent_news += 1

	return enable_save_new


# =============================================================================
#  FUNCIÓN PRINCIPAL
# =============================================================================

def main_extract_news(driver, list_sports, MAX_OLDER_DATE_ALLOWED=31):
	"""
	Orquesta el proceso completo de extracción de noticias por deporte.

	Flujo por deporte:
	  [FASE 1] Navega a la URL, itera noticias en bloques (get_list_recent_news),
	           expande el DOM si hay más contenido (click_show_more_news),
	           guarda cada batch en un checkpoint JSON.
	  [FASE 2] Entra a cada URL recolectada, extrae el detalle completo
	           y persiste el registro en DB (extract_news_info).
	"""
	dict_url_news   = load_json('check_points/sports_url_m1.json')
	last_news_saved = load_check_point('check_points/last_saved_news.json')

	# ── LOOP PRINCIPAL POR DEPORTE ────────────────────────────────────────────
	for sport_name in list_sports:
		news_url = dict_url_news[sport_name]
		print_section(f"NEWS: {sport_name}", space_=50)

		# ── CONDICIÓN DE REANUDACIÓN: FASE 2 INTERRUMPIDA ────────────────────
		# Si existe un checkpoint "phase2" en last_saved_news.json Y hay archivos
		# pendientes en check_points/news/, el proceso anterior se interrumpió
		# durante FASE 2 → saltamos FASE 1 y retomamos directamente desde el
		# punto exacto donde quedó (archivo + índice de noticia).
		sport_data     = last_news_saved.get(sport_name, {})
		has_phase2_cp  = isinstance(sport_data, dict) and 'phase2' in sport_data
		sport_news_dir = f'check_points/news/{sport_name}'
		has_news_files = os.path.isdir(sport_news_dir) and any(
			f.endswith('.json') for f in os.listdir(sport_news_dir)
		)
		if has_phase2_cp and has_news_files:
			print(f"  ⚠ Proceso anterior interrumpido — retomando FASE 2 directamente")
			extract_news_info(driver, sport_name, last_news_saved)
			continue

		# ─────────────────────────────────────────────────────────────────────
		#  FASE 1 — RECOLECCIÓN DE LINKS Y METADATA
		# ─────────────────────────────────────────────────────────────────────

		# ── 1.1 NAVEGACIÓN A LA URL DEL DEPORTE ──────────────────────────────
		print(f"  URL: {news_url}")
		wait_update_page(driver, news_url, "fsNewsSection")

		# ── 1.2 CARGAR CHECKPOINT DE FECHA (última noticia guardada) ─────────
		# Sirve como frontera temporal: sólo se procesan noticias más recientes.
		# Compat. con formato antiguo (string) y nuevo (dict con clave last_date).
		sport_data      = last_news_saved.get(sport_name, {})
		last_date_saved = sport_data.get('last_date') if isinstance(sport_data, dict) else sport_data

		# ── 1.3 ESTADO INICIAL DEL CONTENEDOR ────────────────────────────────
		last_index      = 0
		new_date_update = ''
		container_news  = driver.find_elements(By.XPATH, XPATH_ARTICLES)

		# ── 1.4 LOOP DE PROCESAMIENTO EN BLOQUES ─────────────────────────────
		# Cada iteración procesa el bloque visible actual (desde last_index).
		# Si hay más noticias válidas, se expande el DOM y se repite.
		while last_index < len(container_news):
			start_index = last_index

			# 1.4a — Iterar sobre el bloque visible sin solapamiento
			list_upate_news, last_index, enable_more_click = get_list_recent_news(
				driver, MAX_OLDER_DATE_ALLOWED, last_index, last_date_saved
			)
			print(f"  enable_more_click: {enable_more_click}  |  noticias en batch: {len(list_upate_news)}")

			# 1.4b — Registrar la fecha de la noticia más reciente del primer batch
			new_date_update = update_recent_news_found(
				sport_name, last_news_saved, list_upate_news, new_date_update
			)

			if len(list_upate_news) != 0:
				# 1.4c — Guardar batch de links/metadata en checkpoint JSON
				# Cada deporte tiene su propia subcarpeta dentro de check_points/news/
				# para evitar mezclar archivos entre deportes y facilitar la reanudación.
				sport_news_dir = f'check_points/news/{sport_name}'
				os.makedirs(sport_news_dir, exist_ok=True)
				save_check_point(
					f'{sport_news_dir}/{start_index}_{last_index}.json',
					list_upate_news
				)
				if enable_more_click:
					# 1.4d — Expandir el DOM: click en "show more" y esperar nuevas noticias
					container_news = click_show_more_news(driver, MAX_OLDER_DATE_ALLOWED, max_click_more=5)

			last_index += 1

		# ─────────────────────────────────────────────────────────────────────
		#  FASE 2 — EXTRACCIÓN DE DETALLE Y GUARDADO EN DB
		# ─────────────────────────────────────────────────────────────────────
		# Lee los checkpoints JSON generados en FASE 1, entra a cada URL,
		# extrae el cuerpo completo y persiste el registro en la base de datos.
		extract_news_info(driver, sport_name, last_news_saved)


# =============================================================================
#  INICIALIZACIÓN (primera ejecución)
# =============================================================================

def initial_settings_m1(driver):
	"""
	Crea los archivos de configuración si no existen (sólo primera ejecución).
	  - sports_url_m1.json : URLs de noticias por deporte
	  - CONFIG_M1.json     : deportes habilitados y parámetros generales
	"""
	# ── OBTENER URLS POR DEPORTE ──────────────────────────────────────────────
	if not os.path.isfile('check_points/sports_url_m1.json'):
		driver.get('https://www.flashscore.com/news/football/')
		dict_url_news_m1 = get_sports_links_news(driver)
		save_check_point('check_points/sports_url_m1.json', dict_url_news_m1)

	# ── CONSTRUIR CONFIG_M1 ───────────────────────────────────────────────────
	if not os.path.isfile('check_points/CONFIG_M1.json'):
		dict_url_news_m1  = load_json('check_points/sports_url_m1.json')
		dict_enable_news  = {'SPORTS': {sport: True for sport in dict_url_news_m1.keys()}}
		dict_enable_news['MAX_OLDER_DATE_ALLOWED'] = 31
		save_check_point('check_points/CONFIG_M1.json', dict_enable_news)


# =============================================================================
#  CONFIGURACIÓN GLOBAL
# =============================================================================

CONFIG          = load_json('check_points/CONFIG.json')
database_enable = CONFIG['DATA_BASE']

if __name__ == "__main__":
	driver = launch_navigator('https://www.flashscore.com', database_enable)
	initial_settings_m1(driver)
	login(driver, email_= "FS_EMAIL", password_ = "FS_PASSWORD")
	main_extract_news(driver, ['FOOTBALL'], MAX_OLDER_DATE_ALLOWED = 31)