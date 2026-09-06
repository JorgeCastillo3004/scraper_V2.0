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
from sofascore_provider import (scheduled_tournaments, search_tournament,
                                tournament_events, norm_name)

ap = argparse.ArgumentParser()
ap.add_argument('--deporte', default='Football')
ap.add_argument('--desde', default=None,
                help='fecha inicial YYYY-MM-DD (por defecto hoy). Sirve para deportes\n                      fuera de temporada: se valida contra sus últimas jornadas.')
ap.add_argument('--dias', type=int, default=4, help='días hacia delante a explorar')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

MAPA = os.path.join(ROOT, 'check_points', 'sofascore_map.json')

# Las competiciones de selecciones no cuelgan de un país: la BD las guarda bajo
# 'WORLD', 'EUROPE', 'AFRICA'… y SofaScore las pone en la categoría 'International'
# (a veces 'World' o el nombre del continente). Sin esta equivalencia, EuroBasket o el
# Mundial FIBA quedan sin correspondencia.
REGIONES = {
    'world': {'world', 'international'},
    'europe': {'europe', 'international'},
    'africa': {'africa', 'international'},
    'asia': {'asia', 'international'},
    'north & central america': {'north and central america', 'international'},
    'south america': {'south america', 'international'},
    'australia & oceania': {'australia and oceania', 'oceania', 'international'},
}


# Marcas de competición DISTINTA (categorías inferiores, femenino, clasificación).
# Sin penalizarlas, 'World Cup' de básquet se emparejaba con 'FIBA U17 Basketball
# World Cup' y 'EuroBasket' con 'EuroBasket Qual.' — competiciones que no son la de
# la BD y cuyos partidos son otros.
MARCAS_DISTINTAS = ('u16', 'u17', 'u18', 'u19', 'u20', 'u21', 'u23', 'women', 'femenin',
                    'qual', 'youth', 'junior', 'amateur', 'friendly', 'reserve')


def penalizacion(nombre_ss, nombre_bd):
    """Cuánto restar a un candidato por parecer otra competición."""
    n, b = norm_name(nombre_ss), norm_name(nombre_bd)
    return sum(30 for m in MARCAS_DISTINTAS if m in n and m not in b)


def pais_compatible(pais_bd, pais_ss):
    """¿El país de la BD y la categoría de SofaScore son el mismo ámbito?"""
    a, b = norm_name(pais_bd), norm_name(pais_ss)
    if a == b:
        return True
    return b in REGIONES.get(a, set())



def equipos_bd(pais, liga, deporte, desde, hasta):
    """Equipos que la BD tiene en esa liga y ventana (normalizados)."""
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()
    cur.execute("""SELECT m.name, m.match_date FROM match m
                     JOIN league  l ON m.league_id  = l.league_id
                     JOIN sport   s ON l.sport_id   = s.sport_id
                     JOIN country c ON l.country_id = c.country_id
                    WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s
                      AND m.match_date BETWEEN %s AND %s""",
                (deporte, pais, liga, desde, hasta))
    eq, fechas = set(), set()
    for n, f in cur.fetchall():
        for parte in str(n).split('~'):
            if parte.strip():
                eq.add(norm_name(parte))
        fechas.add(f.isoformat())
    cur.close(); con.close()
    return eq, sorted(fechas)


def verificar_por_equipos(driver, unique_id, fechas, eq_bd, deporte, limite=3):
    """Cuántos equipos de la BD aparecen de verdad en ese torneo.

    El nombre puede engañar —la BD llama 'World Cup' a lo que es la clasificación
    europea del Mundial FIBA—, así que la prueba definitiva son los equipos: si el
    torneo no los contiene, no es el torneo, por mucho que el nombre se parezca."""
    vistos = set()
    for f in fechas[:limite]:
        for e in tournament_events(driver, unique_id, f, deporte):
            vistos.add(norm_name(e['home'])); vistos.add(norm_name(e['away']))
        time.sleep(0.3)
    return len(vistos & eq_bd), len(eq_bd)


