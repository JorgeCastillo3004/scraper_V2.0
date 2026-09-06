from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
# from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By

from datetime import date, timedelta, datetime
from selenium import webdriver
import random
import string
import requests
import json
import os
import re
import shutil
import time
import uuid

local_time_naive = datetime.now()
utc_time_naive = datetime.utcnow()
time_difference_naive = utc_time_naive - local_time_naive
unable_validate = False

# ── Clasificación del estado del partido (texto de event__stage de FlashScore) ──
# La regla vieja era "si NO dice 'Finished' -> LIVE", lo que marcaba LIVE por error a
# partidos 'Postponed'/'Cancelled'/'Abandoned'/etc. (no están en vivo ni tienen marcador).
# Solo 'LIVE' y 'COMPLETED' deben disparar actualización de score/estado en el flujo live.
_FINISHED_STAGES = {
    'finished', 'after extra time', 'after pen.', 'after penalties',
    'aet', 'ap', 'awarded', 'walkover', 'wo',
}
_NONLIVE_STAGES = {
    'postponed', 'cancelled', 'canceled', 'abandoned', 'interrupted',
    'suspended', 'delayed', 'awaiting', 'awaiting d.', 'to be determined',
    'tbd', 'not started', 'scheduled',
}


def classify_live_status(stage_text):
    """Estado del partido a partir del texto de `event__stage`.
    Devuelve 'COMPLETED', 'LIVE' o la etiqueta NO-live en MAYÚSCULAS ('POSTPONED', ...).
    Cualquier label que no sea finalizado ni no-live se considera 'LIVE' (un partido en
    juego muestra minuto/quarter/inning/set, que no están en ninguna de las listas)."""
    s = (stage_text or '').strip()
    sl = s.lower()
    if sl in _FINISHED_STAGES:
        return 'COMPLETED'
    if sl in _NONLIVE_STAGES:
        return s.upper()
    return 'LIVE'

days = {'monday': 0,
        'tuesday': 1,
        'wednesday': 2,
        'thursday': 3,
        'friday': 4,
        'saturday': 5,
        'sunday': 6}

#####################################################################
#                   CHECK POINTS BLOCK                              #
#####################################################################
def int_folders():
    if not os.path.exists('check_points'):
        os.mkdir('check_points')
    if not os.path.exists('check_points/news/'):
        os.mkdir("check_points/news/")
    if not os.path.exists('check_points/results/'):
        os.mkdir("check_points/results/")
    if not os.path.exists('check_points/fixtures/'):
        os.mkdir("check_points/fixtures/")
    if not os.path.exists('check_points/standings/'):
        os.mkdir("check_points/standings/")
    if not os.path.exists('check_points/leagues_season/'):
        os.mkdir("check_points/leagues_season/")
    if not os.path.exists('check_points/issues/'):
        os.mkdir("check_points/issues/")
    if not os.path.exists('images'):
        os.mkdir("images")
    if not os.path.exists('images/logos'):
        os.mkdir('images/logos')
    if not os.path.exists('images/players'):
        os.mkdir('images/players')
    if not os.path.exists('images/news'):
        os.mkdir("images/news")
    if not os.path.exists('images/news/small_images'):
        os.mkdir("images/news/small_images/")
    if not os.path.exists('images/news/full_images'):
        os.mkdir("images/news/full_images/")
    if not os.path.isfile('check_points/CONFIG.json'):
        CONFIG = {"get_news_m1": True,  # Activate M1
            "sports_link": False,       # 
            "update_links": True,       #
            "get_news": False,          # Get news from each sport
            "DATA_BASE": False}         # Save in data base
        save_check_point('check_points/CONFIG.json', CONFIG)

def get_sports_links_news(driver):
    wait = WebDriverWait(driver, 1)
    buttonmore = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'arrow.topMenuSpecific__moreIcon')))

    mainsports = driver.find_elements(By.XPATH, '//div[@class="topMenuSpecific__items"]/a')

    dict_links = {}

    for link in mainsports[1:]:     
        sport_name = '_'.join(link.text.split())
        sport_url = link.get_attribute('href')
        if sport_name != '':            
            dict_links[sport_name] = sport_url  
    buttonmore.click()

    list_links = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, 'topMenuSpecific__dropdownItem')))
    list_links = driver.find_elements(By.CLASS_NAME, 'topMenuSpecific__dropdownItem')

    for link in list_links:
        sport_name = '_'.join(link.text.split())
        sport_url = link.get_attribute('href')      
        if sport_name == '':
            sport_name = sport_url.split('/')[-2].upper()
        dict_links[sport_name] = sport_url

    buttonminus = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, 'arrow.topMenuSpecific__moreIcon')))
    buttonminus.click()
    return dict_links

