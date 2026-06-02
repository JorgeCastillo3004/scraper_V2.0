"""
fix_live_matches.py — ejecucion diaria
=======================================
Cierra partidos que quedaron en LIVE al finalizar el dia.

USO:
    python scripts/fix_live_matches.py              # dry-run
    python scripts/fix_live_matches.py --run        # interactivo (pide confirmacion)
    python scripts/fix_live_matches.py --run --yes  # sin confirmacion
"""

import sys, os, re, time
from collections import defaultdict
from datetime import date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import psycopg2
from selenium.webdriver.common.by import By

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, FS_EMAIL, FS_PASSWORD
from common_functions import launch_navigator, login, dismiss_cookies, wait_update_page, load_json
from data_base import get_math_details_ids, update_score, update_match_status
from milestone4 import get_result, get_match_info, get_statistics_game, wait_load_details, retry_match

LEAGUES_INFO_PATH = 'check_points/leagues_info.json'
DRY_RUN  = '--run' not in sys.argv
AUTO_YES = '--yes' in sys.argv


def confirm(msg):
    # Confirmacion deshabilitada: el script actualiza siempre sin preguntar.
    # Se conserva la firma por si algun caller externo la importa.
    print('  [AUTO] %s' % msg)
    return True


def get_pending_live_matches(only_status=None, sport=None, date_from=None, date_to=None, verbose=True):
    """
    Devuelve partidos que requieren cierre desde FlashScore.

    Criterio unificado:
      - fecha < hoy
      - Y (status = 'LIVE'  OR  algun score_entity.points = -1)

    Filtros opcionales (todos AND):
      only_status : 'LIVE' o 'SCHEDULED' para restringir.
      sport       : nombre de sport.name (ej. 'Football').
      date_from   : 'YYYY-MM-DD' inclusive.
      date_to     : 'YYYY-MM-DD' inclusive.

    El partido aparece una sola vez (DISTINCT) aunque tenga dos match_detail con -1.
    """
    if verbose:
        print('\n[1] Consultando DB...')
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()

    sql = """
        SELECT DISTINCT
               m.match_id, m.name, m.match_date, m.league_id, m.season_id,
               l.league_name, c.country_name, s.name, m.status
        FROM match m
        JOIN league  l ON m.league_id  = l.league_id
        JOIN sport   s ON l.sport_id   = s.sport_id
        JOIN country c ON l.country_id = c.country_id
        LEFT JOIN match_detail md ON md.match_id          = m.match_id
        LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
        WHERE m.match_date < CURRENT_DATE
          AND (m.status = 'LIVE' OR se.points = -1)
    """
    params = []
    if only_status:
        sql += " AND m.status = %s "; params.append(only_status)
    if sport:
        sql += " AND s.name = %s ";   params.append(sport)
    if date_from:
        sql += " AND m.match_date >= %s "; params.append(date_from)
    if date_to:
        sql += " AND m.match_date <= %s "; params.append(date_to)
    sql += " ORDER BY s.name, l.league_name, m.match_date;"

    cur.execute(sql, params)
    cols = ['match_id','name','match_date','league_id','season_id',
            'league_name','country_name','sport_name','status']
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); con.close()

    if verbose:
        by_status = {}
        for r in rows:
            by_status[r['status']] = by_status.get(r['status'], 0) + 1
        print('  Partidos a cerrar: %d  | desglose por status: %s' % (len(rows), by_status))
        for m in rows[:20]:
            print('    [%s] %s | %s | %s | %s | %s' % (
                m['status'], m['sport_name'], m['country_name'], m['league_name'],
                m['match_date'], m['name']))
        if len(rows) > 20:
            print('    ... (+%d adicionales)' % (len(rows) - 20))
    return rows


def sin_stats(s):
    """True si el campo statistic está vacío (NULL / '' / '{}') — misma regla
    que fix_null_team_ids. (Validado en el notebook de pruebas.)"""
    return s is None or str(s).strip() in ('', '{}')


def get_statistic_map(match_ids):
    """{match_id: statistic} para los match_ids dados (solo lectura).
    (Validado en el notebook de pruebas.)"""
    if not match_ids:
        return {}
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute('SELECT match_id, statistic FROM match WHERE match_id = ANY(%s)', (list(match_ids),))
    out = {r[0]: r[1] for r in cur.fetchall()}
    cur.close(); con.close()
    return out


