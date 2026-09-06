"""Evalúa ESPN como FUENTE DE RESPALDO del live: ¿sus nombres de equipo cruzan
con los que ya están en la BD (que vienen de FlashScore)?

READ-ONLY: consulta la BD y la API pública de ESPN. No escribe nada.
El cruce por nombre es lo que decide la viabilidad: get_match_id busca por
nombre + fecha + liga + deporte, así que si los nombres no mapean, el respaldo
no encontraría los partidos (el mismo fallo que ya se ve con [DB-SKIP] en tenis).

  sports_env/bin/python scripts/_debug_evaluar_respaldo_espn.py
"""
import sys, os, json, re, requests
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from unidecode import unidecode

# liga en la BD (país, nombre)  ->  ruta de ESPN
MAPA = [
    (('ECUADOR', 'Liga Pro'),               'soccer/ecu.1'),
    (('PERU', 'Liga 1'),                    'soccer/per.1'),
    (('COLOMBIA', 'Primera A'),             'soccer/col.1'),
    (('CHILE', 'Liga de Primera'),          'soccer/chi.1'),
    (('BOLIVIA', 'Division Profesional'),   'soccer/bol.1'),
    (('ARGENTINA', 'Liga Profesional'),     'soccer/arg.1'),
    (('BRAZIL', 'Serie A Betano'),          'soccer/bra.1'),
    (('CHINA', 'Super League'),             'soccer/chn.1'),
    (('USA', 'MLB'),                        'baseball/mlb'),
    (('CANADA', 'CFL'),                     'football/cfl'),
]

GENERICOS = {'fc','cf','sc','ac','cd','club','deportivo','de','the','city','united','atletico',
             'atlético','sporting','real','cs','ec','se','ca','afc','cfc','sd','ad','cds'}

def norm(s):
    """Normaliza un nombre de equipo para comparar: sin acentos, sin puntuación,
    minúsculas y sin las palabras genéricas que cada sitio pone a su manera."""
    s = unidecode(str(s)).lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    toks = [t for t in s.split() if t not in GENERICOS]
    return ' '.join(toks) or s.strip()

def espn_equipos(ruta, dias=30):
    """Nombres de equipo vistos en ESPN en la ventana de fechas."""
    hoy = date.today()
    rango = f'{(hoy-timedelta(days=dias)):%Y%m%d}-{hoy:%Y%m%d}'
    url = f'https://site.api.espn.com/apis/site/v2/sports/{ruta}/scoreboard?dates={rango}'
    # OJO: ESPN devuelve 403 si se envían cabeceras de navegador (User-Agent Mozilla)
    # y responde 200 al cliente HTTP pelado. Verificado 2026-09-06.
    d = requests.get(url, timeout=25).json()
    eq, ev = set(), d.get('events', [])
    for e in ev:
        for c in e['competitions'][0]['competitors']:
            eq.add(c['team'].get('displayName', ''))
    return eq, len(ev)

def bd_equipos(cur, pais, liga, dias=30):
    """Nombres de equipo en la BD para esa liga (match.name = 'A~B')."""
    cur.execute("""
        SELECT DISTINCT m.name FROM match m
          JOIN league l ON m.league_id = l.league_id
          JOIN country c ON l.country_id = c.country_id
         WHERE c.country_name = %s AND l.league_name = %s
           AND m.match_date >= %s
    """, (pais, liga, date.today() - timedelta(days=dias)))
    eq = set()
    for (n,) in cur.fetchall():
        for parte in str(n).split('~'):
            if parte.strip():
                eq.add(parte.strip())
    return eq

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()

print('\n%-34s %6s %6s %8s %9s' % ('LIGA', 'ESPN', 'BD', 'CRUZAN', '% cruce'))
print('-' * 70)
tot_e = tot_ok = 0
sin_cruce = {}
for (pais, liga), ruta in MAPA:
    try:
        eq_e, n_ev = espn_equipos(ruta)
    except Exception as ex:
        print('%-34s  ERROR ESPN: %s' % (f'{pais}/{liga}', type(ex).__name__)); continue
    eq_b = bd_equipos(cur, pais, liga)
    if not eq_b:
        print('%-34s %6d %6d   (sin partidos recientes en la BD)' % (f'{pais}/{liga}', len(eq_e), 0)); continue
    nb = {norm(x): x for x in eq_b}
    ok, falla = [], []
    for x in eq_e:
        n = norm(x)
        hit = n in nb or any(n and (n in k or k in n) for k in nb)
        (ok if hit else falla).append(x)
    pct = 100.0 * len(ok) / max(len(eq_e), 1)
    tot_e += len(eq_e); tot_ok += len(ok)
    print('%-34s %6d %6d %8d %8.0f%%' % (f'{pais}/{liga}', len(eq_e), len(eq_b), len(ok), pct))
    if falla:
        sin_cruce[f'{pais}/{liga}'] = (sorted(falla)[:6], sorted(nb.values())[:6])

print('-' * 70)
print('TOTAL: %d equipos de ESPN, %d cruzan → %.0f%%' % (tot_e, tot_ok, 100.0*tot_ok/max(tot_e,1)))

if sin_cruce:
    print('\nEjemplos que NO cruzan (izq = ESPN, der = muestra de la BD):')
    for liga, (f, b) in list(sin_cruce.items())[:5]:
        print(f'\n  {liga}')
        print(f'    ESPN sin par : {f}')
        print(f'    BD (muestra) : {b}')
cur.close(); con.close()
