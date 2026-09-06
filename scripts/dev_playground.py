"""
dev_playground.py
==================
Scratchpad de desarrollo iterativo para `fix_null_team_ids.py`.

FILOSOFIA
---------
Igual que trabajar en el notebook: te conectas al driver YA vivo (lanzado por
fix_null_team_ids.py una vez), pruebas funciones aisladas paso a paso, y
cuando una funciona la copias al script principal.

  Driver vivo ──── reuse via session_id ────► dev_playground.py
                                                    │
                                                    ├─ test_scan_league()
                                                    ├─ test_team_links_from_match()
                                                    ├─ test_create_team()
                                                    └─ test_update_match_detail()

PRECONDICION
------------
Hay un driver vivo con session guardada en `tmp/driver_session.json`.
Si no, lanzalo primero con:
    python scripts/fix_null_team_ids.py --league "FOOTBALL/AFRICA_World Cup" \
        --match-id b8bb3b8c-0acb-4dd0-93b7-8408e120e109
(eso hace login + guarda session, no importa que termine; el driver queda
detached gracias a setsid).

USO
---
    # Ejecutar TODO el playground en orden
    python scripts/dev_playground.py

    # Solo un test puntual (edita TESTS_TO_RUN abajo)
    python scripts/dev_playground.py --only scan

    # Modo interactivo (carga driver y deja shell Python)
    python scripts/dev_playground.py --shell
"""

import sys, os, argparse, code, datetime
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By

from scripts.fix_null_team_ids import (
    _reuse_driver_session, launch_detached_driver,
    get_team_links_from_match, ensure_team_created,
    update_match_detail_team, detect_null_team_matches,
    is_african_match,
)
from scripts.fix_live_matches import (
    find_results_url, load_until_date, scan_results_page,
)
from common_functions import (
    wait_update_page, dismiss_cookies, load_json, login,
)
from data_base import getdb, get_dict_league_ready
from config import FS_EMAIL, FS_PASSWORD

# ─── Constantes de prueba (editar libremente) ───────────────────────────────

LEAGUE_KEYS_TO_TEST = [('FOOTBALL', 'AFRICA_World Cup')]
TEST_MATCH_ID       = 'b8bb3b8c-0acb-4dd0-93b7-8408e120e109'   # Central Africa~Mali
TEST_MATCH_NAME     = 'Central Africa~Mali'
TEST_MATCH_DATE     = datetime.date(2025, 3, 24)


# ─── Helpers de setup ───────────────────────────────────────────────────────

def get_driver(or_login=True):
    """Reusa driver vivo. Si or_login=True y no hay sesion, lanza nuevo + login."""
    d = _reuse_driver_session()
    if d is not None:
        return d
    if not or_login:
        raise RuntimeError(
            "no hay driver vivo. Lanza primero con fix_null_team_ids.py"
        )
    print("[playground] sin driver vivo — lanzando uno nuevo")
    d = launch_detached_driver()
    login(d, email_=FS_EMAIL, password_=FS_PASSWORD)
    return d


def section(title):
    print(f'\n{"═"*72}\n{title}\n{"═"*72}')


# ─── Tests aislados (cada uno se puede correr solo) ─────────────────────────

def test_db_detection():
    """Verifica detect_null_team_matches y filtro is_african_match."""
    section("TEST 1: deteccion en DB")
    leagues_info = load_json('check_points/leagues_info.json')
    league_ids = [
        leagues_info[sk][lk]['league_id']
        for sk, lk in LEAGUE_KEYS_TO_TEST
    ]
    con = getdb()
    try:
        rows = detect_null_team_matches(con, league_ids)
        print(f"  total con team_id NULL: {len(rows)}")
        afr = [r for r in rows if is_african_match(r['name'])]
        print(f"  ambos equipos africanos: {len(afr)}")
        for r in afr[:5]:
            print(f"    {r['match_date']} {r['name']}")
        # match_id puntual
        rows_pt = detect_null_team_matches(con, league_ids,
                                            match_id_filter=TEST_MATCH_ID)
        print(f"  test match_id puntual: {len(rows_pt)} fila(s)")
        if rows_pt:
            print(f"    → {rows_pt[0]['name']}  league_id={rows_pt[0]['league_id'][:8]}…")
    finally:
        con.close()


def test_scan_league(driver):
    """Verifica scroll + scan en la liga AFRICA."""
    section("TEST 2: scan de la liga AFRICA")
    leagues_info = load_json('check_points/leagues_info.json')
    info = leagues_info['FOOTBALL']['AFRICA_World Cup']
    results_url = info['results']

    print(f"  navegando a {results_url}")
    wait_update_page(driver, results_url, 'container__heading')
    dismiss_cookies(driver)

    target = [{
        'match_id':   TEST_MATCH_ID,
        'name':       TEST_MATCH_NAME,
        'match_date': TEST_MATCH_DATE,
    }]

    load_until_date(driver, TEST_MATCH_DATE)
    found = scan_results_page(driver, target)
    print(f"\n  encontrados: {list(found.keys())}")
    if TEST_MATCH_ID in found:
        print(f"  link_details: {found[TEST_MATCH_ID]['link_details']}")
    return found


def test_team_links_from_match(driver, match_url=None):
    """Verifica extraccion de team URLs desde la pagina del match."""
    section("TEST 3: extraer team URLs del match")
    match_url = match_url or (
        'https://www.flashscore.com/match/61N82zh2/#/match-summary/match-summary'
    )
    print(f"  navegando a {match_url}")
    wait_update_page(driver, match_url, 'duelParticipant')
    dismiss_cookies(driver)

    home_url, away_url = get_team_links_from_match(driver)
    print(f"  home_url: {home_url}")
    print(f"  away_url: {away_url}")
    return home_url, away_url


