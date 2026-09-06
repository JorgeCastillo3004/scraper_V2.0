"""SC4 — Cobertura de CATÁLOGO de SofaScore vs las ligas de la BD.

Criterio de Jorge: gana la fuente con MÁS DATOS, conservando la BD actual, empezando
por el Live. Medir sobre `events/live` es una foto instantánea (solo ve lo que se
juega en ese minuto), así que aquí se cruza el CATÁLOGO completo: por cada deporte
se piden sus categorías (países) y las ligas de cada país, y se compara con las 77
ligas que realmente tienen partidos en `sports_db`.

Se consulta desde el navegador porque SofaScore da 403 a cualquier cliente HTTP.
Reusa el driver vivo, nunca hace quit. READ-ONLY.

  sports_env/bin/python scripts/_debug_cobertura_sofascore.py
"""
import sys, os, re, time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from unidecode import unidecode
from driver_session import get_driver

SPORTS = {'Football': 'football', 'Baseball': 'baseball', 'Basketball': 'basketball',
          'Hockey': 'ice-hockey', 'American Football': 'american-football', 'Tennis': 'tennis'}
GENERICOS = {'fc','cf','sc','ac','cd','club','de','la','el','liga','league','division',
             'primera','pro','the','of','and','betano'}

def norm(s):
    s = unidecode(str(s)).lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return ' '.join(t for t in s.split() if t not in GENERICOS) or s.strip()

d = get_driver(); d.set_script_timeout(90)
if 'sofascore' not in (d.current_url or ''):
    d.get('https://www.sofascore.com'); time.sleep(4)

def api(path):
    return d.execute_async_script("""
        const cb = arguments[arguments.length-1];
        fetch(arguments[0]).then(r=>r.json()).then(j=>cb(j)).catch(e=>cb({__error:String(e)}));
    """, 'https://api.sofascore.com/api/v1' + path)

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

print('\n%-18s %7s %8s %9s %10s' % ('DEPORTE', 'LIGAS BD', 'CUBIERTAS', '% ligas', '% partidos'))
print('-' * 66)
faltan, tot_ok, tot, p_ok_g, p_g = {}, 0, 0, 0, 0
for sport, ligas in sorted(bd.items()):
    slug = SPORTS.get(sport)
    if not slug:
        continue
    cats = api(f'/sport/{slug}/categories')
    if not isinstance(cats, dict) or 'categories' not in cats:
        print('%-18s  no se pudo leer el catálogo' % sport); continue
    # países de la BD para este deporte (para no pedir las ~200 categorías)
    quiero = {norm(p) for p, _, _ in ligas}
    catalogo = set()
    for c in cats['categories']:
        if norm(c.get('name', '')) not in quiero:
            continue
        t = api(f"/category/{c['id']}/unique-tournaments")
        for grupo in (t.get('groups') or []) if isinstance(t, dict) else []:
            for ut in grupo.get('uniqueTournaments', []):
                catalogo.add((norm(c.get('name','')), norm(ut.get('name',''))))
        time.sleep(0.4)
    solo = {l for _, l in catalogo}
    ok, no, p_ok, p_tot = 0, [], 0, 0
    for pais, liga, n in ligas:
        p_tot += n
        hit = (norm(pais), norm(liga)) in catalogo or norm(liga) in solo \
              or any(norm(liga) in l or l in norm(liga) for l in solo if l)
        if hit: ok += 1; p_ok += n
        else:   no.append((pais, liga, n))
    tot_ok += ok; tot += len(ligas); p_ok_g += p_ok; p_g += p_tot
    print('%-18s %7d %8d %8.0f%% %9.0f%%' % (sport, len(ligas), ok,
          100.0*ok/max(len(ligas),1), 100.0*p_ok/max(p_tot,1)))
    if no: faltan[sport] = sorted(no, key=lambda x: -x[2])[:5]

print('-' * 66)
print('TOTAL: %d de %d ligas (%.0f%%)  |  %d de %d partidos (%.0f%%)'
      % (tot_ok, tot, 100.0*tot_ok/max(tot,1), p_ok_g, p_g, 100.0*p_ok_g/max(p_g,1)))
if faltan:
    print('\nLigas de la BD que NO aparecen en el catálogo de SofaScore:')
    for sport, items in faltan.items():
        print(f'\n  {sport}')
        for pais, liga, n in items:
            print(f'     {n:5d} partidos  {pais} / {liga}')
print('\n[fin] driver vivo intacto')