def load_json(filename):
    # Opening JSON file
    with open(filename, 'r') as openfile:        
        json_object = json.load(openfile)
    return json_object

def save_check_point(filename, dictionary):
    json_object = json.dumps(dictionary, indent=4)
    with open(filename, "w") as outfile:
        outfile.write(json_object)

def load_check_point(filename):
    # Opening JSON file
    if os.path.isfile(filename):
        with open(filename, 'r') as openfile:        
            json_object = json.load(openfile)
    else:
        json_object = {}
    return json_object

def check_previous_execution(file_path = 'check_points/scraper_control.json'):
    if os.path.isfile(file_path):
        dict_scraper_control = load_json(file_path)
    else:
        dict_scraper_control = {}
    return dict_scraper_control

def launch_navigator_chrome(url, headless = True):
    options = webdriver.ChromeOptions()
    options.add_argument("--disable-application-cache")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    # options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-web-security")
    options.add_argument("--incognito")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")     
    # options.add_experimental_option("excludeSwitches", ["enable-automation"]) ----
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    # options.add_argument('--disable-dev-shm-usage')  ---  
    # chrome_path = os.getcwd()+'/chrome_files'
    # print("chrome_path: ", chrome_path)
    # options.add_argument(r"user-data-dir={}".format(chrome_path))
    # options.add_argument(r"profile-directory=Profile1")

    drive_path = Service('/usr/local/bin/chromedriver')

    driver = webdriver.Chrome(service=drive_path,  options=options)
    driver.get(url)
    return driver

