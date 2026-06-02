"""
crear_fixtures_ligas.py — Crear los partidos FIXTURE de ligas sin partidos
==========================================================================
Estrategia (acordada con Jorge): para ligas cuyos equipos NO están creados
(distribución distinta en la sección de equipos), se navega la sección
FIXTURES, se recorre cada match y, entrando al match, se crean los equipos
desde su link + el stadium, y luego se crea el partido.

REUTILIZA bloques YA PROBADOS (no reinventa):
  - fix_null_team_ids.get_or_launch_driver      -> adjunta al driver vivo
  - fix_null_team_ids.get_team_links_from_match -> [home_url, away_url] del match
  - fix_null_team_ids.ensure_team_created       -> crea team + league_team + stadium
  - fix_null_team_ids.load_url_team_cache       -> cache team_url -> team_id
  - milestone4.get_result                       -> lee una fila (name '~', match_url)
  - milestone4.get_time_date_format             -> parsea fecha/hora del fixture
  - data_base.save_math_info / save_details_math_info / save_score_info
  - data_base.check_match_duplicate             -> anti-duplicado

DIFERENCIA con fix_null_team_ids: aquel ARREGLA matches existentes (UPDATE
match_detail); este CREA matches nuevos (save_math_info) desde la sección
fixtures.

REGLAS: driver vivo (no quit), default DRY-RUN (no escribe). DELETE jamás.

Uso:
  env_sports/bin/python crear_fixtures_ligas.py --sport FOOTBALL \
      --leagues "PERU_Liga 1" "VENEZUELA_Liga FUTVE"            # dry-run
  env_sports/bin/python crear_fixtures_ligas.py --sport FOOTBALL \
      --leagues "PERU_Liga 1" --apply                           # escribe en DB
"""
import sys, os, argparse, time, json, subprocess
from collections import Counter
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common_functions import load_json, wait_update_page, dismiss_cookies, generate_uuid
from data_base import (getdb, get_dict_league_ready, check_match_duplicate,
                       save_math_info, save_details_math_info, save_score_info,
                       get_dict_sport_id, get_season_id_by_name, save_season_database,
                       get_country_id, insert_country, get_stadium_id, save_stadium_in_db,
                       get_match_id, strip_phase_suffix)
from milestone4 import get_result, get_time_date_format, get_match_info
from milestone7 import get_live_result          # lector de fila de la vista ALL (detección)
from fix_null_team_ids import (get_or_launch_driver, get_team_links_from_match,
                               ensure_team_created, load_url_team_cache,
                               _reuse_driver_session)
from _debug_pin_insert_dryrun import resolve_league_id   # league_id real por país+nombre

LI_PATH = 'check_points/leagues_info.json'
FIXTURE_POINTS = -1          # convención milestone4 para fixtures (sin jugar)


class _StopAfterFirstTeam(Exception):
    """Señal de PRUEBA: detener tras crear el primer equipo."""


class _Tee:
    """Escribe a varios streams (consola + archivo de log) con flush inmediato,
    para que el log quede completo aunque el proceso termine por excepción."""
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


def load_url_stadium_cache(sport_key, league_key):
    """{team_url: stadium_id} desde el JSON de leagues_season (para equipos ya
    creados / cache hits, así el match igual obtiene su stadium)."""
    try:
        from fix_null_team_ids import _league_season_json_path
        path = _league_season_json_path(sport_key, league_key)
        if not os.path.isfile(path):
            return {}
        data = load_json(path)
        return {info.get('team_url', ''): info.get('stadium_id', '')
                for info in data.values()
                if isinstance(info, dict) and info.get('team_url')}
    except Exception:
        return {}


def read_season_name(driver):
    """Lee el season_name del encabezado de la liga (mismo selector que usa
    milestone2.get_league_data: container__heading -> heading__info)."""
    try:
        heading = driver.find_element(By.CLASS_NAME, 'container__heading')
        return heading.find_element(By.CLASS_NAME, 'heading__info').text.strip()
    except Exception:
        return ''


