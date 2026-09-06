"""Construye el mapeo LIGA de la BD ↔ torneo de SofaScore. SOLO LECTURA.

Es la pieza que decide si el respaldo escribe en el partido correcto (SC6 del roadmap).
Para cada liga de la BD con partidos en la ventana pedida, busca su torneo equivalente
en SofaScore por dos vías:
  1. entre los torneos que SofaScore programa esos días (país + nombre);
  2. si no aparece, por su buscador.
Guarda el resultado en check_points/sofascore_map.json, con el grado de confianza de
cada correspondencia para que las dudosas se revisen a mano.

Usa el DRIVER YA ABIERTO (tmp/sofascore_driver.json) y nunca lo cierra.

  sports_env/bin/python scripts/build_sofascore_map.py --deporte Football --dias 4
"""
import sys, os, json, time, argparse
from datetime import date, timedelta
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from driver_session import get_driver
from sofascore_provider import scheduled_tournaments, search_tournament, norm_name

ap = argparse.ArgumentParser()
ap.add_argument('--deporte', default='Football')
ap.add_argument('--dias', type=int, default=4, help='días hacia delante a explorar')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

MAPA = os.path.join(ROOT, 'check_points', 'sofascore_map.json')

# ── ligas de la BD con partidos en la ventana ────────────────────────────────
hoy = date.today()
hasta = hoy + timedelta(days=args.dias)
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()
cur.execute("""
    SELECT c.country_name, l.league_name, count(m.match_id)
      FROM match m
      JOIN league  l ON m.league_id  = l.league_id
      JOIN sport   s ON l.sport_id   = s.sport_id
      JOIN country c ON l.country_id = c.country_id
     WHERE s.name = %s AND m.match_date BETWEEN %s AND %s
     GROUP BY 1, 2 ORDER BY 3 DESC
""", (args.deporte, hoy, hasta))
ligas = cur.fetchall()
cur.close(); con.close()
print(f'Ligas de {args.deporte} con partidos entre {hoy} y {hasta}: {len(ligas)}')

d = get_driver(args.session_file)

# ── catálogo de torneos que SofaScore programa esos días ─────────────────────
catalogo = {}
for i in range(args.dias + 1):
    f = (hoy + timedelta(days=i)).isoformat()
    ts = scheduled_tournaments(d, args.deporte, f)
    for t in ts:
        if t['unique_id']:
            catalogo[t['unique_id']] = t
    print(f'  {f}: {len(ts)} torneos programados (catálogo acumulado: {len(catalogo)})')
    time.sleep(0.4)

por_pais = defaultdict(list)
for t in catalogo.values():
    por_pais[norm_name(t['country'])].append(t)

# ── emparejar cada liga de la BD ─────────────────────────────────────────────
mapa = {}
if os.path.exists(MAPA):
    try:
        mapa = json.load(open(MAPA, encoding='utf-8'))
    except Exception:
        mapa = {}
mapa.setdefault(args.deporte, {})

print('\n%-34s %-38s %s' % ('LIGA EN LA BD', 'TORNEO EN SOFASCORE', 'CONFIANZA'))
print('-' * 92)
for pais, liga, n in ligas:
    clave = f'{pais}_{liga}'
    cands = por_pais.get(norm_name(pais), [])
    nl = norm_name(liga)
    elegido, confianza = None, ''
    # comparar también SIN espacios: la BD dice 'Liga Pro' y SofaScore 'LigaPro Serie A'
    sin_esp = nl.replace(' ', '')
    exactos = [t for t in cands if norm_name(t['name']) == nl]
    if exactos:
        elegido, confianza = exactos[0], 'exacta'
    else:
        parciales = [t for t in cands
                     if nl and (nl in norm_name(t['name']) or norm_name(t['name']) in nl
                                or sin_esp in norm_name(t['name']).replace(' ', '')
                                or norm_name(t['name']).replace(' ', '') in sin_esp)]
        if len(parciales) == 1:
            elegido, confianza = parciales[0], 'parcial'
        elif len(parciales) > 1:
            # varias candidatas: quedarse con la de nombre más parecido en longitud
            parciales.sort(key=lambda t: abs(len(norm_name(t['name'])) - len(nl)))
            elegido, confianza = parciales[0], 'AMBIGUA (revisar)'
        else:
            # buscador: primero por el nombre de la liga, luego por el país (que suele
            # devolver todas sus competiciones)
            # Último recurso: TOKENS compartidos. 'Serie A Betano' (BD) y
            # 'Brasileirão Betano' (SofaScore) no se contienen, pero comparten el
            # token distintivo 'betano'. Se puntúa y se exige al menos uno no trivial.
            TRIVIALES = {'a', 'b', 'serie', 'liga', 'primera', 'division', 'league',
                         'championship', 'cup', 'copa', 'super', 'pro', '1', '2'}
            toks_bd = set(nl.split())
            mejor, mejor_p = None, 0
            candidatas = list(cands)
            for consulta in (liga.replace(' ', '%20'), pais.replace(' ', '%20')):
                candidatas += [r for r in search_tournament(d, consulta)
                               if norm_name(r.get('country', '')) == norm_name(pais)]
                time.sleep(0.4)
            for r in candidatas:
                rn = norm_name(r['name'])
                comunes = toks_bd & set(rn.split())
                fuertes = comunes - TRIVIALES
                p = len(fuertes) * 10 + len(comunes)
                if rn == nl or sin_esp in rn.replace(' ', '') or rn.replace(' ', '') in sin_esp:
                    p += 50
                if p > mejor_p:
                    mejor, mejor_p = r, p
            if mejor and mejor_p >= 10:          # al menos un token distintivo en común
                elegido, confianza = mejor, 'tokens (revisar)'
    if elegido:
        mapa[args.deporte][clave] = {
            'unique_id': elegido['unique_id'], 'sofascore_name': elegido['name'],
            'sofascore_country': elegido.get('country', ''), 'confianza': confianza,
            'partidos_bd': n,
        }
        print('%-34s %-38s %s' % (f'{pais}/{liga}'[:33],
                                  f"{elegido.get('country','')}/{elegido['name']}"[:37], confianza))
    else:
        mapa[args.deporte][clave] = {'unique_id': None, 'confianza': 'SIN CORRESPONDENCIA',
                                     'partidos_bd': n}
        print('%-34s %-38s %s' % (f'{pais}/{liga}'[:33], '—', 'SIN CORRESPONDENCIA'))

os.makedirs(os.path.dirname(MAPA), exist_ok=True)
with open(MAPA, 'w', encoding='utf-8') as f:
    json.dump(mapa, f, ensure_ascii=False, indent=2)

res = defaultdict(int)
for v in mapa[args.deporte].values():
    res[v['confianza']] += 1
print('\nResumen:', dict(res))
print(f'Mapa guardado en {MAPA}')
print('[fin] driver vivo intacto')