def launch_navigator(url, headless= True, enable_profile=False, lightweight=False, load_images=False,
                     profile_dir=None):
    # load_images=True fuerza la carga de imágenes aunque el driver sea lightweight.
    # Necesario para flujos de CREACIÓN que descargan logos/fotos (p.ej. tenis:
    # get_player_data_tennis → save_image). El modo lightweight por defecto las
    # desactiva para ahorrar RAM (driver de LIVE, que solo lee texto).
    # Resolver geckodriver dinámicamente: PATH primero (cubre el de snap en
    # /snap/bin/geckodriver), luego rutas conocidas. Antes estaba hardcodeado a
    # ~/.cache/selenium, que desaparece al mover/restaurar la máquina.
    geckodriver_path = (
        shutil.which("geckodriver")
        or next((p for p in (
            "/snap/bin/geckodriver",
            "/usr/local/bin/geckodriver",
            "/usr/bin/geckodriver",
        ) if os.path.exists(p)), None)
    )

    # Configurar las opciones del navegador
    options = Options()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-browser-side-navigation')
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    # Silenciar TODO el audio del navegador (ads/clips de FlashScore) en CUALQUIER
    # driver creado, sea lightweight o no. media.volume_scale=0 mutea la salida de
    # audio a nivel del navegador; autoplay.default=5 además bloquea autoplay.
    options.set_preference('media.volume_scale', '0.0')
    options.set_preference('media.autoplay.default', 5)
    if headless:
        print('Mode headless')
        options.add_argument('--headless')
    if lightweight:
        # Modo bajo consumo de RAM (p.ej. driver de LIVE, que solo necesita el TEXTO
        # de los scores). Reduce procesos de contenido y memoria de Firefox.
        if not load_images:
            options.set_preference('permissions.default.image', 2)      # no cargar imágenes/logos/ads
        options.set_preference('fission.autostart', False)              # sin aislamiento por sitio
        options.set_preference('dom.ipc.processCount', 1)               # 1 proceso de contenido
        options.set_preference('browser.sessionhistory.max_total_viewers', 0)  # sin bfcache
        options.set_preference('browser.sessionhistory.max_entries', 1)
        options.set_preference('browser.cache.disk.enable', False)
        options.set_preference('browser.cache.memory.capacity', 32768)  # ~32 MB de caché en memoria
        options.set_preference('media.autoplay.default', 5)             # sin autoplay
        options.set_preference('toolkit.telemetry.enabled', False)
        # --- extras de bajo consumo (2026-06-16): el scraper solo necesita texto/estructura ---
        options.set_preference('webgl.disabled', True)                  # sin WebGL
        options.set_preference('gfx.downloadable_fonts.enabled', False) # sin web fonts
        options.set_preference('dom.serviceWorkers.enabled', False)     # sin service workers
        options.set_preference('network.prefetch-next', False)          # sin prefetch de links
        options.set_preference('network.dns.disablePrefetch', True)     # sin prefetch DNS
        options.set_preference('media.peerconnection.enabled', False)   # sin WebRTC
        options.set_preference('media.cache_size', 0)                   # sin caché de media
        options.set_preference('browser.tabs.unloadOnLowMemory', True)  # descargar tabs en RAM baja
        options.set_preference('places.history.enabled', False)         # sin historial
        options.set_preference('extensions.pocket.enabled', False)
        options.set_preference('reader.parse-on-load.enabled', False)
        options.set_preference('javascript.options.mem.gc_incremental_slice_ms', 10)  # GC más agresivo
    if load_images:
        options.set_preference('permissions.default.image', 1)          # cargar imágenes (creación: logos/fotos)
    if profile_dir:
        # Perfil PERSISTENTE de verdad: `-profile <dir>` hace que Firefox USE ese
        # directorio (no una copia), así cookies y localStorage sobreviven al cierre y
        # el navegador abre ya logueado. Distinto de `enable_profile`, que usa
        # FirefoxProfile(ruta) → COPIA a un temporal y nunca escribe de vuelta.
        # OJO: un directorio de perfil admite UNA instancia a la vez (lock), así que
        # para el hot-swap hacen falta dos perfiles alternados (A/B).
        os.makedirs(profile_dir, exist_ok=True)
        options.add_argument('-profile')
        options.add_argument(profile_dir)
    if enable_profile:
        profile_path = "/home/jorge/.mozilla/firefox/lf4ga6zv.default-release"
        profile = FirefoxProfile(profile_path)
        options.profile = profile
    service = Service(geckodriver_path)
    driver = webdriver.Firefox(service=service, options=options)
    driver.get(url)
    driver.execute_script("document.body.style.zoom='50%'")
    return driver

def login(driver, email_="FS_EMAIL", password_="FS_PASSWORD", max_attempts=3):
    """
    Login robusto en FlashScore.
    - Reintenta hasta max_attempts veces si cualquier paso falla
    - Usa JS click como fallback si el click normal está bloqueado
    - Recarga la página entre intentos para partir de estado limpio
    - Verifica que la sesión quedó activa al final
    """
    wait = WebDriverWait(driver, 15)
    wait_short = WebDriverWait(driver, 10)

    def safe_click(element):
        """Click normal con fallback a JavaScript si hay overlay bloqueando."""
        try:
            element.click()
        except Exception:
            driver.execute_script("arguments[0].click();", element)

    def send_esc():
        try:
            webdriver.ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

    for attempt in range(1, max_attempts + 1):
        try:
            print(f"  [Login] Intento {attempt}/{max_attempts}...")

            # Aceptar cookies si aparece el banner (timeout corto para no bloquear)
            try:
                accept_btn = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
                )
                safe_click(accept_btn)
                time.sleep(0.5)
            except Exception:
                pass  # Banner ya aceptado o no apareció

            # Click en LOGIN
            login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[text()='LOGIN']")))
            safe_click(login_button)

            # Seleccionar modo email
            continue_email = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[span[text()='Continue with email']]")
            ))
            safe_click(continue_email)

            # Email
            email_field = wait.until(EC.visibility_of_element_located((By.ID, 'email')))
            email_field.clear()
            email_field.send_keys(email_.strip())

            # Password
            passwd_field = wait.until(EC.visibility_of_element_located((By.ID, 'passwd')))
            passwd_field.clear()
            passwd_field.send_keys(password_)

            # Enviar formulario: primero intenta click en el botón, luego Enter como fallback
            try:
                login_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(
                    (By.XPATH, '//button[contains(translate(., "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"), "LOG IN")]')
                ))
                safe_click(login_btn)
            except Exception:
                passwd_field.send_keys(Keys.RETURN)

            # Verificar sesión activa — header__text--loggedIn aparece si el login fue exitoso
            try:
                wait_short.until(EC.presence_of_element_located((By.XPATH, '//*[contains(@class,"header__text--loggedIn")]')))
                print(f"  [Login] Exitoso en intento {attempt}\n")
                driver.execute_script("document.body.style.zoom='50%'")
                send_esc()
                time.sleep(0.5)
                return  # ← login OK, salir
            except Exception:
                error_els = driver.find_elements(
                    By.XPATH, '//*[contains(@class,"error") or contains(@class,"alert")]'
                )
                error_text = ' | '.join([e.text for e in error_els if e.text.strip()])
                raise Exception(f"Sesión no activa tras submit. Mensaje: {error_text or 'sin detalle'}")

        except Exception as e:
            print(f"  [Login] Intento {attempt} fallido: {e}")
            if attempt < max_attempts:
                print(f"  [Login] Recargando página antes de reintentar...")
                send_esc()
                try:
                    driver.get('https://www.flashscore.com')
                    time.sleep(3)
                except Exception:
                    pass
            else:
                raise RuntimeError(
                    f"Login fallido tras {max_attempts} intentos. Último error: {e}"
                )