def ensure_season(driver, league_inf, dry_run):
    """Verifica que la temporada del fixture exista en DB; si no, la crea
    (reusa save_season_database, igual patrón que milestone2.create_leagues).
    Devuelve el season_id correcto a usar para los matches."""
    league_id = league_inf['league_id']
    season_name = read_season_name(driver)
    if not season_name:
        print("    [SEASON] no se pudo leer season_name del encabezado; "
              f"uso season_id de leagues_info: {league_inf['season_id']}")
        return league_inf['season_id']

    existing = get_season_id_by_name(league_id, season_name)
    if existing:
        print(f"    [SEASON] ya existe '{season_name}' -> {existing}")
        return existing

    new_season_id = generate_uuid()
    print(f"    [SEASON] NO existe '{season_name}' para esta liga -> "
          f"{'WOULD CREATE' if dry_run else 'CREATE'} season_id={new_season_id}")
    if not dry_run:
        save_season_database({
            'season_id':    new_season_id,
            'season_name':  season_name,
            'season_end':   datetime.now().date(),
            'season_start': datetime.now().date(),
            'league_id':    league_id,
        })
    return new_season_id


def expand_all_fixtures(driver, max_clicks=40):
    """Hace click en 'Show more matches' hasta cargar TODOS los fixtures futuros.
    Prueba el selector clásico (event__more) y, si no, el botón nuevo por texto
    ('Show more matches'). Repite hasta que el nº de filas deje de crecer."""
    last = -1
    for _ in range(max_clicks):
        rows = len(driver.find_elements(By.CSS_SELECTOR, 'div.event__match'))
        if rows == last:          # el último click no agregó nada -> no hay más
            break
        last = rows
        btns = driver.find_elements(By.CSS_SELECTOR, 'a.event__more, .event__more')
        if not btns:              # fallback: botón/enlace por texto
            btns = [b for b in driver.find_elements(By.CSS_SELECTOR, 'button, a')
                    if 'show more matches' in (b.text or '').lower()]
        if not btns:
            break
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btns[0])
            driver.execute_script("arguments[0].click();", btns[0])
            time.sleep(1.5)
        except Exception:
            break


def scan_fixtures_page(driver, country_id):
    """Lee TODAS las filas de match visibles en la página de fixtures.
    Reusa milestone4.get_result(section='fixtures') -> dict por match con
    name ('home~visitor'), match_date (texto crudo) y link_details (match URL).
    Devuelve una lista de dicts (strings, sin element refs → seguro tras navegar)."""
    # esperar a que carguen las filas (event__match) — wait_update_page solo
    # espera container__heading; sin esto el scan podía dar 0 por timing.
    rows = []
    for intento in range(3):
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div.event__match')))
        except Exception:
            pass
        expand_all_fixtures(driver)
        rows = driver.find_elements(By.CSS_SELECTOR, 'div.event__match')
        if rows:
            break
        print(f"      [FIXTURES] sin filas aún (intento {intento+1}/3)...")
        time.sleep(2)
    fixtures = []
    for row in rows:
        try:
            fixtures.append(get_result(row, country_id=country_id, section='fixtures'))
        except Exception:
            continue
    return fixtures


def detect_match_country_id(driver, fallback_country_id, dry_run):
    """País del match desde la página (tournamentHeader__country, detección que
    ya usaba get_match_info_v2). Si no existe en DB, lo crea (insert_country).
    Devuelve country_id (fallback de la liga si no se detecta)."""
    try:
        txt = driver.find_element(By.XPATH, '//span[@class="tournamentHeader__country"]').text
        country_name = txt.split(':')[0].strip()
    except Exception:
        country_name = ''
    if not country_name:
        return fallback_country_id
    cid = get_country_id(country_name)
    if not cid and not dry_run:
        cid = insert_country(country_name)
        print(f"      [COUNTRY] país creado '{country_name}' -> {cid}")
    if cid:
        print(f"      [COUNTRY] match country '{country_name}' -> {cid}")
        return cid
    print(f"      [COUNTRY] '{country_name}' sin id (dry-run) -> fallback {fallback_country_id}")
    return fallback_country_id


