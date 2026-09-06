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
import sys, os, argparse, time, json, subprocess, re
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
from milestone4 import get_result, get_time_date_format, get_match_info, get_statistics_game
from milestone7 import get_live_result          # lector de fila de la vista ALL (detección)
from fix_null_team_ids import (get_or_launch_driver, get_team_links_from_match,
                               ensure_team_created, load_url_team_cache,
                               _reuse_driver_session)
from _debug_pin_insert_dryrun import resolve_league_id   # league_id real por país+nombre

LI_PATH = 'check_points/leagues_info.json'
FIXTURE_POINTS = -1          # convención milestone4 para fixtures (sin jugar)

_DB_SPORT_NAME = None
def _db_sport_name(sport_project):
    """Nombre de deporte como lo guarda la DB (sport.name, Title Case) a partir del
    nombre de PROYECTO (UPPER, ej. 'BASKETBALL' -> 'Basketball'). Sirve para filtrar
    los lookups por deporte y NO confundir ligas homónimas de deportes distintos
    (p.ej. TURKEY tiene 'Super Lig' en básquet Y en fútbol). Devuelve None si el
    deporte no está en el mapa -> el lookup queda sin filtro (comportamiento previo)."""
    global _DB_SPORT_NAME
    if _DB_SPORT_NAME is None:
        _DB_SPORT_NAME = {v: k for k, v in
                          load_json('check_points/sport_name_map.json').get('db_to_project', {}).items()}
    return _DB_SPORT_NAME.get(sport_project)


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
    clicks = 0
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
            clicks += 1
            time.sleep(1.5)
            nuevos = len(driver.find_elements(By.CSS_SELECTOR, 'div.event__match'))
            print(f"      [MOSTRAR MAS] click #{clicks} -> {nuevos} partidos cargados "
                  f"(+{nuevos - last})")
        except Exception:
            break
    total = len(driver.find_elements(By.CSS_SELECTOR, 'div.event__match'))
    if clicks:
        print(f"      [FIXTURES] 'mostrar mas' completado: {clicks} clicks -> "
              f"{total} partidos en total")
    else:
        print(f"      [FIXTURES] sin boton 'mostrar mas' -> {total} partidos visibles")
    return total