# ── Sesión de FlashScore reutilizable (abrir el navegador ya logueado) ────────
# El login por formulario es el paso más caro y frágil del arranque de un driver
# (hasta 3 intentos, banner de cookies, ~30-60 s) y repetirlo seguido —p.ej. en cada
# reciclaje del driver de live— es justo lo que conviene evitar. La sesión de
# FlashScore vive en las cookies (+ localStorage) del dominio, así que se guardan
# tras un login bueno y se re-inyectan en el driver nuevo: abre y ya está dentro.
#
# Por qué NO un perfil de Firefox persistente (`-profile`): un directorio de perfil
# admite UNA instancia a la vez (lock de Firefox) y el hot-swap tiene el navegador
# viejo y el nuevo vivos a la vez → el segundo no arrancaría. Además `enable_profile`
# usa FirefoxProfile(ruta), que COPIA el perfil a un temporal y nunca escribe de
# vuelta, así que tampoco persistiría nada. El JSON de sesión no tiene ese límite.

FS_URL = 'https://www.flashscore.com'
FS_SESSION_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tmp', 'fs_session.json')


def is_logged_in(driver, timeout=8):
    """True si la sesión de FlashScore está activa. Usa el MISMO marcador que login()
    para verificar el submit (`header__text--loggedIn`), así ambos caminos coinciden."""
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located(
            (By.XPATH, '//*[contains(@class,"header__text--loggedIn")]')))
        return True
    except Exception:
        return False


def dump_fs_session(driver):
    """Cookies + localStorage del dominio de FlashScore tal como los tiene `driver`."""
    if 'flashscore' not in (getattr(driver, 'current_url', '') or ''):
        driver.get(FS_URL)
    try:
        storage = driver.execute_script(
            'var o={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);'
            'o[k]=localStorage.getItem(k);}return o;') or {}
    except Exception:
        storage = {}
    return {'cookies': driver.get_cookies(), 'storage': storage,
            'saved_at': datetime.now().isoformat()}


def save_fs_session(driver, path=FS_SESSION_FILE):
    """Persiste la sesión a disco (para arranques en frío). Devuelve el dict guardado."""
    data = dump_fs_session(driver)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f'  [Sesión] guardada en {path} ({len(data["cookies"])} cookies)')
    except Exception as e:
        print(f'  [Sesión] no se pudo guardar ({type(e).__name__}: {e})')
    return data