def ensure_match_stadium(driver, country_id, dry_run):
    """Crea el stadium del match SI NO EXISTE (idea principal de Jorge).
    Lee el bloque NUEVO de FlashScore 'Match Information':
      [data-testid="wcl-summaryMatchInformation"] -> wcl-infoLabel / wcl-infoValue
    (labels 'Venue:' / 'Capacity:'). Crea si no existe, reusa si existe."""
    name, capacity = '', 0
    SEL_BLOCK = '[data-testid="wcl-summaryMatchInformation"]'
    SEL_LABEL = SEL_BLOCK + ' [class*="wcl-infoLabel_"]'
    SEL_VALUE = SEL_BLOCK + ' [class*="wcl-infoValue"]'

    # La sección "Match Information" carga lazy y está abajo: scroll + espera +
    # reintentos para que renderice completa antes de leer el VENUE.
    labels, values = [], []
    for intento in range(4):
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL_BLOCK)))
        except Exception:
            pass
        try:
            blk = driver.find_element(By.CSS_SELECTOR, SEL_BLOCK)
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", blk)
        except Exception:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)
        labels = driver.find_elements(By.CSS_SELECTOR, SEL_LABEL)
        values = driver.find_elements(By.CSS_SELECTOR, SEL_VALUE)
        if labels and values:
            break
        print(f"      [STADIUM] Match Information aún no carga (intento {intento+1}/4)...")

    try:
        for lab, val in zip(labels, values):
            key = (lab.text or '').replace(':', '').strip().upper()
            if key == 'VENUE':
                spans = val.find_elements(By.CSS_SELECTOR, 'span')   # 1er span = nombre (2º = ciudad)
                name = (spans[0].text if spans else val.text).strip()
            elif key == 'CAPACITY':
                try:
                    capacity = int(''.join((val.text or '').split()))
                except Exception:
                    capacity = 0
    except Exception as e:
        print(f"      [STADIUM] no se pudo leer Match Information: {e}")
    if not name:
        print("      [STADIUM] sin VENUE en la página -> sin stadium")
        return None
    existing = get_stadium_id(name)
    if existing:
        print(f"      [STADIUM] ya existe '{name}' -> {existing[0]}")
        return existing[0]
    sid = generate_uuid()
    print(f"      [STADIUM] NO existe '{name}' (cap={capacity}) -> "
          f"{'WOULD CREATE' if dry_run else 'CREATE'}")
    if not dry_run:
        save_stadium_in_db({'stadium_id': sid, 'capacity': capacity,
                            'desc_i18n': '', 'name': name, 'photo': ''})
    return sid


def create_match(fixture, league_inf, home_team_id, away_team_id, stadium_id, country_id, dry_run):
    """Crea el match + match_detail (home/visitor) + score. Anti-duplicado por
    (league_id, match_date, name). Devuelve 'created'|'would'|'dup'|'error'."""
    try:
        match_date, start_time = get_time_date_format(fixture['match_date'], section='fixtures')
    except Exception as e:
        print(f"      [ERROR] no se pudo parsear fecha {fixture['match_date']!r}: {e}")
        return 'error'

    if check_match_duplicate(league_inf['league_id'], match_date, fixture['name']):
        print(f"      [DUP] ya existe: {fixture['name']} @ {match_date}")
        return 'dup'

    match_id = generate_uuid()
    match_dict = {
        'match_id':     match_id,
        'country_id':   country_id or league_inf['country_id'],
        'end_time':     None,
        'match_date':   match_date,
        'name':         fixture['name'],
        'place':        '',
        'start_time':   start_time,
        'league_id':    league_inf['league_id'],
        'stadium_id':   stadium_id or None,   # stadium del equipo local (si se pudo)
        'tournament_id': None,
        'rounds':       '',
        'season_id':    league_inf['season_id'],
        'statistic':    None,
        'status':       'SCHEDULED',
    }
    md_home = {'match_detail_id': generate_uuid(), 'home': True,  'visitor': False,
               'match_id': match_id, 'team_id': home_team_id,
               'points': FIXTURE_POINTS, 'score_id': generate_uuid()}
    md_away = {'match_detail_id': generate_uuid(), 'home': False, 'visitor': True,
               'match_id': match_id, 'team_id': away_team_id,
               'points': FIXTURE_POINTS, 'score_id': generate_uuid()}

    # Campos EXACTOS que se insertarían (verificación de prueba):
    print(f"      [MATCH FIELDS] {match_dict}")
    print(f"      [DETAIL home ] {md_home}")
    print(f"      [DETAIL away ] {md_away}")

    if dry_run:
        print(f"      [DRY-RUN] WOULD CREATE match: {fixture['name']} @ {match_date} {start_time} "
              f"| home={home_team_id} away={away_team_id} | stadium_id={match_dict['stadium_id']}")
        return 'would'

    save_math_info(match_dict)
    save_details_math_info(md_home)
    save_details_math_info(md_away)
    save_score_info(md_home)
    save_score_info(md_away)
    print(f"      [CREATED] match {fixture['name']} @ {match_date} (match_id={match_id})")
    return 'created'


