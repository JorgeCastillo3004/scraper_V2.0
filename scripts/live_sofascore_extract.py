"""EXTRACCIÓN EN VIVO de SofaScore comparada con lo que FlashScore dejó en la BD.

Se reengancha al driver que dejó abierto `scripts/start_sofascore.sh` (nunca abre ni
cierra navegadores) y, para cada partido en vivo, imprime:

    LIGA | PARTIDO | RESULTADO en SofaScore | RESULTADO en la BD (FlashScore) | ESTADO

Los nombres se traducen con check_points/sofascore_teams_map.json, de modo que el
partido se localiza por el nombre REAL de la BD y no por parecido.

SOLO LECTURA: no escribe en la base de datos.

  sports_env/bin/python scripts/live_sofascore_extract.py
  sports_env/bin/python scripts/live_sofascore_extract.py --deporte Football --loop 60
"""
import sys, os, json, time, argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from driver_session import get_driver
from sofascore_provider import (live_events, ensure_context, load_teams_map,
                                match_name_db, norm_name, best_match)

ap = argparse.ArgumentParser()
ap.add_argument('--deporte', default='Football',
                help="Football | Basketball | Baseball | Hockey | 'American Football' | todos")
ap.add_argument('--loop', type=int, default=0, help='repetir cada N segundos (0 = una vez)')
ap.add_argument('--todos', action='store_true',
                help='mostrar también los partidos de ligas que la BD no sigue')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

TODOS = json.load(open(os.path.join(ROOT, 'check_points', 'sofascore_map.json'),
                       encoding='utf-8'))
deportes = ([d for d in TODOS if any(v.get('unique_id') for v in TODOS[d].values())]
            if args.deporte.lower() == 'todos' else [args.deporte])
teams_map = load_teams_map()


def indice_ligas(dep):
    """torneo de SofaScore -> clave de liga en la BD ('COLOMBIA_Primera A')"""
    out = {}
    for clave, info in TODOS.get(dep, {}).items():
        if info.get('unique_id'):
            out[norm_name(info.get('sofascore_name', ''))] = clave
    return out

d = get_driver(args.session_file)


def resultado_en_bd(cur, sport, clave_liga, nombre_bd, fecha):
    """Marcador y estado que tiene la BD (lo escrito por FlashScore)."""
    pais, _, liga = clave_liga.partition('_')
    cur.execute("""
        SELECT m.status,
               (SELECT string_agg(se.points::text, '-' ORDER BY md.home DESC)
                  FROM match_detail md
                  JOIN score_entity se ON se.match_detail_id = md.match_detail_id
                 WHERE md.match_id = m.match_id)
          FROM match m
          JOIN league  l ON m.league_id  = l.league_id
          JOIN sport   s ON l.sport_id   = s.sport_id
          JOIN country c ON l.country_id = c.country_id
         WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s
           AND m.name=%s AND m.match_date=%s
    """, (sport, pais, liga, nombre_bd, fecha))
    r = cur.fetchone()
    return (r[0], r[1]) if r else (None, None)


def una_pasada(dep, ss_a_bd):
    ensure_context(d)
    eventos = live_events(d, dep)
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()

    print('\n' + '=' * 118)
    print(f'  {dep.upper()} EN VIVO — SofaScore vs BD (FlashScore)      '
          f'{datetime.now():%H:%M:%S}   |   {len(eventos)} partidos en vivo en SofaScore')
    print('=' * 118)
    print('%-26s %-42s %-11s %-11s %-9s' %
          ('LIGA', 'PARTIDO', 'SOFASCORE', 'BD/FLASH', 'ESTADO'))
    print('-' * 118)

    mostrados = iguales = distintos = solo_ss = 0
    for ev in eventos:
        clave = ss_a_bd.get(norm_name(ev['league_raw'])) or ss_a_bd.get(norm_name(ev['league_unique']))
        if not clave and not args.todos:
            continue
        nombre_bd, mapeado = (match_name_db(ev, dep, clave, teams_map)
                              if clave else (ev['match_name'], False))
        estado_bd = marcador_bd = None
        if clave:
            estado_bd, marcador_bd = resultado_en_bd(cur, dep, clave,
                                                     nombre_bd, ev['match_date'])
        ss = f"{ev['score_home']}-{ev['score_away']}"
        bd = marcador_bd if marcador_bd is not None else '—'
        if marcador_bd is None:
            solo_ss += 1
            nota = 'no está en la BD' if clave else 'liga no seguida'
        elif ss == bd:
            iguales += 1; nota = estado_bd or ''
        else:
            distintos += 1; nota = f'{estado_bd or ""} ⚠'
        mostrados += 1
        etiqueta = (clave or f"{ev['country_raw']}/{ev['league_raw']}")[:25]
        print('%-26s %-42s %-11s %-11s %-9s' % (etiqueta, nombre_bd[:41], ss, bd, nota))

    cur.close(); con.close()
    print('-' * 118)
    print(f'  mostrados: {mostrados} | marcador idéntico: {iguales} | '
          f'distinto: {distintos} | sin correspondencia en la BD: {solo_ss}')
    return mostrados
    if not args.todos:
        print('  (solo ligas mapeadas; usa --todos para ver el resto de lo que SofaScore tiene en vivo)')


def ronda():
    total = 0
    for dep in deportes:
        idx = indice_ligas(dep)
        if not idx:
            continue
        total += una_pasada(dep, idx) or 0
    return total


if args.loop:
    print(f'Comparando cada {args.loop}s ({", ".join(deportes)}). Ctrl+C para parar.')
    try:
        while True:
            ronda()
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print('\n[fin] driver vivo intacto')
else:
    ronda()
    print('\n[fin] driver vivo intacto')