def load_fs_session(path=FS_SESSION_FILE):
    """Lee la sesión de disco; None si no hay o está corrupta."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if data.get('cookies') else None
    except Exception:
        return None


def apply_fs_session(driver, data):
    """Inyecta cookies + localStorage en `driver` y recarga. True si la sesión quedó
    activa. No lanza: si algo falla, el llamador cae al login normal."""
    if not data or not data.get('cookies'):
        return False
    try:
        if 'flashscore' not in (getattr(driver, 'current_url', '') or ''):
            driver.get(FS_URL)          # add_cookie exige estar ya en el dominio
        for c in data['cookies']:
            c = dict(c)
            c.pop('sameSite', None)     # Firefox rechaza algunos valores al re-inyectar
            if c.get('expiry') is not None:
                c['expiry'] = int(c['expiry'])
            try:
                driver.add_cookie(c)
            except Exception:
                c.pop('domain', None)   # 2º intento: dejar que lo infiera del dominio actual
                try:
                    driver.add_cookie(c)
                except Exception:
                    pass
        for k, v in (data.get('storage') or {}).items():
            try:
                driver.execute_script('localStorage.setItem(arguments[0], arguments[1]);', k, v)
            except Exception:
                pass
        driver.get(FS_URL)              # recargar ya con la sesión puesta
        return is_logged_in(driver)
    except Exception as e:
        print(f'  [Sesión] no se pudo restaurar ({type(e).__name__}: {e})')
        return False


def ensure_login(driver, email_=None, password_=None, path=FS_SESSION_FILE, session=None):
    """Deja `driver` logueado gastando lo menos posible, en este orden:
      1. ya logueado           -> refresca el JSON de sesión y listo
      2. sesión reutilizable   -> la inyecta (sin formulario);  `session` permite pasar
         la del driver VIEJO en un hot-swap (más fresca que la de disco)
      3. login por formulario  -> y guarda la sesión para la próxima
    Devuelve 'already' | 'restored' | 'login'. Propaga el error solo si el login falla."""
    if is_logged_in(driver, timeout=6):
        save_fs_session(driver, path)
        return 'already'
    if apply_fs_session(driver, session or load_fs_session(path)):
        print('  [Sesión] restaurada sin login (cookies reutilizadas)')
        return 'restored'
    print('  [Sesión] no reutilizable — login por formulario')
    login(driver, email_=email_, password_=password_)
    save_fs_session(driver, path)
    return 'login'


def dismiss_cookies(driver):
    """Cierra el banner de cookies de OneTrust si está visible."""
    try:
        btn = WebDriverWait(driver, 3).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        driver.execute_script("arguments[0].click();", btn)
    except Exception:
        pass


def wait_update_page(driver, url, class_name):

    wait = WebDriverWait(driver, 10)
    current_tab = driver.find_elements(By.CLASS_NAME, class_name)
    driver.get(url)

    if len(current_tab) == 0:
        current_tab = wait.until(EC.presence_of_all_elements_located((By.CLASS_NAME, class_name)))
    else:
        element_updated = wait.until(EC.staleness_of(current_tab[0]))   

def wait_load_detailed_news(driver, url_news):  
    wait = WebDriverWait(driver, 10)
    class_name = 'fsNews'
    title = driver.find_elements(By.CLASS_NAME, class_name)
    driver.get(url_news)
    if len(title) == 0:
        title = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, class_name)))
    else:
        wait.until(EC.staleness_of(title[0]))

def get_mentions(driver):
    mention_list = ''
    mentions = driver.find_elements(By.XPATH, '//article//div[contains(@class,"wcl-group")]//a')
    for mention in mentions:
        text = mention.text.strip()
        if not text:
            continue
        if mention_list == '':
            mention_list = text
        else:
            mention_list = mention_list + ', ' + text
    return mention_list

def save_image(driver, image_url, image_path):
    print("image_path: ", image_path)
    img_data = requests.get(image_url).content

    with open(image_path, 'wb') as handler:
        handler.write(img_data)

def process_date(date):
    date_format = "%d.%m.%Y %H:%M:%S"
    local_time_now = datetime.now()
    if 'min ago' in date:
        min_ = int(re.findall(r'(\d+)\ min ago', date)[0])
        news_time_post = local_time_now - timedelta(minutes=min_)
    elif ' h ago' in date:
        hours_ = int(re.findall(r'(\d+)\ h ago', date)[0])
        news_time_post = local_time_now - timedelta(hours=hours_)
    elif 'Yesterday' in date:
        previous_day = local_time_now - timedelta(days=1)
        time_post = re.findall(r'\d+:\d+', date)[0]+':00'
        time_post = datetime.strptime(time_post, "%H:%M:%S")
        news_time_post = datetime(
            previous_day.year,
            previous_day.month,
            previous_day.day,
            time_post.hour,
            time_post.minute,
            time_post.second,
        )
    elif 'Just now' in date:
        news_time_post = local_time_now
    else:       
        date = date +':00'
        news_time_post = datetime.strptime(date, date_format)   

    news_utc_time = news_time_post + time_difference_naive
    return news_utc_time

def random_name(folder = 'news_images', termination = '.jpg'):
    file_name = ''.join(random.choice(string.ascii_lowercase) for i in range(16))
    return os.path.join(folder,file_name + termination)

def img_path(title, folder = 'news_images',termination = '.jpg'):
    title = title[0:20].replace(' ','_')
    return os.path.join(folder,title + termination)

def random_name_logos(league_team, folder = 'news_images', termination = '.jpg'):
    file_name = ''.join(random.choice(string.ascii_lowercase) for i in range(4))
    digits = ''.join([str(random.randint(0, 9)) for i in range(1)])
    file_name = '_' + file_name + digits
    league_team = '_'.join(league_team.replace('-', '_').replace('/', '_').lower().split())
    return os.path.join(folder,(league_team) + file_name + termination)

def random_id():
    # rand_id = ''.join(random.choice(string.ascii_lowercase) for i in range(4))
    # rand_id = rand_id + str(random.choice([0, 9]))
    # digits = ''.join([str(random.randint(0, 9)) for i in range(4)])
    # return rand_id+digits
    return str(uuid.uuid4())

def generate_uuid():    
    return str(uuid.uuid4())

def random_id_text(textinput):
    # textinput = textinput.replace(' ', '')
    # unique_code = 0
    # for char in textinput:
    #     unique_code = unique_code*6 + ord(char)
    # unique_code = str(unique_code)    
    # if len(unique_code) < 10:        
    #     unique_code = (10 - len(unique_code))*'0' + unique_code        
    # else:
    #     unique_code = unique_code[-10:]
    # return unique_code
    return str(uuid.uuid4())

def generate_uuid_text(textinput):
    """Deterministic UUID from text using UUID5 (NAMESPACE_DNS)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(textinput)))