def test_create_team(driver, team_url, dry_run=True):
    """Verifica creacion de team desde una URL (dry-run por default)."""
    section(f"TEST 4: ensure_team_created (dry_run={dry_run})")
    leagues_info = load_json('check_points/leagues_info.json')
    info = leagues_info['FOOTBALL']['AFRICA_World Cup']

    # FOOTBALL sport_id (lo sacamos de DB para no hardcodear)
    con = getdb()
    cur = con.cursor()
    cur.execute("SELECT sport_id FROM sport WHERE name='Football'")
    sport_id = cur.fetchone()[0]
    con.close()

    league_inf = {
        'sport_id':    sport_id,
        'sport_name':  'Football',
        'league_id':   info['league_id'],
        'league_name': 'World Cup',
        'season_id':   info['season_id'],
        'country_id':  info['country_id'],
    }
    dict_teams_db = get_dict_league_ready(sport_id=sport_id)

    team_id = ensure_team_created(
        driver, team_url, league_inf, dict_teams_db, sport_id, dry_run,
    )
    print(f"  team_id retornado: {team_id}")
    return team_id


def test_update_match_detail(con, match_id, home_team_id, away_team_id,
                              dry_run=True):
    """Verifica INSERT/UPDATE en match_detail."""
    section(f"TEST 5: update_match_detail (dry_run={dry_run})")
    stats = update_match_detail_team(
        con, match_id, home_team_id, away_team_id, dry_run,
    )
    print(f"  resultado: {stats}")
    return stats


# ─── Runner ─────────────────────────────────────────────────────────────────

ALL_TESTS = ('detection', 'scan', 'links', 'create', 'update', 'full')


def run_full_dry(driver):
    """Pipeline end-to-end en dry-run: detection → scan → links → create teams → update detail."""
    section("FULL PIPELINE DRY-RUN: Central Africa~Mali")

    # 1) Detection
    leagues_info = load_json('check_points/leagues_info.json')
    info = leagues_info['FOOTBALL']['AFRICA_World Cup']
    con = getdb()
    try:
        m = detect_null_team_matches(con, [info['league_id']],
                                       match_id_filter=TEST_MATCH_ID)[0]
        print(f"  match: {m['name']}  date={m['match_date']}  in_league={m['league_id'][:8]}…")

        # 2) Scan
        wait_update_page(driver, info['results'], 'container__heading')
        dismiss_cookies(driver)
        load_until_date(driver, m['match_date'])
        found = scan_results_page(driver, [{
            'match_id': m['match_id'], 'name': m['name'],
            'match_date': m['match_date'],
        }])
        scraped = found.get(m['match_id'])
        if not scraped:
            print("  [ABORT] match no encontrado en results")
            return
        match_url = scraped['link_details']

        # 3) Team links
        wait_update_page(driver, match_url, 'duelParticipant')
        dismiss_cookies(driver)
        home_url, away_url = get_team_links_from_match(driver)
        print(f"  home_url: {home_url}")
        print(f"  away_url: {away_url}")

        # 4) Create teams (dry-run)
        cur = con.cursor()
        cur.execute("SELECT sport_id FROM sport WHERE name='Football'")
        sport_id = cur.fetchone()[0]
        league_inf = {
            'sport_id': sport_id, 'sport_name': 'Football',
            'league_id': info['league_id'], 'league_name': 'World Cup',
            'season_id': info['season_id'], 'country_id': info['country_id'],
        }
        cache = get_dict_league_ready(sport_id=sport_id)

        home_id = ensure_team_created(driver, home_url, league_inf, cache, sport_id, True)
        away_id = ensure_team_created(driver, away_url, league_inf, cache, sport_id, True)

        # 5) update_match_detail (dry-run)
        stats = update_match_detail_team(con, m['match_id'], home_id, away_id, True)
        print(f"\n  RESULTADO: {stats}")
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--only', choices=ALL_TESTS, default=None,
                   help='Solo correr un test puntual')
    p.add_argument('--shell', action='store_true',
                   help='Despues de cargar driver, abre shell Python interactivo')
    p.add_argument('--no-launch', action='store_true',
                   help='Falla si no hay driver vivo (no lanza uno nuevo)')
    args = p.parse_args()

    driver = get_driver(or_login=not args.no_launch)
    print(f"\n[playground] driver listo — session_id={driver.session_id}")
    print(f"             current_url: {driver.current_url[:80]}")

    if args.shell:
        section("MODO SHELL — usa `d` para el driver")
        code.interact(local={'d': driver, **globals()})
        return

    only = args.only
    if only is None or only == 'detection':
        test_db_detection()
    if only is None or only == 'scan':
        test_scan_league(driver)
    if only is None or only == 'links':
        test_team_links_from_match(driver)
    if only is None or only == 'create':
        # solo prueba con la URL de home; cambia a away si quieres
        home_url = 'https://www.flashscore.com/team/central-africa/MiKwAcg9/'
        test_create_team(driver, home_url, dry_run=True)
    if only is None or only == 'update':
        con = getdb()
        try:
            test_update_match_detail(con, TEST_MATCH_ID,
                                     'fake-home-id', 'fake-away-id', True)
        finally:
            con.close()
    if only == 'full':
        run_full_dry(driver)

    print(f"\n[playground] driver SIGUE VIVO — session_id={driver.session_id}\n"
          f"             puerto: {driver.command_executor._url}")


if __name__ == '__main__':
    main()