def get_stats_backfill_matches(league_ids=None, sport=None, verbose=True):
    """Población para BACKFILL de estadísticas (validado en el notebook):
       status = COMPLETED  AND  statistic vacío  AND  ningún score = -1
    (el resultado real ya está cargado; solo faltan los detalles). NO toca score.
    Devuelve dicts con las mismas claves que get_pending_live_matches."""
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    sql = """
        SELECT DISTINCT
               m.match_id, m.name, m.match_date, m.league_id, m.season_id,
               l.league_name, c.country_name, s.name, m.status
          FROM match m
          JOIN league  l ON m.league_id  = l.league_id
          JOIN sport   s ON l.sport_id   = s.sport_id
          JOIN country c ON l.country_id = c.country_id
         WHERE m.status = 'COMPLETED'
           AND (m.statistic IS NULL OR m.statistic IN ('', '{}'))
           AND NOT EXISTS (
               SELECT 1 FROM match_detail md
                 JOIN score_entity se ON se.match_detail_id = md.match_detail_id
                WHERE md.match_id = m.match_id AND se.points = -1)
    """
    params = []
    if league_ids:
        sql += ' AND m.league_id = ANY(%s) '; params.append(list(league_ids))
    if sport:
        sql += ' AND s.name = %s '; params.append(sport)
    sql += ' ORDER BY s.name, l.league_name, m.match_date;'
    cur.execute(sql, params)
    cols = ['match_id', 'name', 'match_date', 'league_id', 'season_id',
            'league_name', 'country_name', 'sport_name', 'status']
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); con.close()
    if verbose:
        print('  Backfill stats (COMPLETED, score!=-1, sin statistic): %d' % len(rows))
    return rows


def find_results_url(leagues_info, sport_name, country_name, league_name):
    for k, v in leagues_info.items():
        if k.upper() != sport_name.upper():
            continue
        for lk, lv in v.items():
            lc, _, ll = lk.partition('_')
            if lc.upper() == country_name.upper() and ll.upper() == league_name.upper():
                return lv.get('results')
    return None


_DATE_RE = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?')


def parse_flashscore_date(raw):
    """
    Parsea fechas que FlashScore muestra en la lista de results.

    Formatos validos:
      DD.MM.          -> sin anio, asume actual
      DD.MM.YY        -> anio de 2 digitos, prefija '20'
      DD.MM.YYYY      -> anio completo
    Cualquiera puede llevar tiempo extra "HH:MM" detras (se ignora).

    Devuelve datetime.date o None si no parsea.
    """
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if not m:
        return None
    day, month, year_raw = int(m.group(1)), int(m.group(2)), m.group(3)
    if not year_raw:
        year = date.today().year
    else:
        y = int(year_raw)
        year = 2000 + y if y < 100 else y
    return date(year, month, day)


def get_last_visible_date(driver):
    rows = driver.find_elements(By.XPATH, '//div[contains(@class,"leagues--static event--leagues")]/div')
    for row in reversed(rows):
        try:
            html = row.get_attribute('outerHTML')
            if 'Click for match detail!' not in html and 'Click for details!' not in html:
                continue
            scraped = get_result(row, country_id='', section='results')
            parsed = parse_flashscore_date(scraped['match_date'])
            if parsed:
                return parsed
        except Exception:
            continue
    return None


def _no_match_visible(driver):
    # FlashScore mantiene el texto "No match found" oculto en placeholders del DOM
    # (menus colapsados, plantillas). Solo cuenta si esta visible Y no hay rows.
    xpath = "//*[contains(text(),'No match found') or contains(text(),'No matches found')]"
    nodes = driver.find_elements(By.XPATH, xpath)
    if not any(n.is_displayed() for n in nodes):
        return False
    matches = driver.find_elements(By.CSS_SELECTOR, "div.event__match")
    return not any(m.is_displayed() for m in matches)


def load_until_date(driver, target_date):
    xpath_rows = '//div[contains(@class,"leagues--static event--leagues")]/div'
    xpath_btn  = "//*[contains(.,'Show more matches') and (self::button or self::a)]"
    print('  Cargando hasta: %s' % target_date)

    # Pre-check: si la pagina ya muestra "No match found", abortar de inmediato
    if _no_match_visible(driver):
        print('  [SKIP] "No match found" detectado — la pagina no tiene partidos')
        return

    for attempt in range(30):
        # Esperar a que la fecha renderice: get_last_visible_date puede devolver
        # None si las filas aún no cargaron. Reintentamos hasta ~6s antes de seguir,
        # salvo que realmente no haya partidos ("No match found").
        last_date = get_last_visible_date(driver)
        waited = 0
        while last_date is None and waited < 12 and not _no_match_visible(driver):
            time.sleep(0.5)
            last_date = get_last_visible_date(driver)
            waited += 1
        rows      = driver.find_elements(By.XPATH, xpath_rows)
        print('  [click %d] filas=%d | ultima fecha=%s' % (attempt, len(rows), last_date))
        # Si no hay filas y aparece "No match found" visible, abortar
        if len(rows) == 0 and _no_match_visible(driver):
            print('  [SKIP] "No match found" tras click %d — abortando carga' % attempt)
            return
        if last_date and last_date <= target_date:
            print('  Rango alcanzado.')
            break
        btn = driver.find_elements(By.XPATH, xpath_btn)
        if not btn:
            print('  Sin mas resultados.')
            break
        old_len = len(rows)
        driver.execute_script("arguments[0].scrollIntoView(true);", btn[0])
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn[0])
        for _ in range(10):
            time.sleep(0.3)
            if len(driver.find_elements(By.XPATH, xpath_rows)) > old_len:
                break

    # Delay final: tras el último "Show more" (o al alcanzar el rango), esperar a
    # que la página termine de cargar/renderizar todas las filas antes de escanear.
    # Este script no necesita velocidad, así que damos margen para no perder partidos.
    time.sleep(2.5)


