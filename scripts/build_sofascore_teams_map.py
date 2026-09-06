"""Genera el MAPA DE EQUIPOS SofaScore → BD. SOLO LECTURA.

Los nombres nunca coinciden entre proveedores ('Atlético Nacional' en SofaScore es
'Atl. Nacional' en la BD). La similitud automática acierta, pero depender de ella en
producción es frágil: un empate de puntuación escribiría el marcador en el partido
equivocado. Este script congela esas correspondencias en
`check_points/sofascore_teams_map.json`, que pasa a ser la verdad, y deja marcadas
las dudosas para repasarlas a mano.

Se apoya en el driver YA ABIERTO (tmp/sofascore_driver.json) y nunca lo cierra.

  sports_env/bin/python scripts/build_sofascore_teams_map.py --deporte Football --dias 7
"""
import sys, os, json, time, argparse
from datetime import date, timedelta
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from driver_session import get_driver
from sofascore_provider import tournament_events, best_match, norm_name, similar_match

ap = argparse.ArgumentParser()
ap.add_argument('--deporte', default='Football')
ap.add_argument('--dias', type=int, default=7)
ap.add_argument('--umbral-seguro', type=float, default=0.75,
                help='a partir de aquí el par se da por bueno; por debajo queda "revisar"')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

MAPA_LIGAS = os.path.join(ROOT, 'check_points', 'sofascore_map.json')
MAPA_EQUIPOS = os.path.join(ROOT, 'check_points', 'sofascore_teams_map.json')

ligas = json.load(open(MAPA_LIGAS, encoding='utf-8')).get(args.deporte, {})
ligas = {k: v for k, v in ligas.items() if v.get('unique_id')}
print(f'Ligas mapeadas ({args.deporte}): {len(ligas)}')

mapa = {}
if os.path.exists(MAPA_EQUIPOS):
    try:
        mapa = json.load(open(MAPA_EQUIPOS, encoding='utf-8'))
    except Exception:
        mapa = {}
mapa.setdefault(args.deporte, {})

d = get_driver(args.session_file)
hoy = date.today()
nuevos = revisar = ya = 0

for clave, info in ligas.items():
    pais, _, liga = clave.partition('_')
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute("""
        SELECT m.name, m.match_date FROM match m
          JOIN league  l ON m.league_id  = l.league_id
          JOIN sport   s ON l.sport_id   = s.sport_id
          JOIN country c ON l.country_id = c.country_id
         WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s
           AND m.match_date BETWEEN %s AND %s
    """, (args.deporte, pais, liga, hoy - timedelta(days=args.dias), hoy + timedelta(days=args.dias)))
    partidos = cur.fetchall()
    cur.close(); con.close()
    if not partidos:
        continue

    # eventos de SofaScore en la misma ventana (deduplicados)
    evs, vistos = [], set()
    fechas = sorted({p[1].isoformat() for p in partidos})
    for f in fechas:
        for delta in (0, 1, -1):
            fx = (date.fromisoformat(f) + timedelta(days=delta)).isoformat()
            for e in tournament_events(d, info['unique_id'], fx, args.deporte):
                if e['event_id'] not in vistos:
                    vistos.add(e['event_id']); evs.append(e)
            time.sleep(0.3)

    mapa[args.deporte].setdefault(clave, {})
    tabla = mapa[args.deporte][clave]
    print(f'\n  {pais}/{liga}: {len(partidos)} partidos en la BD, {len(evs)} en SofaScore')
    for name, _f in partidos:
        partes = str(name).split('~')
        if len(partes) != 2:
            continue
        ev, score, via = best_match(name, evs)
        if not ev:
            continue
        for bd_nombre, ss_nombre in ((partes[0], ev['home']), (partes[1], ev['away'])):
            if ss_nombre in tabla:
                ya += 1
                continue
            s_ind = similar_match(bd_nombre, bd_nombre, ss_nombre, ss_nombre)
            entrada = {'bd': bd_nombre, 'score': round(min(score, s_ind), 2)}
            if min(score, s_ind) < args.umbral_seguro:
                entrada['revisar'] = True
                revisar += 1
                print(f'     ? {ss_nombre:32s} → {bd_nombre:28s} (score {entrada["score"]:.2f}) REVISAR')
            else:
                nuevos += 1
                print(f'     ✓ {ss_nombre:32s} → {bd_nombre:28s} (score {entrada["score"]:.2f})')
            tabla[ss_nombre] = entrada

os.makedirs(os.path.dirname(MAPA_EQUIPOS), exist_ok=True)
with open(MAPA_EQUIPOS, 'w', encoding='utf-8') as f:
    json.dump(mapa, f, ensure_ascii=False, indent=2)
total = sum(len(v) for v in mapa[args.deporte].values())
print(f'\nEquipos mapeados: {total} (nuevos {nuevos}, a revisar {revisar}, ya existentes {ya})')
print(f'Guardado en {MAPA_EQUIPOS}')
print('[fin] driver vivo intacto')
