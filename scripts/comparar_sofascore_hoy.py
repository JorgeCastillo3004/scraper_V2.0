"""Compara TODOS los partidos de hoy: SofaScore vs lo que FlashScore dejó en la BD.

A diferencia de live_sofascore_extract.py (que solo mira lo que está en juego en este
instante), esto recorre los partidos que la BD tiene HOY en cada liga mapeada y pone
al lado el marcador y el estado de las dos fuentes. Es la foto completa del día.

Reusa el driver abierto (tmp/sofascore_driver.json). SOLO LECTURA.

  sports_env/bin/python scripts/comparar_sofascore_hoy.py
  sports_env/bin/python scripts/comparar_sofascore_hoy.py --fecha 2026-09-05
"""
import sys, os, json, time, argparse
from datetime import date, timedelta
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from driver_session import get_driver
from sofascore_provider import (tournament_events, best_match, norm_name,
                                team_to_db, load_teams_map)

ap = argparse.ArgumentParser()
ap.add_argument('--fecha', default=None, help='YYYY-MM-DD (por defecto hoy)')
ap.add_argument('--deporte', default='todos')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

f = args.fecha or date.today().isoformat()
TODOS = json.load(open(os.path.join(ROOT, 'check_points', 'sofascore_map.json'), encoding='utf-8'))
deportes = ([k for k in TODOS if any(v.get('unique_id') for v in TODOS[k].values())]
            if args.deporte == 'todos' else [args.deporte])
teams = load_teams_map()
d = get_driver(args.session_file)
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()

print(f'\n{"="*116}\n  COMPARACIÓN DEL DÍA {f} — SofaScore  vs  BD (escrita por FlashScore)\n{"="*116}')
tot = igual = dif = falta = pendientes = adelanta = atrasa = 0

for dep in deportes:
    for clave, info in TODOS[dep].items():
        if not info.get('unique_id'):
            continue
        pais, _, liga = clave.partition('_')
        cur.execute("""
            SELECT m.name, m.status,
                   (SELECT string_agg(se.points::text, '-' ORDER BY md.home DESC)
                      FROM match_detail md
                      JOIN score_entity se ON se.match_detail_id = md.match_detail_id
                     WHERE md.match_id = m.match_id)
              FROM match m
              JOIN league  l ON m.league_id  = l.league_id
              JOIN sport   s ON l.sport_id   = s.sport_id
              JOIN country c ON l.country_id = c.country_id
             WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s AND m.match_date=%s
             ORDER BY m.name
        """, (dep, pais, liga, f))
        en_bd = cur.fetchall()
        if not en_bd:
            continue

        evs, vistos = [], set()
        for delta in (0, 1, -1):
            fx = (date.fromisoformat(f) + timedelta(days=delta)).isoformat()
            for e in tournament_events(d, info['unique_id'], fx, dep):
                if e['event_id'] not in vistos:
                    vistos.add(e['event_id']); evs.append(e)
            time.sleep(0.3)
        delDia = [e for e in evs if e['match_date'] == f] or evs

        print(f'\n  ── {dep}  ·  {pais}/{liga}  ({len(en_bd)} en la BD, {len(delDia)} en SofaScore) ──')
        print('  %-44s %-13s %-13s %-11s %s' % ('PARTIDO', 'SOFASCORE', 'FLASHSCORE', 'ESTADO SS', 'ESTADO BD'))
        usados = set()
        for name, status_bd, score_bd in en_bd:
            tot += 1
            libres = [e for e in delDia if id(e) not in usados]
            ev, sc, motivo = best_match(name, libres)
            if not ev:
                falta += 1
                print('  %-44s %-13s %-13s %-11s %s' % (name[:43], '—', score_bd or '—', f'({motivo})', status_bd))
                continue
            usados.add(id(ev))
            # Clasificación honesta. 'None-None' en SofaScore y '-1--1' en la BD son
            # LO MISMO: partido sin empezar. Y que SofaScore tenga resultado mientras la
            # BD sigue en -1 no es una discrepancia: es el respaldo yendo por delante,
            # que es justo para lo que existe.
            sin_ss = ev['score_home'] is None
            ss = 'sin empezar' if sin_ss else f"{ev['score_home']}-{ev['score_away']}"
            sin_bd = (not score_bd) or score_bd in ('-1--1', '-1.0--1.0')
            bd = 'sin empezar' if sin_bd else score_bd
            if sin_ss and sin_bd:
                pendientes += 1; marca = '·  ambos sin empezar'
            elif sin_bd and not sin_ss:
                adelanta += 1; marca = '★  SofaScore ya lo tiene, la BD no'
            elif sin_ss and not sin_bd:
                atrasa += 1; marca = '·  la BD va por delante'
            elif ss == bd:
                igual += 1; marca = '✓'
            else:
                dif += 1; marca = '⚠  DISCREPANCIA REAL'
            print('  %-44s %-13s %-13s %-11s %-10s %s' % (name[:43], ss, bd, ev['status'], status_bd, marca))

cur.close(); con.close()
print(f'\n{"="*116}')
print(f'  TOTAL {tot} partidos de la BD en esa fecha')
print(f'    ✓ marcador IDÉNTICO en ambas fuentes ....... {igual}')
print(f'    ★ SofaScore YA tiene el resultado, la BD no  {adelanta}   ← lo que aportaría el respaldo')
print(f'    · sin empezar en ambas ..................... {pendientes}')
print(f'    · la BD va por delante ..................... {atrasa}')
print(f'    ⚠ DISCREPANCIA REAL de marcador ............ {dif}')
print(f'    — no localizado en SofaScore ............... {falta}')
print(f'{"="*116}\n[fin] driver vivo intacto')