def random_id_short():
    rand_id = ''.join(random.choice(string.ascii_lowercase) for i in range(4))
    digits = ''.join([str(random.randint(0, 9)) for i in range(4)])
    return rand_id+digits

def stop_validate(message = ''):
    global unable_validate
    print_section(message)
    if unable_validate:
        return None
    user_input = input("Type y to continue s to stop: ")
    if user_input == 'y':
        return True
    if user_input == 's':
        print(stop)
    if user_input == 'continue':
        unable_validate = True

def stop_validate2(message = ''):
    print_section(message)
    user_input = input("Type y to continue s to stop: ")
    if user_input == 'y':
        return True
    if user_input == 's':
        print(stop)

def print_section(section, space_ = 50):
    line_sport = "#" + " "*(space_ - int(len(section)/2)) + section + " "*(space_ - int(len(section)/2)) + "#"
    print('\n')
    print("#"*len(line_sport))
    print(line_sport)
    print("#"*len(line_sport), '\n')

def clean_field(text):
    return text.replace("'", "\''")

def clean_text(text):
    return ' '.join(text.split())

def execute_section(execution_schedule, day_execution, execute_ready):
    # global day_execution, execute_ready
    enable_execution = False    
    if 'montly' in execution_schedule and not execute_ready:
        interval, day_exe, time_str = execution_schedule.split("|")
        if datetime.now().day == day_exe:
            time_execution = datetime.strptime(time_str, '%H:%M:%S')
            if datetime.now().time() > time_execution.time() and datetime.now().time() < (time_execution + timedelta(minutes=1)).time():
                # print(time_execution)
                enable_execution = True
                execute_ready = True

    if 'weekly' in execution_schedule and not execute_ready:
        interval, day_exe, time_str = execution_schedule.split("|")
        time_execution = datetime.strptime(time_str, '%H:%M:%S')
        # print("time_execution: ", time_execution, type(time_execution))
        if datetime.now().weekday() == days[day_exe] and datetime.now().time() > time_execution.time() and datetime.now().time() < (time_execution + timedelta(minutes=1)).time():
            enable_execution = True
            execute_ready = True
            day_execution = datetime.now().day

    if 'daily' in execution_schedule and not execute_ready:     
        # print("Case daily")
        _, time_str = execution_schedule.split("|")     
        time_execution = datetime.strptime(time_str, '%H:%M:%S')
        if datetime.now().time() >= time_execution.time() and datetime.now().time() < (time_execution + timedelta(minutes=1)).time():
            enable_execution = True
            execute_ready = True
            day_execution = datetime.now().day
    
    if datetime.now().day != day_execution:     
        execute_ready = False
        day_execution = -1

    #################################################################
    #           SECTION SECONDS-MINUTES                             #
    #################################################################
    if 'minute' in execution_schedule:
        # print("Case daily")
        part1, time_str = execution_schedule.split("|")     
        time_execution = datetime.strptime(time_str, '%H:%M:%S')
        if datetime.now().time() >= time_execution.time() and datetime.now().time() < (time_execution + timedelta(minutes=1)).time():
            enable_execution = True
            execute_ready = False
            time_execution = time_execution + timedelta(minutes=1)
            execution_schedule = part1 +'|'+str(time_execution.time())          
            # day_execution = datetime.now().day
    if 'seconds' in execution_schedule:
        
        if len(execution_schedule.split("|")) == 2:
            part1, seconds_str = execution_schedule.split("|")          
            option = 1
        if len(execution_schedule.split("|")) == 3:
            part1, seconds_str, time_str = execution_schedule.split("|")
            option = 2
        
        if option == 1:         
            time_execution = datetime.now()         
            enable_execution = True
            execute_ready = False               
            time_execution = time_execution + timedelta(seconds = int(seconds_str))
            execution_schedule = part1 +'|' + seconds_str +'|'+ time_execution.time().strftime('%H:%M:%S')          
                
        if option == 2:
            time_execution = datetime.strptime(time_str, '%H:%M:%S')            
            if datetime.now().time() >= time_execution.time() and datetime.now().time() < (time_execution + timedelta(seconds = 10)).time():
                enable_execution = True
                execute_ready = False
                time_execution = time_execution + timedelta(seconds = int(seconds_str))             
                execution_schedule = part1 +'|' + seconds_str +'|'+ time_execution.time().strftime('%H:%M:%S') 
                

        # print("Salida de la funcion: ", "#"*30)
        # print("enable_execution: ", enable_execution, "Current time: ", datetime.now().time(), "execution_schedule: ", execution_schedule)
            

    return enable_execution, day_execution, execute_ready, execution_schedule

