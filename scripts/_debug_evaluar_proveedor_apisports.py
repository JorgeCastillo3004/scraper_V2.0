"""SC4 — Mide la cobertura REAL de API-Sports contra las ligas que hay en la BD.

El roadmap exige evaluar "contra los league_id que realmente están en sports_db,
no contra la lista de marketing del proveedor". Eso hace esto: pide las ligas de
cada deporte a API-Sports y las cruza con las de la BD.

READ-ONLY (consulta la BD y la API; no escribe nada).
Necesita una key gratuita de https://dashboard.api-football.com/register
(100 peticiones/día por API, sin tarjeta), pasada por entorno:

    API_SPORTS_KEY=xxxx sports_env/bin/python scripts/_debug_evaluar_proveedor_apisports.py
"""
import sys, os, re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import requests, psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from unidecode import unidecode

KEY = os.environ.get('API_SPORTS_KEY', '').strip()
if not KEY:
    sys.exit('Falta API_SPORTS_KEY (regístrate gratis en dashboard.api-football.com/register)')

# deporte en la BD -> host de la API correspondiente (API-Sports es una API por deporte)
HOSTS = {
    'Football':          'v3.football.api-sports.io',
    'Baseball':          'v1.baseball.api-sports.io',
    'Basketball':        'v1.basketball.api-sports.io',
    'Hockey':            'v1.hockey.api-sports.io',
    'American Football': 'v1.american-football.api-sports.io',
}
GENERICOS = {'fc','cf','sc','ac','cd','club','de','la','el','liga','league','division','primera','pro'}

def norm(s):
    s = unidecode(str(s)).lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(t for t in s.split() if t not in GENERICOS) or s.strip()

def ligas_api(host):
    r = requests.get(f'https://{host}/leagues', headers={'x-apisports-key': KEY}, timeout=30)
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}'
    d = r.json()
    if d.get('errors'):
        return None, str(d['errors'])[:120]
    out = []
    for item in d.get('response', []):
        liga = item.get('league') or item          # el formato varía entre deportes
        pais = item.get('country') or {}
        out.append((str(pais.get('name') or ''), str(liga.get('name') or '')))
    return out, None

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

print('\n%-18s %6s %8s %9s %s' % ('DEPORTE', 'BD', 'EN API', '% cubierto', 'partidos cubiertos'))
print('-' * 78)
faltantes = {}
for sport, ligas in sorted(bd.items()):
    host = HOSTS.get(sport)
    if not host:
        print('%-18s %6d   (API-Sports no tiene API para este deporte)' % (sport, len(ligas)))
        continue
    api, err = ligas_api(host)
    if api is None:
        print('%-18s %6d   ERROR: %s' % (sport, len(ligas), err))
        continue
    idx = {(norm(p), norm(l)) for p, l in api}
    solo_liga = {norm(l) for _, l in api}
    ok, no, part_ok, part_tot = [], [], 0, 0
    for pais, liga, n in ligas:
        part_tot += n
        hit = (norm(pais), norm(liga)) in idx or norm(liga) in solo_liga
        (ok if hit else no).append((pais, liga, n))
        if hit:
            part_ok += n
    print('%-18s %6d %8d %8.0f%%  %d/%d' % (sport, len(ligas), len(ok),
          100.0*len(ok)/max(len(ligas),1), part_ok, part_tot))
    if no:
        faltantes[sport] = sorted(no, key=lambda x: -x[2])[:8]

print('\nLigas de la BD que el proveedor NO cubre (las de más partidos):')
for sport, items in faltantes.items():
    print(f'\n  {sport}')
    for pais, liga, n in items:
        print(f'     {n:5d} partidos  {pais} / {liga}')
