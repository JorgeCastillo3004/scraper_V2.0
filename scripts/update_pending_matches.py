#!/usr/bin/env python3
"""
update_pending_matches.py — Completa partidos pendientes reusando el driver vivo.

Transcribe el flujo VALIDADO en el notebook de pruebas
(notebooks/pruebas_etapas_RUSSIA_Premier_League.ipynb), reusando exactamente las
mismas funciones de scripts/fix_live_matches.py:
    get_pending_live_matches / get_stats_backfill_matches / find_results_url /
    load_until_date / scan_with_coverage  (+ los primitivos de extracción).

Modos (los que se exponen en el frontend):
  --mode rapido     solo resultados: update_score + status=COMPLETED (sin stats, sin navegar)
  --mode completo   score + estadísticas: navega cada match y escribe score+status+statistic
  --solo-sin-stats  backfill: solo COMPLETED con score!=-1 y statistic vacío; fuerza 'completo'
                    y escribe ÚNICAMENTE statistic (no toca score ni status)

Por defecto DRY-RUN (no escribe). --apply para escribir en DB.
Reusa el driver vivo (driver_session.get_driver); NUNCA hace driver.quit().

Uso:
    python scripts/update_pending_matches.py --league "FOOTBALL/RUSSIA_Premier League" --mode rapido
    python scripts/update_pending_matches.py --league "FOOTBALL/RUSSIA_Premier League" --mode completo --apply
    python scripts/update_pending_matches.py --league "FOOTBALL/RUSSIA_Premier League" --solo-sin-stats --apply
"""
import os
import sys
import json
import time
import argparse
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import psycopg2

from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from common_functions import wait_update_page, dismiss_cookies, load_json
from data_base import get_math_details_ids, update_score, update_match_status
from milestone4 import wait_load_details, get_match_info, get_statistics_game, retry_match
from scripts.fix_live_matches import (
    get_pending_live_matches, get_stats_backfill_matches, find_results_url,
    load_until_date, scan_with_coverage,
)
from scripts.driver_session import get_driver

LEAGUES_INFO_PATH = 'check_points/leagues_info.json'
# Archivo de control que escribe el panel (process_manager) para pausar/parar.
_CONTROL_FILE = os.path.join(ROOT, 'logs', 'run_control_update_matches.json')


def _read_control():
    try:
        with open(_CONTROL_FILE, encoding='utf-8') as f:
            return json.load(f).get('command', 'none')
    except Exception:
        return 'none'


def _write_control(cmd):
    try:
        os.makedirs(os.path.dirname(_CONTROL_FILE), exist_ok=True)
        with open(_CONTROL_FILE, 'w', encoding='utf-8') as f:
            json.dump({'command': cmd}, f)
    except Exception:
        pass


def _check_control():
    """Control cooperativo (chequeado ENTRE matches). NO cierra el driver: queda
    disponible para otra ejecución. (Detener real = kill desde el panel.)
      - 'stop'   -> SystemExit (sale limpio entre partidos)
      - 'pause'  -> espera en bucle hasta 'resume' o 'stop'
    """
    cmd = _read_control()
    if cmd == 'stop':
        print('[INFO] stop recibido — saliendo entre partidos (driver intacto).')
        _write_control('none')
        raise SystemExit('stop solicitado')
    if cmd == 'pause':
        print('[INFO] pausado — esperando reanudación...')
        while True:
            time.sleep(2)
            cmd = _read_control()
            if cmd == 'resume':
                _write_control('none')
                print('[INFO] reanudado.')
                break
            if cmd == 'stop':
                print('[INFO] stop durante pausa — saliendo (driver intacto).')
                _write_control('none')
                raise SystemExit('stop durante pausa')


def _extract_statistic(driver, scraped):
    """Extrae el statistic del detalle (mismos primitivos que update_match_in_db)."""
    link = scraped['link_details']
    event_info = {'home': scraped.get('home', ''), 'visitor': scraped.get('visitor', '')}

    def _extract(drv):
        wait_load_details(drv, link)
        get_match_info(drv, event_info)
        return get_statistics_game(drv)

    statistic = '{}'
    try:
        r = retry_match(driver, link, _extract)
        if r:
            statistic = r
    except Exception as e:
        print('    [WARN] sin estadisticas: %s' % e)
    return statistic


def _write_statistic(match_id, statistic):
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute('UPDATE match SET statistic = %s WHERE match_id = %s', (str(statistic), match_id))
    con.commit(); cur.close(); con.close()