def _norm_team(s):
    # FlashScore renderiza nombres sin guiones ni espacios consistentes
    # ("Hapoel Tel-Aviv" en DB -> "Hapoel Tel Aviv" en la pagina).
    return s.lower().replace('-', '').replace(' ', '')


def scan_results_page(driver, target_matches):
    print('\n  [4] Buscando partidos en pagina...')
    rows  = driver.find_elements(By.XPATH, '//div[contains(@class,"leagues--static event--leagues")]/div')
    # Si no hay filas y aparece "No match found" visible, retornar dict vacio rapido
    if not rows and _no_match_visible(driver):
        print('    [SKIP] "No match found" — sin partidos en la pagina')
        return {}
    # Pre-cachear text + outerHTML de cada row UNA SOLA VEZ. Hacer row.text/get_attribute
    # dentro del doble loop (N_targets * N_rows llamadas a Selenium) es lento y
    # produce strings vacios cuando el row aun no esta renderizado.
    row_cache = []
    for row in rows:
        try:
            # textContent NO depende del renderizado: trae el texto aunque la fila
            # esté fuera de pantalla. row.text devuelve '' para filas no renderizadas
            # y hacía perder matches (ej. Lokomotiv Moscow~Krasnodar a mitad de lista).
            text = row.get_attribute('textContent') or row.text or ''
        except Exception:
            text = ''
        try:
            html = row.get_attribute('outerHTML') or ''
        except Exception:
            html = ''
        row_cache.append({
            'row':       row,
            'text_norm': _norm_team(text),
            'html':      html,
            'has_tip':   'Click for details!' in html or 'Click for match detail!' in html,
        })

    found = {}
    for m in target_matches:
        home, _, visitor = m['name'].partition('~')
        h_norm = _norm_team(home)
        v_norm = _norm_team(visitor)
        for entry in row_cache:
            if h_norm not in entry['text_norm'] or v_norm not in entry['text_norm']:
                continue
            if not entry['has_tip']:
                continue
            try:
                scraped = get_result(entry['row'], country_id='', section='results')
            except Exception:
                continue
            found[m['match_id']] = scraped
            print('    [FOUND] %s | score: %s-%s | %s' % (
                m['name'], scraped['home_result'], scraped['visitor_result'], scraped['link_details']))
            break
        else:
            print('    [NOT FOUND] %s' % m['name'])
    return found


def scan_with_coverage(driver, league_matches, label='', max_retries=3):
    """scan_results_page + log de COBERTURA (encontrados X / Y en DB).
    Si no se encuentran todos, espera más tiempo (escalando) y reintenta — la
    lista de FlashScore puede no haber terminado de cargar/renderizar. Devuelve
    el dict found acumulado. (Este script no necesita velocidad.)"""
    total = len(league_matches)
    tag = (' ' + label) if label else ''
    found = scan_results_page(driver, league_matches)
    print('  [COBERTURA%s] encontrados %d / %d en DB' % (tag, len(found), total))

    extra_wait = 3.0
    attempt = 0
    while len(found) < total and attempt < max_retries:
        attempt += 1
        faltan = [m for m in league_matches if m['match_id'] not in found]
        print('  [COBERTURA] faltan %d -> espero %.0fs y reintento (%d/%d)...'
              % (len(faltan), extra_wait, attempt, max_retries))
        try:
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        except Exception:
            pass
        time.sleep(extra_wait)
        nuevos = scan_results_page(driver, faltan)
        found.update(nuevos)
        print('  [COBERTURA%s] encontrados %d / %d en DB' % (tag, len(found), total))
        extra_wait += 3.0

    if len(found) < total:
        faltan = [m for m in league_matches if m['match_id'] not in found]
        print('  [COBERTURA] ADVERTENCIA: NO se encontraron todos (faltan %d):' % len(faltan))
        for m in faltan[:20]:
            print('      [FALTA] %s | %s' % (m['match_date'], m['name']))
    else:
        print('  [COBERTURA] OK: todos los partidos encontrados (%d/%d)' % (total, total))
    return found