def update_data(folder = ''):
    file_path = os.path.join(folder, 'execution_control.json')
    with open(file_path, 'r') as file:
        section_schedule = json.load(file)
    return section_schedule

def f1_puntuation(posicion_str):
    try:
        posicion = int(posicion_str.rstrip('.'))
    except:
        posicion = 0
    if posicion == 1:
        return 25
    elif posicion == 2:
        return 18
    elif posicion == 3:
        return 15
    elif posicion == 4:
        return 12
    elif posicion == 5:
        return 10
    elif posicion == 6:
        return 8
    elif posicion == 7:
        return 6
    elif posicion == 8:
        return 4
    elif posicion == 9:
        return 2
    elif posicion == 10:
        return 1
    else:
        return 0

def store_league_info(sport_name, league_name, number_matches, n_teams_league, sports_data):
    """
    Stores or updates league information under a sport key.
    
    Structure:
    {
        "Football": {
            "Premier League": {
                "number_matches": 120,
                "date": "2025-10-05",
                "enable": True
            }
        }
    }
    """
    current_date = date.today().isoformat()

    # Initialize the sport key if it doesn't exist
    if sport_name not in sports_data:
        sports_data[sport_name] = {}

    enable_flag = False

    # Store or update league information check if it was created previously
    if league_name in sports_data[sport_name].keys():
        sports_data[sport_name][league_name]['number_matches'] = number_matches
        sports_data[sport_name][league_name]['date'] = current_date
        sports_data[sport_name][league_name]['number_teams'] = n_teams_league
        sports_data[sport_name][league_name]['enable'] = enable_flag        
    else:
        sports_data[sport_name][league_name] = {
            "number_matches": number_matches,
            "date": current_date,
            "number_teams":n_teams_league,
            "enable": enable_flag
        }
    return sports_data