def process_match(driver, m, scraped, *, mode, es_backfill, apply):
    """Procesa un match según modo. dry-run imprime lo que escribiría; apply escribe.
    Reglas (validadas en el notebook):
      - rapido   : update_score + status=COMPLETED (sin stats)
      - completo : score + status + statistic
      - backfill : SOLO statistic (no toca score/status); requiere score!=-1
    Devuelve 'ok' | 'skip' | 'error'.
    """
    match_id = m['match_id']
    name     = m['name']
    home_r   = scraped['home_result']
    vis_r    = scraped['visitor_result']

    quiere_stats = (mode == 'completo') or es_backfill
    # Guard: el modo que extrae estadísticas exige resultado real (!= -1)
    if quiere_stats and (str(home_r) == '-1' or str(vis_r) == '-1'):
        print('  [SKIP stats] %s: score aún -1, no se extraen estadísticas' % name)
        if es_backfill:
            return 'skip'        # backfill sin resultado real: nada que hacer
        quiere_stats = False     # completo: al menos actualiza el resultado

    statistic = None
    if quiere_stats:
        statistic = _extract_statistic(driver, scraped)
        try:    n_stats = len(eval(str(statistic)))
        except Exception: n_stats = 0
    else:
        n_stats = None

    dict_detail = get_math_details_ids(match_id)   # {match_detail_id: home_flag}

    # ---- log de lo que se escribiría ----
    print('  [%s] %s | score %s-%s%s' % (
        ('backfill' if es_backfill else mode), name, home_r, vis_r,
        '' if n_stats is None else (' | stats=%d' % n_stats)))
    if not apply:
        if es_backfill:
            print('      [DRY-RUN] UPDATE match.statistic (score/status NO se tocan)')
        elif mode == 'rapido':
            print('      [DRY-RUN] update_score %s + status=COMPLETED (statistic NO se toca)'
                  % {d: (home_r if hf else vis_r) for d, hf in dict_detail.items()})
        else:
            print('      [DRY-RUN] update_score + status=COMPLETED + UPDATE statistic')
        return 'ok'

    # ---- escrituras reales ----
    try:
        if not es_backfill:
            for detail_id, home_flag in dict_detail.items():
                points = home_r if home_flag else vis_r
                update_score({'match_detail_id': detail_id, 'points': points})
            update_match_status({'status': 'COMPLETED', 'match_id': match_id})
            print('      [SCORE] %s-%s + status=COMPLETED' % (home_r, vis_r))
        if quiere_stats:
            _write_statistic(match_id, statistic)
            print('      [STATS] %d indicadores guardados' % n_stats)
        return 'ok'
    except Exception as e:
        print('      [ERROR] %s: %s' % (name, e))
        return 'error'


def run(leagues, mode='completo', solo_sin_stats=False, apply=False):
    leagues_info = load_json(LEAGUES_INFO_PATH)

    # Resolver league_ids + metadata desde leagues_info
    league_ids = []
    meta = {}
    for spec in leagues:
        sport_key, league_key = spec.split('/', 1)
        try:
            info = leagues_info[sport_key][league_key]
        except KeyError:
            print('[WARN] %s no existe en leagues_info' % spec)
            continue
        lid = info['league_id']
        league_ids.append(lid)
        meta[lid] = {
            'sport_key': sport_key,
            'league_key': league_key,
            'results_url': info.get('results') or info.get('url'),
        }
    if not league_ids:
        print('[ABORT] no hay ligas válidas.')
        return

    if solo_sin_stats:
        mode = 'completo'
        es_backfill = True
        pop = get_stats_backfill_matches(league_ids)
    else:
        es_backfill = False
        idset = set(league_ids)
        pop = [m for m in get_pending_live_matches(verbose=False) if m['league_id'] in idset]

    print('=' * 78)
    print('UPDATE PENDING MATCHES | mode=%s solo_sin_stats=%s apply=%s' % (mode, solo_sin_stats, apply))
    print('Ligas: %s | población: %d partidos' % ([m['league_key'] for m in meta.values()], len(pop)))
    print('=' * 78)
    if not pop:
        print('Sin partidos a procesar para los filtros indicados.')
        return

    by_league = defaultdict(list)
    for m in pop:
        by_league[m['league_id']].append(m)

    driver = get_driver()   # reusa el driver vivo (start_driver.py); NUNCA quit()
    totals = defaultdict(int)

    for lid, ms in by_league.items():
        info = meta.get(lid)
        if not info or not info['results_url']:
            print('\n[SKIP] liga %s sin results_url' % lid)
            totals['skip'] += len(ms)
            continue
        print('\n' + '-' * 78)
        print('[%s] %s — %d partidos' % (info['sport_key'], info['league_key'], len(ms)))
        print('  results_url: %s' % info['results_url'])

        try:
            wait_update_page(driver, info['results_url'], 'container__heading')
            dismiss_cookies(driver)
        except Exception as e:
            print('  [ERROR] navegando results: %s' % e)
            totals['error'] += len(ms)
            continue

        oldest = min(m['match_date'] for m in ms if m['match_date'])
        load_until_date(driver, oldest)
        found = scan_with_coverage(driver, ms, label=info['league_key'])

        for m in ms:
            _check_control()   # pausa/stop cooperativo entre partidos
            if m['match_id'] not in found:
                totals['not_found'] += 1
                continue
            res = process_match(driver, m, found[m['match_id']],
                                mode=mode, es_backfill=es_backfill, apply=apply)
            totals[res] += 1

    print('\n' + '=' * 78)
    print('RESUMEN (apply=%s)' % apply)
    print('  Procesados OK   : %d' % totals['ok'])
    print('  No encontrados  : %d' % totals['not_found'])
    print('  Omitidos        : %d' % totals['skip'])
    print('  Errores         : %d' % totals['error'])
    print('=' * 78)
    print('[done] driver vivo intacto (sin quit).')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--league', action='append', default=None, required=True,
                   help='SPORT/COUNTRY_LeagueName (repetible)')
    p.add_argument('--mode', choices=['rapido', 'completo'], default='completo')
    p.add_argument('--solo-sin-stats', action='store_true',
                   help='backfill: solo COMPLETED sin statistic (score!=-1); fuerza completo')
    p.add_argument('--apply', action='store_true', help='escribe en DB (default dry-run)')
    args = p.parse_args()
    run(args.league, mode=args.mode, solo_sin_stats=args.solo_sin_stats, apply=args.apply)


if __name__ == '__main__':
    main()