def update_match_in_db(driver, db_match, scraped, dry_run):
    match_id       = db_match['match_id']
    match_name     = db_match['name']
    home_result    = scraped['home_result']
    visitor_result = scraped['visitor_result']
    link           = scraped['link_details']

    print('\n  [5] Extrayendo detalle: %s' % match_name)
    print('    URL: %s' % link)

    event_info = {'home': scraped.get('home',''), 'visitor': scraped.get('visitor','')}
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
        print('    [WARN] Sin estadisticas: %s' % e)

    print('\n  [6] Datos a actualizar:')
    print('    match_id  : %s' % match_id)
    print('    partido   : %s' % match_name)
    print('    score     : %s (home) - %s (visitor)' % (home_result, visitor_result))
    print('    status    : LIVE → COMPLETED')
    print('    statistic : %s...' % str(statistic)[:100])

    dict_detail = get_math_details_ids(match_id)
    print('    details   : %s' % dict_detail)

    if dry_run:
        print('    [DRY-RUN]')
        return True

    for detail_id, home_flag in dict_detail.items():
        points = home_result if home_flag else visitor_result
        update_score({'match_detail_id': detail_id, 'points': points})
        print('    [SCORE] %s → %s' % ('home' if home_flag else 'visitor', points))

    update_match_status({'status': 'COMPLETED', 'match_id': match_id})

    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute("UPDATE match SET statistic = %s WHERE match_id = %s", (str(statistic), match_id))
    con.commit(); cur.close(); con.close()

    try:
        stats_count = len(eval(str(statistic)))
    except Exception:
        stats_count = 0

    print('\n    ── RESUMEN PARTIDO ──────────────────────────────')
    print('    Partido      : %s' % match_name)
    print('    Score        : %s (home)  -  %s (visitor)' % (home_result, visitor_result))
    print('    Status       : LIVE → COMPLETED')
    print('    Estadisticas : %d indicadores guardados' % stats_count)
    print('    ─────────────────────────────────────────────────')
    return True


def main():
    print('=' * 65)
    print('fix_live_matches.py — ejecucion diaria')
    print('Modo: %s' % ('DRY-RUN' if DRY_RUN else ('AUTO' if AUTO_YES else 'INTERACTIVO')))
    print('=' * 65)

    matches = get_pending_live_matches()
    if not matches:
        print('\nSin partidos LIVE pendientes. Todo OK.')
        return

    leagues_info = load_json(LEAGUES_INFO_PATH)

    print('\n[2] Verificando URLs de results...')
    by_league = defaultdict(list)
    for m in matches:
        by_league[(m['sport_name'], m['country_name'], m['league_name'])].append(m)

    for (sport, country, league), ms in by_league.items():
        url = find_results_url(leagues_info, sport, country, league)
        print('  [%s] %s_%s → %s' % (sport, country, league, url or 'NO ENCONTRADA'))

    if DRY_RUN:
        print('\nEjecuta con --run para procesar.')
        return

    print('\n[3] Iniciando browser...')
    driver = launch_navigator()
    login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
    dismiss_cookies(driver)

    stats = {'ok': 0, 'not_found': 0, 'skipped': 0, 'error': 0}

    try:
        for (sport_name, country_name, league_name), league_matches in by_league.items():
            results_url = find_results_url(leagues_info, sport_name, country_name, league_name)
            if not results_url:
                print('\n[WARN] URL no encontrada: %s_%s' % (country_name, league_name))
                stats['not_found'] += len(league_matches)
                continue

            print('\n%s' % ('─' * 65))
            print('[%s] %s — %s' % (sport_name, country_name, league_name))
            print('URL: %s' % results_url)

            try:
                wait_update_page(driver, results_url, 'container__heading')
                dismiss_cookies(driver)
            except Exception as e:
                print('[ERROR] %s' % e)
                stats['error'] += len(league_matches)
                continue

            oldest_date = min(m['match_date'] for m in league_matches)
            load_until_date(driver, oldest_date)

            found = scan_results_page(driver, league_matches)

            for m in league_matches:
                if m['match_id'] not in found:
                    stats['not_found'] += 1
                    continue
                try:
                    ok = update_match_in_db(driver, m, found[m['match_id']], dry_run=False)
                    stats['ok' if ok else 'skipped'] += 1
                except Exception as e:
                    print('  [ERROR] %s: %s' % (m['name'], e))
                    stats['error'] += 1
    finally:
        driver.quit()

    print('\n%s' % ('=' * 65))
    print('RESUMEN:')
    print('  Actualizados → COMPLETED : %d' % stats['ok'])
    print('  No encontrados           : %d' % stats['not_found'])
    print('  Omitidos por usuario     : %d' % stats['skipped'])
    print('  Errores                  : %d' % stats['error'])
    print('=' * 65)


if __name__ == '__main__':
    main()