def enable_league(global_check_point, sport_name, league_name, stage='M4',section='results'):
    print_section(" ENABLE LEAGUE: ")
    print(global_check_point[sport_name])
    if not section in global_check_point[sport_name][stage]:
        global_check_point[sport_name][stage][section] = {}
        global_check_point[sport_name][stage][section]['league'] = ''
        global_check_point[sport_name][stage][section]['round'] = ''
        global_check_point[sport_name][stage][section]['match_name'] = ''
        return True
    if global_check_point[sport_name][stage][section]['league'] == '':
        print_section("ENABLE LEAGUE")
        return True
    if global_check_point[sport_name][stage][section]['league'] == league_name:
        print_section("ENABLE LEAGUE")
        return True
    else:
        return False
    
def round_files_exist(sport_name, league_name, name_section):
    """
    Verifica si la carpeta existe y no está vacía.
    Retorna True si existe y contiene archivos, False en caso contrario.
    """
    folder = os.path.join("check_points", name_section, league_name)

    # Verificar si existe y es un directorio
    if os.path.isdir(folder):
        # Verificar si contiene archivos
        return len(os.listdir(folder)) > 0
    return False

def is_checkpoint_reached(checkpoint_value, current_value):
    """Returns True if current_value is the resume point or no checkpoint exists."""
    return checkpoint_value == '' or checkpoint_value == current_value
    
def enable_match(global_check_point, sport_name, section, match_name):
    if global_check_point[sport_name]['M4'][section]['match_name'] == '':
        return True
    if global_check_point[sport_name]['M4'][section]['match_name'] == match_name:
        print_section("ENABLE MATCH")        
        return True
    else:
        return False


def get_resume_point(global_check_point, sport_name, milestone='M3', section=None):
    """
    Retorna el punto de reanudación (liga, equipo/partido) para un deporte dado.
    Si no existe checkpoint previo retorna strings vacíos → inicio desde cero.

    Args:
        section (str|None): Clave de subsección dentro del milestone (ej: 'results', 'fixtures').
                            Usar solo en M4 donde el checkpoint tiene un nivel extra.
    """
    m = global_check_point.get(sport_name, {}).get(milestone, {})
    if section is not None:
        m = m.get(section, {})
    return m.get('league', ''), m.get('team_name', '')


def update_resume_point(global_check_point, sport_name, league, team_name, milestone='M3'):
    """Persiste el punto de reanudación actual en global_check_point.json."""
    global_check_point.setdefault(sport_name, {})[milestone] = {
        'sport': sport_name, 'league': league, 'team_name': team_name
    }
    save_check_point('check_points/global_check_point.json', global_check_point)


def red_box_warning(title, detail_lines=None):
    """Imprime una ADVERTENCIA en CUADRO ROJO (ANSI) y CONTINÚA (no detiene el
    proceso). Para condiciones que NUNCA deberían ocurrir, p.ej. resolver un
    partido/liga SIN filtro de deporte (riesgo de colisión cross-deporte:
    ligas homónimas en deportes distintos, ej. WORLD 'World Cup' en fútbol y
    básquet). Si esta caja aparece en los logs, hay un caller a corregir."""
    RED = '\033[1;31m'; RESET = '\033[0m'
    lines = [str(title)] + [str(l) for l in (detail_lines or [])]
    width = max([len(s) for s in lines] + [len('ADVERTENCIA - NO DEBERIA OCURRIR NUNCA')]) + 2
    bar = '═' * width
    try:
        print(RED + '╔' + bar + '╗')
        print('║' + 'ADVERTENCIA - NO DEBERIA OCURRIR NUNCA'.center(width) + '║')
        print('╠' + bar + '╣')
        for s in lines:
            print('║ ' + s.ljust(width - 1) + '║')
        print('╚' + bar + '╝' + RESET, flush=True)
    except Exception:
        # Nunca romper por un fallo de impresión de la advertencia.
        print('[ADVERTENCIA-NO-DEBERIA-OCURRIR] ' + ' | '.join(lines), flush=True)


int_folders()
