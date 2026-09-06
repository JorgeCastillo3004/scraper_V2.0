"""SC4 — Cobertura REAL de SofaScore contra las ligas de la BD, medida para el LIVE.

Criterio de Jorge: lo que manda es la CANTIDAD DE DATOS, conservando la BD actual,
empezando por la sección Live. Esto mide exactamente eso: cuántas de las ligas que
hoy están en `sports_db` aparecen en SofaScore, deporte por deporte.

SofaScore devuelve 403 a cualquier cliente HTTP, así que se consulta su API DESDE EL
NAVEGADOR ya abierto (fetch en el contexto de la página). Reusa el driver vivo y
NUNCA hace quit. READ-ONLY: no escribe en la BD ni en los JSON.

  sports_env/bin/python scripts/_debug_evaluar_respaldo_sofascore.py [--dias 3]
"""
import sys, os, re, json, time, argparse
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from unidecode import unidecode
from driver_session import get_driver

ap = argparse.ArgumentParser()
ap.add_argument('--dias', type=int, default=3, help='ventana de días hacia atrás')
args = ap.parse_args()

# deporte en la BD -> slug de SofaScore
SPORTS = {
    'Football': 'football', 'Baseball': 'baseball', 'Basketball': 'basketball',
    'Hockey': 'ice-hockey', 'American Football': 'american-football', 'Tennis': 'tennis',
}
GENERICOS = {'fc','cf','sc','ac','cd','club','de','la','el','liga','league','division',
             'primera','pro','the','of','and'}

def norm(s):
    s = unidecode(str(s)).lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(t for t in s.split() if t not in GENERICOS) or s.strip()

d = get_driver()
if 'sofascore' not in (d.current_url or ''):
    d.get('https://www.sofascore.com')     # el fetch debe salir del origen correcto
    time.sleep(4)

def api(path):
    """Llama a la API de SofaScore desde dentro del navegador (evita el 403)."""
    return d.execute_async_script("""
        const cb = arguments[arguments.length - 1];
        fetch(arguments[0], {headers: {'accept': 'application/json'}})
          .then(r => r.json()).then(j => cb(j)).catch(e => cb({__error: String(e)}));
    """, f'https://api.sofascore.com/api/v1{path}')

# ── ligas que hay en la BD ───────────────────────────────────────────────────
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()
cur.execute("""SELECT s.name, c.country_name, l.league_name, count(m.match_id)
                 FROM league l JOIN sport s ON l.sport_id=s.sport_id
                 JOIN country c ON l.country_id=c.country_id
                 JOIN match m ON m.league_id=l.league_id
                GROUP BY 1,2,3 ORDER BY 1,4 DESC""")
bd = defaultdict(list)
for sp, pais, liga, n in cur.fetchall():
    bd[sp].append((pais, liga, n))
cur.close(); con.close()

_EN_VIVO = {}
fechas = [(date.today() - timedelta(days=i)).isoformat() for i in range(args.dias)]
print('\nFoto EN VIVO de SofaScore (endpoint events/live) — %s' % date.today())
print('\n%-18s %8s %9s %9s %9s' % ('DEPORTE', 'EN VIVO', 'LIGAS SS', 'EN LA BD', '% ligas BD'))
print('-' * 74)

faltan_global = {}
tot_p_ok = tot_p = 0
for sport, ligas in sorted(bd.items()):
    slug = SPORTS.get(sport)
    if not slug:
        print('%-18s %6d   (deporte no consultado)' % (sport, len(ligas)))
        continue
    # SofaScore ya no expone scheduled-events por fecha (404); events/live sí, y es
    # justo lo que interesa para la sección LIVE.
    vistas, n_ev = set(), 0
    try:
        j = api(f'/sport/{slug}/events/live')
    except Exception as e:
        print('%-18s  ERROR navegador: %s' % (sport, type(e).__name__)); j = None
    if j and not j.get('__error'):
        for ev in j.get('events', []):
            n_ev += 1
            t = ev.get('tournament') or {}
            cat = (t.get('category') or {}).get('name', '')
            vistas.add((norm(cat), norm(t.get('name', ''))))
            vistas.add(('', norm((t.get('uniqueTournament') or {}).get('name', ''))))
    _EN_VIVO[sport] = (n_ev, len({v for v in vistas if v[1]}))
    solo_liga = {l for _, l in vistas}
    ok, no, p_ok, p_tot = 0, [], 0, 0
    for pais, liga, n in ligas:
        p_tot += n
        hit = (norm(pais), norm(liga)) in vistas or norm(liga) in solo_liga
        if hit:
            ok += 1; p_ok += n
        else:
            no.append((pais, liga, n))
    tot_p_ok += p_ok; tot_p += p_tot
    n_ev, n_lig = _EN_VIVO.get(sport, (0, 0))
    print('%-18s %8d %9d %9d %8.0f%%' % (sport, n_ev, n_lig, ok, 100.0*ok/max(len(ligas),1)))
    if no:
        faltan_global[sport] = sorted(no, key=lambda x: -x[2])[:6]

print('-' * 74)
print('Total de partidos EN VIVO que ofrece SofaScore ahora mismo: %d' % sum(v[0] for v in _EN_VIVO.values()))
print('Ligas distintas en vivo: %d' % sum(v[1] for v in _EN_VIVO.values()))
print('\nLigas de la BD sin partido en vivo AHORA (no significa que no las cubra):')
for sport, items in faltan_global.items():
    print(f'\n  {sport}')
    for pais, liga, n in items:
        print(f'     {n:5d} partidos  {pais} / {liga}')
print('\n[fin] driver vivo intacto')
