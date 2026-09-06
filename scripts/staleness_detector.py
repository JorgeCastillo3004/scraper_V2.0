"""SC10 — Detector de obsolescencia del scraper primario (FlashScore). SOLO LECTURA.

Responde a una única pregunta: **¿el primario sigue actualizando los datos?**
No actúa. Escribe su veredicto en tmp/staleness_status.json y nada más — detección y
acción van separadas para poder confiar en la detección antes de dejarla decidir
(es la condición que pone el propio roadmap).

Tres señales independientes:

  A · LATIDO   El proceso del live sigue escribiendo. Se mira el mtime de su log, no
               el heartbeat JSON: se comprobó que ese archivo conservaba la marca del
               arranque durante horas y habría dado por vivo a un proceso colgado.
  B · COLGADOS Partidos que llevan demasiado tiempo en estado LIVE. Si el primario
               muere a media tarde, deja partidos abiertos que nadie cierra.
  C · ATRASO   Partidos que la fuente de respaldo ya da por terminados y la BD no.
               Es la señal más directa de que el primario se está quedando atrás.

Umbrales calibrados con el comportamiento REAL observado (2026-09-06): un ciclo del
live tarda ~134 s y luego pausa 60 s, o sea ~3,2 min por vuelta.

  sports_env/bin/python scripts/staleness_detector.py
  sports_env/bin/python scripts/staleness_detector.py --con-respaldo   # añade la señal C
"""
import sys, os, json, argparse
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from failover import evaluar_primario

ap = argparse.ArgumentParser()
ap.add_argument('--latido-max', type=float, default=8.0,
                help='minutos sin escribir el log antes de dar el primario por parado '
                     '(default 8 = ~2,5 ciclos observados)')
ap.add_argument('--colgado-horas', type=float, default=6.0,
                help='horas en estado LIVE antes de considerar el partido colgado')
ap.add_argument('--con-sonda', action='store_true',
                help='sondear FlashScore en el navegador paralelo (tmp/flashscore_probe.json)')
ap.add_argument('--con-respaldo', action='store_true',
                help='añade la señal C comparando con SofaScore (requiere su driver)')
ap.add_argument('--servidor', default='scraper_server',
                help='host ssh donde corre el live; "local" para no consultar por ssh')
ap.add_argument('--log-remoto', default='/home/scraper/live_v2/logs/live_persist.log')
args = ap.parse_args()

ahora = datetime.now(timezone.utc)

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()
veredicto, señales, detalle = evaluar_primario(
    cur, servidor=args.servidor, ruta_log=args.log_remoto,
    latido_max=args.latido_max, colgado_horas=args.colgado_horas,
    con_sonda=args.con_sonda)

cur.execute("SELECT count(*) FROM match WHERE status='LIVE'")
detalle['en_vivo_ahora'] = f'{cur.fetchone()[0]} partidos en estado LIVE en la BD'

# ── C · ATRASO frente al respaldo (opcional) ─────────────────────────────────
if args.con_respaldo:
    try:
        from driver_session import get_driver
        from sofascore_provider import tournament_events, best_match
        d = get_driver(os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
        mapa = json.load(open(os.path.join(ROOT, 'check_points', 'sofascore_map.json'),
                              encoding='utf-8'))
        hoy = ahora.date().isoformat()
        atrasados = 0
        for dep, ligas in mapa.items():
            for clave, info in ligas.items():
                if not info.get('unique_id'):
                    continue
                pais, _, liga = clave.partition('_')
                cur.execute("""SELECT m.name FROM match m
                                 JOIN league  l ON m.league_id  = l.league_id
                                 JOIN sport   s ON l.sport_id   = s.sport_id
                                 JOIN country c ON l.country_id = c.country_id
                                WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s
                                  AND m.match_date=%s AND m.status <> 'COMPLETED'""",
                            (dep, pais, liga, hoy))
                pendientes = [r[0] for r in cur.fetchall()]
                if not pendientes:
                    continue
                evs = [e for e in tournament_events(d, info['unique_id'], hoy, dep)
                       if e['status'] == 'COMPLETED']
                for name in pendientes:
                    ev, _s, _m = best_match(name, evs)
                    if ev:
                        atrasados += 1
        señales['atraso'] = 'OK' if atrasados == 0 else ('WARN' if atrasados < 5 else 'STALE')
        detalle['atraso'] = (f'{atrasados} partidos que el respaldo da por terminados '
                             f'siguen sin cerrar en la BD')
    except Exception as e:
        señales['atraso'] = 'DESCONOCIDO'
        detalle['atraso'] = f'no se pudo comprobar ({type(e).__name__}: {e})'
cur.close(); con.close()

# ── Veredicto ────────────────────────────────────────────────────────────────
valores = [v for v in señales.values() if v != 'DESCONOCIDO']
if 'STALE' in valores:
    veredicto = 'STALE'
elif 'WARN' in valores:
    veredicto = 'WARN'
elif valores:
    veredicto = 'OK'
else:
    veredicto = 'DESCONOCIDO'

estado = {'comprobado_utc': ahora.isoformat(), 'veredicto': veredicto,
          'señales': señales, 'detalle': detalle,
          'umbrales': {'latido_max_min': args.latido_max,
                       'colgado_horas': args.colgado_horas}}
os.makedirs(os.path.join(ROOT, 'tmp'), exist_ok=True)
with open(os.path.join(ROOT, 'tmp', 'staleness_status.json'), 'w', encoding='utf-8') as fh:
    json.dump(estado, fh, ensure_ascii=False, indent=2)

print(f'\n{"="*74}\n  ESTADO DEL PRIMARIO (FlashScore) — {ahora:%Y-%m-%d %H:%M:%S} UTC\n{"="*74}')
for k, v in señales.items():
    icono = {'OK': '✓', 'WARN': '!', 'STALE': '✗', 'DESCONOCIDO': '?'}[v]
    print(f'  {icono} {k.upper():10s} {v:12s} {detalle.get(k, "")}')
for k, v in detalle.items():
    if k not in señales:
        print(f'    · {v}')
print(f'{"-"*74}\n  VEREDICTO: {veredicto}')
print('  (este detector NO actúa: solo informa. La conmutación es SC11.)')
print(f'  guardado en tmp/staleness_status.json')