# ── ligas de la BD con partidos en la ventana ────────────────────────────────
hoy = date.fromisoformat(args.desde) if args.desde else date.today()
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

# Correcciones manuales: mandan sobre cualquier heurística.
try:
    OVERRIDES = json.load(open(os.path.join(ROOT, 'check_points',
                                            'sofascore_overrides.json'), encoding='utf-8'))
except Exception:
    OVERRIDES = {}
OVR_LIGAS = (OVERRIDES.get('leagues', {}) or {}).get(args.deporte, {})

print('\n%-34s %-38s %s' % ('LIGA EN LA BD', 'TORNEO EN SOFASCORE', 'CONFIANZA'))
print('-' * 92)
for pais, liga, n in ligas:
    clave = f'{pais}_{liga}'
    fijado = OVR_LIGAS.get(clave)
    if fijado and fijado.get('unique_id'):
        mapa[args.deporte][clave] = {
            'unique_id': fijado['unique_id'],
            'sofascore_name': fijado.get('nota', 'fijado a mano'),
            'sofascore_country': pais, 'confianza': 'MANUAL (overrides)', 'partidos_bd': n}
        print('%-34s %-38s %s' % (f'{pais}/{liga}'[:33], f"id={fijado['unique_id']}", 'MANUAL (overrides)'))
        continue

    cands = por_pais.get(norm_name(pais), [])
    if not cands:      # competición internacional: buscar por ámbito
        cands = [t for lst in por_pais.values() for t in lst
                 if pais_compatible(pais, t['country'])]
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
        # descartar de plano las que son otra competición (U17, Qual., Women…)
        limpias = [t for t in parciales if penalizacion(t['name'], liga) == 0]
        if limpias:
            parciales = limpias
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
                for r in search_tournament(d, consulta):
                    if not pais_compatible(pais, r.get('country', '')):
                        continue
                    # el buscador mezcla deportes: descartar los de otro deporte
                    if r.get('sport') and norm_name(r['sport']) != norm_name(args.deporte):
                        continue
                    candidatas.append(r)
                time.sleep(0.4)
            for r in candidatas:
                rn = norm_name(r['name'])
                comunes = toks_bd & set(rn.split())
                fuertes = comunes - TRIVIALES
                p = len(fuertes) * 10 + len(comunes) - penalizacion(r['name'], liga)
                if rn == nl or sin_esp in rn.replace(' ', '') or rn.replace(' ', '') in sin_esp:
                    p += 50
                if p > mejor_p:
                    mejor, mejor_p = r, p
            if mejor and mejor_p >= 10:          # al menos un token distintivo en común
                elegido, confianza = mejor, 'tokens (revisar)'
    # VERIFICACIÓN por equipos: manda sobre el parecido del nombre
    if elegido and elegido.get('unique_id'):
        eq, fechas = equipos_bd(pais, liga, args.deporte, hoy - timedelta(days=args.dias), hasta)
        aciertos, total = verificar_por_equipos(d, elegido['unique_id'], fechas, eq, args.deporte)
        if total and aciertos == 0:
            # el nombre engañaba: probar el resto de candidatos del mismo ámbito
            # Ordenar por parecido de nombre antes de gastar llamadas: así se prueba
            # primero 'FIBA World Cup Qualification, Europe' y no la lista entera.
            def _afinidad(t):
                tn = set(norm_name(t['name']).split())
                return len(tn & set(nl.split())) - (penalizacion(t['name'], liga) / 30.0)
            alternativas = sorted([t for t in cands if t.get('unique_id') != elegido['unique_id']],
                                  key=_afinidad, reverse=True)
            for alt in alternativas[:12]:
                a2, _ = verificar_por_equipos(d, alt['unique_id'], fechas, eq, args.deporte, limite=2)
                if a2 > 0:
                    elegido, confianza = alt, f'verificado por equipos ({a2}/{total})'
                    break
            else:
                confianza = 'SIN VERIFICAR (0 equipos coinciden)'
        elif total:
            confianza = f'verificado por equipos ({aciertos}/{total})'

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