# ─── CHECKPOINT por liga (lista de matches persistida + cursor) ─────────────
PROGRESS_DIR = 'check_points/fixtures_progress'


def _progress_path(sport_key, league_key):
    return os.path.join(ROOT, PROGRESS_DIR, sport_key, f"{league_key}.json")


def load_progress(sport_key, league_key):
    path = _progress_path(sport_key, league_key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  [CHECKPOINT] no se pudo leer {path}: {e}")
        return None


def save_progress(prog):
    path = _progress_path(prog['sport_key'], prog['league_key'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(prog, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)   # escritura atómica


def _recompute_last_index(prog):
    """last_index = índice del último match EXTRAÍDO de forma contigua desde el inicio."""
    li = -1
    for idx, m in enumerate(prog['matches']):
        if m.get('done'):
            li = idx
        else:
            break
    prog['last_index'] = li


def process_league(driver, sport_name, league_key, league_info, sport_id,
                   dict_teams_db, dry_run, stats, stop_after_first_team=False,
                   rescan=False):
    fixtures_url = league_info.get('fixtures')
    if not fixtures_url:
        print(f"  [SKIP] {league_key}: sin URL de fixtures en leagues_info")
        stats['leagues_skipped'] += 1
        return

    league_name = league_info.get('league_name') or league_key.split('_', 1)[-1]
    country = league_key.split('_', 1)[0]
    league_inf = {
        'sport_id':    sport_id,
        'sport_name':  sport_name,
        'league_id':   league_info['league_id'],
        'league_name': league_name,
        'season_id':   league_info['season_id'],
        'country_id':  league_info['country_id'],
    }

    print('\n' + '=' * 72)
    print(f"[{sport_name}] {league_key}")
    print(f"  fixtures: {fixtures_url}")

    # league_id REAL desde la DB (el de leagues_info.json puede estar desactualizado
    # y no existir en `league` -> rompía la creación de season/match).
    try:
        con = getdb()
        real_lid, cands = resolve_league_id(con, country, league_name)
    except Exception as e:
        print(f"  [SKIP] {league_key}: error resolviendo league_id en DB: {e}")
        stats['leagues_skipped'] += 1
        return
    if not real_lid:
        print(f"  [SKIP] {league_key}: liga no encontrada en DB (país={country}, "
              f"liga={league_name}). candidatos={cands}")
        stats['leagues_skipped'] += 1
        return
    if real_lid != league_inf['league_id']:
        print(f"  [league_id] JSON={league_inf['league_id']} -> DB real={real_lid} (uso el real)")
    league_inf['league_id'] = real_lid
    print(f"  league_id={league_inf['league_id']} (season_id se resuelve abajo)")

    # ── CHECKPOINT: cargar lista persistida, o escanear (1ª vez / --rescan) ──
    prog = None if rescan else load_progress(sport_name, league_key)
    if prog is None or rescan:
        try:
            wait_update_page(driver, fixtures_url, 'container__heading')
            dismiss_cookies(driver)
        except Exception as e:
            print(f"  [ERROR] navegando fixtures: {e}")
            stats['leagues_skipped'] += 1
            return
        season_id = ensure_season(driver, league_inf, dry_run)
        scanned = scan_fixtures_page(driver, league_inf['country_id'])
        entries = [{'name': f['name'], 'date': f['match_date'], 'url': f['link_details'],
                    'home': f.get('home', ''), 'visitor': f.get('visitor', ''), 'done': False}
                   for f in scanned]
        if prog and rescan:
            # MERGE: agregar SOLO los nuevos (clave name+date). Suelen aparecer al
            # inicio de la lista de fixtures -> se anteponen. Los ya hechos conservan done.
            seen = {(m['name'], m['date']) for m in prog['matches']}
            nuevos = [e for e in entries if (e['name'], e['date']) not in seen]
            prog['matches'] = nuevos + prog['matches']
            prog['season_id'] = season_id or prog.get('season_id')
            prog['league_id'] = real_lid
            print(f"  [RESCAN] +{len(nuevos)} fixtures nuevos (total {len(prog['matches'])})")
        else:
            prog = {'sport_key': sport_name, 'league_key': league_key,
                    'league_id': real_lid, 'season_id': season_id,
                    'matches': entries, 'last_index': -1, 'status': 'pending'}
            print(f"  fixtures detectados: {len(entries)}")
        _recompute_last_index(prog)
        save_progress(prog)
    else:
        hechos = sum(1 for m in prog['matches'] if m.get('done'))
        prog['league_id'] = real_lid
        print(f"  [CHECKPOINT] cargado: {len(prog['matches'])} matches | hechos={hechos} "
              f"| retoma desde índice {prog.get('last_index', -1) + 1}")

    league_inf['season_id'] = prog.get('season_id') or league_inf['season_id']
    stats['fixtures_seen'] += len(prog['matches'])
    url_cache = load_url_team_cache(sport_name, league_key)

    def _mark_done(idx, mm):
        mm['done'] = True
        _recompute_last_index(prog)
        if not dry_run:
            save_progress(prog)   # persistir cursor tras CADA match exitoso

    for i, m in enumerate(prog['matches']):
        if m.get('done'):
            continue   # ya extraído -> sin navegar (resume sin desperdiciar tiempo)
        fx = {'name': m['name'], 'match_date': m['date'], 'link_details': m['url'],
              'home': m.get('home', ''), 'visitor': m.get('visitor', '')}
        print(f"\n  >>> [{i}] {fx['name']}  ({fx['match_date']})  url={fx['link_details']}")

        # red de seguridad: si ya existe en DB (liga+fecha+nombre) -> done sin navegar
        try:
            _md, _ = get_time_date_format(fx['match_date'], section='fixtures')
            if check_match_duplicate(real_lid, _md, fx['name']):
                print("      [DUP] ya existe en DB -> done")
                stats['dup'] += 1
                _mark_done(i, m)
                continue
        except Exception:
            pass

        try:
            wait_update_page(driver, fx['link_details'], 'duelParticipant')
            dismiss_cookies(driver)
        except Exception as e:
            print(f"      [ERROR] navegando al match: {e}")
            stats['errors'] += 1
            continue   # NO marca done -> se reintenta en la próxima corrida

        match_country_id = detect_match_country_id(driver, league_inf['country_id'], dry_run)
        stadium_id = ensure_match_stadium(driver, match_country_id, dry_run)
        home_url, away_url = get_team_links_from_match(driver)
        if not (home_url and away_url):
            print("      [SKIP] no se extrajeron los 2 links de equipo")
            stats['errors'] += 1
            continue

        home_team_id = ensure_team_created(driver, home_url, league_inf, dict_teams_db,
                                           sport_id, dry_run, sport_key=sport_name,
                                           league_key=league_key, url_cache=url_cache)
        if stop_after_first_team:
            print("\n  [TEST] --stop-after-first-team: primer equipo procesado.")
            stats['stopped_test'] += 1
            raise _StopAfterFirstTeam()
        away_team_id = ensure_team_created(driver, away_url, league_inf, dict_teams_db,
                                           sport_id, dry_run, sport_key=sport_name,
                                           league_key=league_key, url_cache=url_cache)
        if not (home_team_id and away_team_id):
            print("      [SKIP] no se pudo crear/obtener uno de los equipos")
            stats['errors'] += 1
            continue

        res = create_match(fx, league_inf, home_team_id, away_team_id,
                           stadium_id, match_country_id, dry_run)
        stats[res] += 1
        if res in ('created', 'dup'):   # 'would' = dry-run, no marca done
            _mark_done(i, m)

    if prog['matches'] and all(m.get('done') for m in prog['matches']):
        prog['status'] = 'completed'
        if not dry_run:
            save_progress(prog)
        print(f"  [CHECKPOINT] liga COMPLETA: {len(prog['matches'])} matches")
    stats['leagues_done'] += 1


# ─── MODO --from-pin: driver con login + detección de ligas con faltantes hoy ──
def ensure_logged_driver(headless=False):
    """Reusa el driver vivo (con login). Si no existe/responde, lanza
    scripts/start_driver.py (crea browser + login) detached y se reconecta."""
    d = _reuse_driver_session()
    if d is not None:
        try:
            _ = d.current_url
            print("[DRIVER] reusando sesión existente (con login)")
            return d
        except Exception:
            print("[DRIVER] la sesión guardada no responde")
    print("[DRIVER] no hay driver usable -> lanzando scripts/start_driver.py (login)...")
    sess = os.path.join(ROOT, 'tmp', 'driver_session.json')
    try:
        os.remove(sess)            # borrar sesión vieja para detectar la nueva
    except Exception:
        pass
    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
    logf = open(os.path.join(ROOT, 'logs', 'start_driver_frompin.log'), 'a')
    subprocess.Popen([sys.executable, 'scripts/start_driver.py'], cwd=ROOT,
                     stdout=logf, stderr=logf, env=os.environ.copy())
    print("[DRIVER] esperando login + sesión (hasta ~120s)...")
    for _ in range(60):
        time.sleep(2)
        if not os.path.isfile(sess):
            continue
        d = _reuse_driver_session()
        if d is not None:
            try:
                _ = d.current_url
                print("[DRIVER] nuevo driver con login listo")
                return d
            except Exception:
                pass
    raise RuntimeError("no se pudo crear el driver con start_driver.py")


def detect_pending_leagues(driver, sport):
    """En la vista ALL del deporte, detecta ligas pineadas con AL MENOS un
    partido de HOY que falta en DB. Devuelve dict {(country, base_league): faltan}."""
    dict_sports_url = load_json('check_points/sports_url_m2.json')
    url = dict_sports_url[sport]
    today = datetime.now().date()
    print(f"\n[FROM-PIN] detectando faltantes de HOY ({today}) en {sport} -> {url}")
    wait_update_page(driver, url, 'container__heading')
    dismiss_cookies(driver)
    for _ in range(12):
        if driver.find_elements(By.CSS_SELECTOR, '[data-testid="wcl-headerLeague"][data-pinned="true"]'):
            break
        time.sleep(1)
    sn = 'soccer' if sport == 'FOOTBALL' else sport.lower()
    rows = driver.find_elements(By.XPATH, f'//div[@class="sportName {sn}"]/div')

    pend = {}
    enable = False
    lc = lname = ''
    for row in rows:
        try:
            row.find_element(By.XPATH, './/span[contains(@class,"headerLeague__title-text")]')
            is_header = True
        except Exception:
            is_header = False
        if is_header:
            enable = False
            try:
                lname = row.find_element(By.XPATH, './/a[@class="headerLeague__title"]').text
                lc = row.find_element(By.XPATH, './/span[@class="headerLeague__category-text"]').text
                pinned = row.find_element(By.XPATH, './/div[@data-testid="wcl-headerLeague"]')
                if pinned.get_attribute('data-pinned') == 'true':
                    enable = True
            except Exception:
                pass
            continue
        if enable:
            try:
                info = get_live_result(row)
            except Exception:
                continue
            mid = get_match_id(lc, lname, today, info['name'])   # ya hace strip de fase
            if not mid:
                base = strip_phase_suffix(lname)
                key = (lc, base)
                pend[key] = pend.get(key, 0) + 1
                print(f"   [FALTA] {lc} / {lname} :: {info['name']}")
    return pend


def main():
    ap = argparse.ArgumentParser(description='Crea fixtures faltantes creando equipos al vuelo')
    ap.add_argument('--sport', default='FOOTBALL', help='Nombre de deporte del proyecto (UPPER)')
    ap.add_argument('--leagues', nargs='+', default=None,
                    help="Claves de liga en leagues_info.json (ej: 'PERU_Liga 1'). "
                         "No requerido si se usa --from-pin")
    ap.add_argument('--from-pin', action='store_true',
                    help='Detecta solo las ligas pineadas con partidos de HOY faltantes '
                         'en DB (driver con login) y extrae sus fixtures')
    ap.add_argument('--apply', action='store_true', help='Escribe en DB (default: dry-run)')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--stop-after-first-team', action='store_true',
                    help='PRUEBA: detiene el script tras crear el primer equipo '
                         '(para verificar los campos insertados)')
    ap.add_argument('--rescan', action='store_true',
                    help='Re-escanea fixtures y MERGEA los nuevos al checkpoint '
                         '(sin perder el progreso ya extraído)')
    args = ap.parse_args()
    dry_run = not args.apply

    # ── LOG a archivo (captura TODO el output, incl. funciones reusadas) ──────
    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    mode = 'dryrun' if dry_run else 'apply'
    log_path = os.path.join(ROOT, 'logs', f'crear_fixtures_{args.sport}_{mode}_{stamp}.log')
    _logf = open(log_path, 'a', encoding='utf-8')
    sys.stdout = _Tee(sys.__stdout__, _logf)
    sys.stderr = _Tee(sys.__stderr__, _logf)
    print(f"[LOG] guardando corrida en: {log_path}")

    # sport_id por nombre de proyecto (DB Title Case -> UPPER vía sport_name_map)
    sp_map = load_json('check_points/sport_name_map.json').get('db_to_project', {})
    dict_sport_id = {sp_map.get(k, k.upper()): v for k, v in get_dict_sport_id().items()}
    sport_id = dict_sport_id.get(args.sport)
    if not sport_id:
        print(f"[ERROR] deporte {args.sport!r} no está en DB. Disponibles: {list(dict_sport_id)}")
        sys.exit(1)

    leagues_info = load_json(LI_PATH)
    # Ligas que NO se pudieron procesar (faltan en DB pero sin entrada/fixtures en
    # leagues_info). NO se ignoran: se reportan fuerte y se persisten para completar.
    pendientes_completar = []

    # ── DRIVER + LISTA DE LIGAS ──────────────────────────────────────────────
    if args.from_pin:
        driver = ensure_logged_driver(headless=args.headless)   # reusa o crea+login
        pend = detect_pending_leagues(driver, args.sport)       # {(país,base): faltan}
        li_sport = leagues_info.get(args.sport, {})
        league_keys = []
        for (co, base) in pend:
            key = f"{co}_{base}"
            if key in li_sport and li_sport[key].get('fixtures'):
                league_keys.append(key)
            else:
                motivo = ('no está en leagues_info.json' if key not in li_sport
                          else 'sin URL de fixtures en leagues_info')
                print(f"  ‼ [INCOMPLETO] '{key}' tiene partidos de HOY FALTANTES en DB "
                      f"pero {motivo} -> NO se pudo extraer. *** DEBE COMPLETARSE LUEGO "
                      f"(crear la liga con completado_de_ligas.py) ***")
                pendientes_completar.append((key, motivo, pend[(co, base)]))
        league_keys = sorted(set(league_keys))
        print(f"\n[FROM-PIN] ligas a extraer (faltantes hoy): {league_keys}")
    else:
        if not args.leagues:
            print("[ERROR] indicá --leagues \"PAIS_Liga\" ... o usá --from-pin")
            sys.exit(1)
        driver = get_or_launch_driver(reuse=True, headless=args.headless)
        league_keys = args.leagues
    print(f"driver: {driver.current_url}")
    dict_teams_db = get_dict_league_ready(sport_id=sport_id)

    stats = Counter()
    print('\n' + '#' * 72)
    print(f"CREAR FIXTURES | sport={args.sport} | dry_run={dry_run} | "
          f"from_pin={args.from_pin} | ligas={league_keys}")
    print('#' * 72)

    for league_key in league_keys:
        info = leagues_info.get(args.sport, {}).get(league_key)
        if not info or not info.get('fixtures'):
            motivo = ('no está en leagues_info.json' if not info
                      else 'sin URL de fixtures en leagues_info')
            print(f"\n  ‼ [INCOMPLETO] {league_key}: {motivo} -> NO se pudo extraer. "
                  f"*** DEBE COMPLETARSE LUEGO (crear la liga con completado_de_ligas.py) ***")
            if (league_key, motivo, 0) not in pendientes_completar and \
               league_key not in [p[0] for p in pendientes_completar]:
                pendientes_completar.append((league_key, motivo, 0))
            stats['leagues_skipped'] += 1
            continue
        try:
            process_league(driver, args.sport, league_key, info, sport_id,
                           dict_teams_db, dry_run, stats,
                           stop_after_first_team=args.stop_after_first_team,
                           rescan=args.rescan)
        except _StopAfterFirstTeam:
            print("\n[TEST] detenido tras el primer equipo (modo prueba). "
                  "Quitá --stop-after-first-team para continuar normal.")
            break
        except Exception as e:
            import traceback
            print(f"[ERROR] liga {league_key}: {type(e).__name__}: {e}")
            traceback.print_exc()
            stats['errors'] += 1

    print('\n' + '#' * 72)
    print('RESUMEN')
    for k in ['leagues_done', 'leagues_skipped', 'fixtures_seen',
              'created', 'would', 'dup', 'errors']:
        print(f"  {k:<16}: {stats[k]}")
    print('#' * 72)

    # ── LIGAS PENDIENTES DE COMPLETAR (NO se ignoran) ────────────────────────
    if pendientes_completar:
        print('\n' + '!' * 72)
        print(f"‼ ATENCIÓN: {len(pendientes_completar)} LIGA(S) CON PARTIDOS FALTANTES QUE "
              f"NO SE PUDIERON EXTRAER — *** COMPLETAR LUEGO ***")
        print("   (crearlas con completado_de_ligas.py para que queden en leagues_info)")
        for key, motivo, faltan in pendientes_completar:
            extra = f" | faltan hoy={faltan}" if faltan else ""
            print(f"   - {key}  ({motivo}){extra}")
        print('!' * 72)
        # persistir para seguimiento
        try:
            pend_path = os.path.join(ROOT, 'check_points', 'fixtures_progress',
                                     f'_PENDIENTES_COMPLETAR_{args.sport}.json')
            os.makedirs(os.path.dirname(pend_path), exist_ok=True)
            with open(pend_path, 'w', encoding='utf-8') as f:
                json.dump([{'league_key': k, 'motivo': m, 'faltan_hoy': fa}
                           for k, m, fa in pendientes_completar], f, ensure_ascii=False, indent=1)
            print(f"[PENDIENTES] guardadas en: {pend_path}")
        except Exception as e:
            print(f"[PENDIENTES] no se pudo guardar el archivo: {e}")

    print('[done] driver vivo intacto.' + ('  (DRY-RUN: no se escribió en DB)' if dry_run else ''))
    print(f"[LOG] corrida guardada en: {log_path}")


if __name__ == '__main__':
    main()