def scan_fixtures_page(driver, country_id, section='fixtures'):
    """Lee TODAS las filas de match visibles en la página de fixtures/results.
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
            fixtures.append(get_result(row, country_id=country_id, section=section))
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


def _parse_md(raw, section):
    """Parsea la fecha del match. Primero usa get_time_date_format (formatos con
    hora/año). En results los partidos RECIENTES vienen como 'DD.MM.' (SIN hora ni
    año) que ese parser no maneja -> fallback robusto: regex 'DD.MM.[YYYY] [HH:MM]',
    año = año UTC actual si no viene. Devuelve (match_date, start_time)."""
    raw = (raw or '').strip()
    try:
        return get_time_date_format(raw, section=section)
    except Exception:
        pass
    if section == 'results':
        try:
            return get_time_date_format(raw, section='fixtures')
        except Exception:
            pass
    from datetime import date as _date, time as _time, datetime as _dt
    m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})?', raw)
    if not m:
        raise ValueError(f'fecha no parseable: {raw!r}')
    dd, mm = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else _dt.utcnow().year
    mt = re.search(r'(\d{1,2}):(\d{2})', raw)
    tm = _time(int(mt.group(1)), int(mt.group(2))) if mt else None
    return _date(year, mm, dd), tm


def create_match(fixture, league_inf, home_team_id, away_team_id, stadium_id, country_id, dry_run,
                 status='SCHEDULED', match_date_override=None, start_time_override=None,
                 statistic=None, section='fixtures'):
    """Crea el match + match_detail (home/visitor) + score. Anti-duplicado por
    (league_id, match_date, name). Devuelve 'created'|'would'|'dup'|'error'.

    Para partidos de HOY (vista summary): pasar match_date_override (date de hoy),
    `status` real (LIVE/COMPLETED/SCHEDULED) y, si el fixture trae home_result/
    visitor_result, se escribe ese score; si no, queda FIXTURE_POINTS (-1)."""
    if match_date_override is not None:
        # start_time NULL si no se conoce (columna time no acepta '' ).
        match_date, start_time = match_date_override, (start_time_override or None)
    else:
        try:
            match_date, start_time = _parse_md(fixture['match_date'], section)
        except Exception as e:
            print(f"      [ERROR] no se pudo parsear fecha {fixture['match_date']!r}: {e}")
            return 'error'

    if check_match_duplicate(league_inf['league_id'], match_date, fixture['name']):
        print(f"      [MATCH EXISTENTE] [DUP] ya existe en DB: {fixture['name']} @ {match_date}")
        return 'dup'

    def _pts(v):
        if v in (None, ''):
            return FIXTURE_POINTS
        try:
            return int(str(v).strip())
        except Exception:
            return FIXTURE_POINTS
    home_pts = _pts(fixture.get('home_result'))
    away_pts = _pts(fixture.get('visitor_result'))

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
        'statistic':    statistic,
        'status':       status,
    }
    md_home = {'match_detail_id': generate_uuid(), 'home': True,  'visitor': False,
               'match_id': match_id, 'team_id': home_team_id,
               'points': home_pts, 'score_id': generate_uuid()}
    md_away = {'match_detail_id': generate_uuid(), 'home': False, 'visitor': True,
               'match_id': match_id, 'team_id': away_team_id,
               'points': away_pts, 'score_id': generate_uuid()}

    # Campos EXACTOS que se insertarían (verificación de prueba):
    print(f"      [MATCH FIELDS] {match_dict}")
    print(f"      [DETAIL home ] {md_home}")
    print(f"      [DETAIL away ] {md_away}")

    if dry_run:
        print(f"      [MATCH NO EXISTENTE] {fixture['name']} @ {match_date} {start_time} "
              f"-> se crearía (DRY-RUN) | home={home_team_id} away={away_team_id} "
              f"| stadium_id={match_dict['stadium_id']}")
        return 'would'

    save_math_info(match_dict)
    save_details_math_info(md_home)
    save_details_math_info(md_away)
    save_score_info(md_home)
    save_score_info(md_away)
    print(f"      [MATCH CREADO] {fixture['name']} @ {match_date} (match_id={match_id}) "
          f"+ match_detail home/away + score_entity")
    return 'created'


# ─── CHECKPOINT por liga (lista de matches persistida + cursor) ─────────────
PROGRESS_DIR = 'check_points/fixtures_progress'


def _progress_path(sport_key, league_key, section='fixtures'):
    base = PROGRESS_DIR if section == 'fixtures' else 'check_points/results_progress'
    return os.path.join(ROOT, base, sport_key, f"{league_key}.json")


def load_progress(sport_key, league_key, section='fixtures'):
    path = _progress_path(sport_key, league_key, section)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"  [CHECKPOINT] no se pudo leer {path}: {e}")
        return None


def save_progress(prog):
    path = _progress_path(prog['sport_key'], prog['league_key'], prog.get('section', 'fixtures'))
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
                   rescan=False, section='fixtures'):
    # section: 'fixtures' (próximos, SCHEDULED, sin stats) | 'results' (jugados,
    # COMPLETED, con score + estadísticas). Todo el resto del flujo es común.
    fixtures_url = league_info.get('fixtures') if section == 'fixtures' else league_info.get('results')
    if not fixtures_url:
        print(f"  [SKIP] {league_key}: sin URL de {section} en leagues_info")
        stats['leagues_skipped'] += 1
        return
    _status = 'SCHEDULED' if section == 'fixtures' else 'COMPLETED'

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
    print(f"  {section}: {fixtures_url}")

    # league_id REAL desde la DB (el de leagues_info.json puede estar desactualizado
    # y no existir en `league` -> rompía la creación de season/match).
    try:
        con = getdb()
        real_lid, cands = resolve_league_id(con, country, league_name,
                                            sport=_db_sport_name(sport_name))
    except Exception as e:
        print(f"  [SKIP] {league_key}: error resolviendo league_id en DB: {e}")
        stats['leagues_skipped'] += 1
        return
    if not real_lid:
        print(f"  [LIGA NO ENCONTRADA EN DB] {league_key} (país={country}, liga={league_name})")
        print(f"  [SKIP] {league_key}: liga no encontrada en DB. candidatos={cands}")
        stats['leagues_skipped'] += 1
        return
    if real_lid != league_inf['league_id']:
        print(f"  [league_id] JSON={league_inf['league_id']} -> DB real={real_lid} (uso el real)")
    league_inf['league_id'] = real_lid
    print(f"  [LIGA EXISTENTE] {league_key} (league_id={league_inf['league_id']})")

    # ── CHECKPOINT: cargar lista persistida, o escanear (1ª vez / --rescan) ──
    prog = None if rescan else load_progress(sport_name, league_key, section)
    if prog is None or rescan:
        try:
            wait_update_page(driver, fixtures_url, 'container__heading')
            dismiss_cookies(driver)
        except Exception as e:
            print(f"  [ERROR] navegando {section}: {e}")
            stats['leagues_skipped'] += 1
            return
        season_id = ensure_season(driver, league_inf, dry_run)
        scanned = scan_fixtures_page(driver, league_inf['country_id'], section=section)
        entries = [{'name': f['name'], 'date': f['match_date'], 'url': f['link_details'],
                    'home': f.get('home', ''), 'visitor': f.get('visitor', ''),
                    'home_result': f.get('home_result'), 'visitor_result': f.get('visitor_result'),
                    'done': False}
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
            prog = {'sport_key': sport_name, 'league_key': league_key, 'section': section,
                    'league_id': real_lid, 'season_id': season_id,
                    'matches': entries, 'last_index': -1, 'status': 'pending'}
            print(f"  [FIXTURES] total de partidos encontrados: {len(entries)}")
        _recompute_last_index(prog)
        save_progress(prog)
    else:
        hechos = sum(1 for m in prog['matches'] if m.get('done'))
        prog['league_id'] = real_lid
        print(f"  [CHECKPOINT] cargado: {len(prog['matches'])} matches | hechos={hechos} "
              f"| retoma desde índice {prog.get('last_index', -1) + 1}")

    prog['section'] = section   # asegura section en todas las ramas (checkpoint viejo/rescan)
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
              'home': m.get('home', ''), 'visitor': m.get('visitor', ''),
              'home_result': m.get('home_result'), 'visitor_result': m.get('visitor_result')}
        print(f"\n  >>> [{i}] {fx['name']}  ({fx['match_date']})  url={fx['link_details']}")
        _res_txt = (f"{fx.get('home_result')}-{fx.get('visitor_result')}"
                    if section == 'results' else '— (fixture)')
        print(f"  [PARTIDO] fecha={fx['match_date']} | "
              f"{fx['home'] or '?'} vs {fx['visitor'] or '?'} | resultado: {_res_txt}")

        # red de seguridad: si ya existe en DB (liga+fecha+nombre) -> done sin navegar
        try:
            _md, _ = _parse_md(fx['match_date'], section)
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

        print(f"  [TEAM] home: {home_url}")
        home_team_id = ensure_team_created(driver, home_url, league_inf, dict_teams_db,
                                           sport_id, dry_run, sport_key=sport_name,
                                           league_key=league_key, url_cache=url_cache,
                                           report_existence=True)
        if stop_after_first_team:
            print("\n  [TEST] --stop-after-first-team: primer equipo procesado.")
            stats['stopped_test'] += 1
            raise _StopAfterFirstTeam()
        print(f"  [TEAM] away: {away_url}")
        away_team_id = ensure_team_created(driver, away_url, league_inf, dict_teams_db,
                                           sport_id, dry_run, sport_key=sport_name,
                                           league_key=league_key, url_cache=url_cache,
                                           report_existence=True)
        if not (home_team_id and away_team_id):
            print("      [SKIP] no se pudo crear/obtener uno de los equipos")
            stats['errors'] += 1
            continue

        statistic = None
        if section == 'results':
            try:
                statistic = get_statistics_game(driver)
            except Exception as e:
                print(f"      [STATS] no se pudieron extraer: {e}")
        res = create_match(fx, league_inf, home_team_id, away_team_id,
                           stadium_id, match_country_id, dry_run,
                           status=_status, statistic=statistic, section=section)
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
    """Asegura el driver de CORRECCIÓN del panel (con login) y lo devuelve.
    REUSA el que ya existe y está libre; SOLO si su sesión no responde o no existe
    lo (re)lanza VÍA EL PANEL (driver_manager) — UN solo driver gestionado y
    persistente, NUNCA uno nuevo sin gestión por corrida (antes hacía Popen propio
    y acumulaba drivers huérfanos cada vez que la sesión estaba caída)."""
    d = _reuse_driver_session()
    if d is not None:
        try:
            _ = d.current_url
            print("[DRIVER] reusando el driver de corrección del panel (con login)")
            return d
        except Exception:
            print("[DRIVER] la sesión del driver de corrección no responde -> reciclando vía panel")
    else:
        print("[DRIVER] no hay driver de corrección -> iniciándolo vía panel")
    # (Re)lanzar el driver de corrección GESTIONADO por el panel (tracked + persistente,
    # se reusa en las próximas corridas). relaunch_driver hace stop+start si estaba
    # caído, o start si no había ninguno, y devuelve el driver reconectado.
    try:
        from driver_session import relaunch_driver
        d = relaunch_driver(timeout=140)
        print("[DRIVER] driver de corrección del panel listo (con login)")
        return d
    except Exception as e:
        raise RuntimeError(f"no se pudo asegurar el driver de corrección del panel: {e}")


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
            # sport (DB) para no dar falsos "ya existe" entre ligas homónimas de
            # deportes distintos (TURKEY 'Super Lig' básquet vs fútbol).
            mid = get_match_id(lc, lname, today, info['name'],
                               sport=_db_sport_name(sport))   # ya hace strip de fase
            if not mid:
                base = strip_phase_suffix(lname)
                key = (lc, base)
                pend[key] = pend.get(key, 0) + 1
                print(f"   [FALTA] {lc} / {lname} :: {info['name']}")
    return pend


# ─── MODO --today: crear partidos de HOY desde la página SUMMARY de la liga ───
def scan_summary_today(driver, country_id):
    """Scan de la SUMMARY de una liga -> partidos de HOY con name, link, status y
    score. HOY = filas SIN prefijo de fecha 'DD.MM.' en event__time (FlashScore solo
    muestra stage/hora en los de hoy). Status: Finished->COMPLETED, 'Nth Inning'->LIVE,
    sin stage y con hora futura->SCHEDULED."""
    import re as _re
    # Las filas event__match aparecen primero como ESQUELETO; su contenido
    # (homeParticipant/stage/score) carga después. Esperar el contenido (participant).
    # OJO: los partidos live/finished NO tienen event__time (muestran event__stage),
    # por eso NO se usa get_result (que exige event__time) — se leen campos directo.
    rows = []
    for _ in range(5):
        rows = driver.find_elements(By.CSS_SELECTOR, 'div.event__match')
        if rows and any(r.find_elements(By.XPATH, ".//div[contains(@class,'homeParticipant')]")
                        for r in rows[:6]):
            break
        time.sleep(2)
    out = []
    for row in rows:
        try:
            t = ''
            try: t = row.find_element(By.CLASS_NAME, 'event__time').text.strip()
            except Exception: pass
            if '.' in t:        # 'DD.MM. HH:MM' -> otro día (hoy: sin event__time o 'HH:MM')
                continue
            try:
                home = row.find_element(By.XPATH, ".//div[contains(@class,'homeParticipant')]").text.strip()
                away = row.find_element(By.XPATH, ".//div[contains(@class,'awayParticipant')]").text.strip()
            except Exception:
                continue
            if not (home and away):
                continue
            stage = ''
            try: stage = row.find_element(By.CSS_SELECTOR, '.event__stage').text.strip()
            except Exception: pass
            hs = aw = ''
            try:
                hs = row.find_element(By.CSS_SELECTOR, '.event__score--home').text.strip()
                aw = row.find_element(By.CSS_SELECTOR, '.event__score--away').text.strip()
            except Exception: pass
            try:
                link_id = _re.findall(r'id="[a-z]_\d_(.+?)\"', row.get_attribute('outerHTML'))[0]
            except Exception:
                continue
            url_details = "https://www.flashscore.com/match/{}/#/match-summary/match-summary".format(link_id)
            low = stage.lower()
            finished = any(w in low for w in ('finish', 'final', 'after', 'aban', 'awarded'))
            if stage and not finished:
                status = 'LIVE'              # 'I9', '9th Inning', etc.
            elif finished or (hs and aw):
                status = 'COMPLETED'         # stage Finished, o score presente sin stage
            else:
                status = 'SCHEDULED'
            out.append({
                'name': home + '~' + away, 'home': home, 'visitor': away,
                'link_details': url_details, 'status': status, 'stage': stage,
                'home_result':    hs if status != 'SCHEDULED' else '',
                'visitor_result': aw if status != 'SCHEDULED' else '',
                'country_id': country_id,
            })
        except Exception:
            continue
    return out


def process_league_summary(driver, sport_name, league_key, league_info, sport_id,
                           dict_teams_db, dry_run, stats):
    """Crea los partidos de HOY faltantes de una liga desde su SUMMARY (cubre
    jugados COMPLETED+score, live LIVE+score y próximos SCHEDULED). Reusa el mismo
    flujo que process_league (navegar match -> equipos -> create_match)."""
    url = league_info.get('url') or league_info.get('results')
    if not url:
        print(f"  [SKIP] {league_key}: sin URL en leagues_info"); stats['leagues_skipped'] += 1; return
    league_name = league_info.get('league_name') or league_key.split('_', 1)[-1]
    country = league_key.split('_', 1)[0]
    league_inf = {'sport_id': sport_id, 'sport_name': sport_name,
                  'league_id': league_info['league_id'], 'league_name': league_name,
                  'season_id': league_info['season_id'], 'country_id': league_info['country_id']}
    print('\n' + '=' * 72)
    print(f"[{sport_name}] {league_key} (SUMMARY hoy) -> {url}")
    try:
        con = getdb(); real_lid, cands = resolve_league_id(con, country, league_name,
                                                           sport=_db_sport_name(sport_name))
    except Exception as e:
        print(f"  [SKIP] error resolviendo league_id: {e}"); stats['leagues_skipped'] += 1; return
    if not real_lid:
        print(f"  [SKIP] liga no encontrada en DB (cands={cands})"); stats['leagues_skipped'] += 1; return
    if real_lid != league_inf['league_id']:
        print(f"  [league_id] JSON={league_inf['league_id']} -> DB real={real_lid}")
    league_inf['league_id'] = real_lid

    try:
        wait_update_page(driver, url, 'container__heading'); dismiss_cookies(driver)
    except Exception as e:
        print(f"  [ERROR] navegando summary: {e}"); stats['leagues_skipped'] += 1; return
    season_id = ensure_season(driver, league_inf, dry_run)
    league_inf['season_id'] = season_id or league_inf['season_id']

    today = datetime.now().date()
    matches = scan_summary_today(driver, league_inf['country_id'])
    print(f"  [SUMMARY] partidos de HOY detectados: {len(matches)}")
    url_cache = load_url_team_cache(sport_name, league_key)

    for i, mm in enumerate(matches):
        name, status = mm['name'], mm['status']
        print(f"\n  >>> [{i}] {name}  status={status}  "
              f"score={mm.get('home_result') or '-'}-{mm.get('visitor_result') or '-'}  "
              f"stage={mm.get('stage')!r}  url={mm['link_details']}")
        if check_match_duplicate(real_lid, today, name):
            print("      [DUP] ya existe en DB (hoy) -> skip"); stats['dup'] += 1; continue
        try:
            wait_update_page(driver, mm['link_details'], 'duelParticipant'); dismiss_cookies(driver)
        except Exception as e:
            print(f"      [ERROR] navegando al match: {e}"); stats['errors'] += 1; continue
        match_country_id = detect_match_country_id(driver, league_inf['country_id'], dry_run)
        stadium_id = ensure_match_stadium(driver, match_country_id, dry_run)
        home_url, away_url = get_team_links_from_match(driver)
        if not (home_url and away_url):
            print("      [SKIP] no se extrajeron los 2 links de equipo"); stats['errors'] += 1; continue
        home_team_id = ensure_team_created(driver, home_url, league_inf, dict_teams_db, sport_id, dry_run,
                                           sport_key=sport_name, league_key=league_key,
                                           url_cache=url_cache, report_existence=True)
        away_team_id = ensure_team_created(driver, away_url, league_inf, dict_teams_db, sport_id, dry_run,
                                           sport_key=sport_name, league_key=league_key,
                                           url_cache=url_cache, report_existence=True)
        if not (home_team_id and away_team_id):
            print("      [SKIP] no se pudo crear/obtener uno de los equipos"); stats['errors'] += 1; continue
        res = create_match(mm, league_inf, home_team_id, away_team_id, stadium_id,
                           match_country_id, dry_run, status=status, match_date_override=today)
        stats[res] = stats.get(res, 0) + 1
    stats['leagues_done'] += 1


def main():
    ap = argparse.ArgumentParser(description='Crea fixtures faltantes creando equipos al vuelo')
    ap.add_argument('--sport', default='FOOTBALL', help='Nombre de deporte del proyecto (UPPER)')
    ap.add_argument('--sports', nargs='+', default=None,
                    help='Varios deportes para --from-pin (barre cada uno). Si se omite, usa --sport.')
    ap.add_argument('--leagues', nargs='+', default=None,
                    help="Claves de liga en leagues_info.json (ej: 'PERU_Liga 1'). "
                         "No requerido si se usa --from-pin")
    ap.add_argument('--from-pin', action='store_true',
                    help='Detecta solo las ligas pineadas con partidos de HOY faltantes '
                         'en DB (driver con login) y extrae sus fixtures')
    ap.add_argument('--today', action='store_true',
                    help='Crea los partidos de HOY desde la página SUMMARY de la liga '
                         '(jugados COMPLETED+score, live LIVE+score, próximos SCHEDULED). '
                         'Requiere --leagues. Es lo que faltaba para los detectados por el Live.')
    ap.add_argument('--apply', action='store_true', help='Escribe en DB (default: dry-run)')
    ap.add_argument('--headless', action='store_true')
    ap.add_argument('--stop-after-first-team', action='store_true',
                    help='PRUEBA: detiene el script tras crear el primer equipo '
                         '(para verificar los campos insertados)')
    ap.add_argument('--rescan', action='store_true',
                    help='Re-escanea fixtures y MERGEA los nuevos al checkpoint '
                         '(sin perder el progreso ya extraído)')
    ap.add_argument('--results', action='store_true',
                    help='Modo RESULTS: crea partidos PASADOS desde la página de results '
                         '(score + estadísticas + status COMPLETED). Crea el equipo si no '
                         'existe, igual que fixtures. Checkpoint separado (results_progress).')
    ap.add_argument('--no-reuse', action='store_true',
                    help='Lanza un driver PROPIO en vez de reusar el vivo de '
                         'corrección (útil si ese driver está ocupado)')
    ap.add_argument('--session-file', default=None,
                    help='Path del session file del driver (default: el de '
                         'corrección tmp/driver_session.json). Con --no-reuse, '
                         'donde se guarda la sesión del driver propio.')
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
    leagues_info = load_json(LI_PATH)
    pendientes_completar = []

    # Deportes a procesar: con --from-pin puede ser VARIOS (--sports); si no, uno.
    sports_to_process = args.sports if (args.from_pin and args.sports) else [args.sport]
    need = 'url' if args.today else ('results' if args.results else 'fixtures')

    # ── DRIVER (una sola vez, compartido entre deportes) ──────────────────────
    if args.from_pin:
        driver = ensure_logged_driver(headless=args.headless)   # reusa o crea+login
    else:
        if not args.leagues:
            print("[ERROR] indicá --leagues \"PAIS_Liga\" ... o usá --from-pin")
            sys.exit(1)
        driver = get_or_launch_driver(reuse=not args.no_reuse, headless=args.headless,
                                      session_path=args.session_file)
    print(f"driver: {driver.current_url}")

    stats = Counter()
    print('\n' + '#' * 72)
    print(f"CREAR FIXTURES | deportes={sports_to_process} | dry_run={dry_run} | "
          f"from_pin={args.from_pin} | today={args.today}")
    print('#' * 72)

    for sport in sports_to_process:
        sport_id = dict_sport_id.get(sport)
        if not sport_id:
            print(f"[ERROR] deporte {sport!r} no está en DB -> se omite. "
                  f"Disponibles: {list(dict_sport_id)}")
            continue
        print('\n' + '=' * 72 + f"\n### DEPORTE: {sport}\n" + '=' * 72)

        # Lista de ligas de ESTE deporte
        if args.from_pin:
            pend = detect_pending_leagues(driver, sport)        # {(país,base): faltan}
            li_sport = leagues_info.get(sport, {})
            league_keys = []
            for (co, base) in pend:
                key = f"{co}_{base}"
                if key in li_sport and li_sport[key].get(need):
                    league_keys.append(key)
                else:
                    motivo = ('no está en leagues_info.json' if key not in li_sport
                              else f'sin URL de {need} en leagues_info')
                    print(f"  ‼ [INCOMPLETO] '{key}' tiene partidos de HOY FALTANTES en DB "
                          f"pero {motivo} -> *** DEBE COMPLETARSE LUEGO ***")
                    pendientes_completar.append((key, motivo, pend[(co, base)]))
            league_keys = sorted(set(league_keys))
            print(f"[FROM-PIN] {sport}: ligas a extraer (faltantes hoy): {league_keys}")
        else:
            league_keys = args.leagues

        dict_teams_db = get_dict_league_ready(sport_id=sport_id)

        for league_key in league_keys:
            info = leagues_info.get(sport, {}).get(league_key)
            if not info or not info.get(need):
                motivo = ('no está en leagues_info.json' if not info
                          else f'sin URL de {need} en leagues_info')
                print(f"\n  ‼ [INCOMPLETO] {league_key}: {motivo} -> NO se pudo extraer. "
                      f"*** DEBE COMPLETARSE LUEGO ***")
                if league_key not in [p[0] for p in pendientes_completar]:
                    pendientes_completar.append((league_key, motivo, 0))
                stats['leagues_skipped'] += 1
                continue
            try:
                if args.today:
                    process_league_summary(driver, sport, league_key, info, sport_id,
                                           dict_teams_db, dry_run, stats)
                    continue
                process_league(driver, sport, league_key, info, sport_id,
                               dict_teams_db, dry_run, stats,
                               stop_after_first_team=args.stop_after_first_team,
                               rescan=args.rescan,
                               section=('results' if args.results else 'fixtures'))
            except _StopAfterFirstTeam:
                print("\n[TEST] detenido tras el primer equipo (modo prueba).")
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
