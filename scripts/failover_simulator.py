"""SC11 — SIMULADOR de conmutación al respaldo. NO ESCRIBE EN LA BASE DE DATOS.

Ensaya el comportamiento completo: vigila al primario (FlashScore), decide cuándo
cedería el mando a SofaScore, calcula **qué escribiría** mientras lo tenga, y cuándo
lo devolvería. Todo se registra; nada se aplica.

Para ver el flujo entero sin esperar a una caída real:

    sports_env/bin/python scripts/failover_simulator.py --simular-caida --lecturas 6

En vigilancia normal (el primario está bien y no debería pasar nada):

    sports_env/bin/python scripts/failover_simulator.py --lecturas 3 --pausa 60
"""
import sys, os, json, time, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from failover import evaluar_primario, MaquinaFailover

ap = argparse.ArgumentParser()
ap.add_argument('--lecturas', type=int, default=6, help='cuántas rondas simular')
ap.add_argument('--pausa', type=float, default=0, help='segundos entre rondas')
ap.add_argument('--simular-caida', action='store_true',
                help='finge que el primario no responde, para ensayar la conmutación')
ap.add_argument('--recuperar-en', type=int, default=0,
                help='con --simular-caida: ronda a partir de la cual el primario "vuelve"')
ap.add_argument('--reset', action='store_true', help='empezar con el estado limpio')
args = ap.parse_args()

if args.reset and os.path.exists(os.path.join(ROOT, 'tmp', 'failover_state.json')):
    os.remove(os.path.join(ROOT, 'tmp', 'failover_state.json'))

maquina = MaquinaFailover()
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()

# ── qué escribiría el respaldo si tuviera el mando ───────────────────────────
def plan_de_escritura():
    """Partidos que el respaldo cerraría AHORA (SofaScore los da por terminados y la
    BD no). Es exactamente lo que se escribiría; aquí solo se enumera."""
    try:
        from driver_session import get_driver
        from sofascore_provider import tournament_events, best_match
        d = get_driver(os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
        mapa = json.load(open(os.path.join(ROOT, 'check_points', 'sofascore_map.json'),
                              encoding='utf-8'))
    except Exception as e:
        return None, f'respaldo no disponible ({type(e).__name__})'
    hoy = datetime.now(timezone.utc).date().isoformat()
    plan = []
    for dep, ligas in mapa.items():
        for clave, info in ligas.items():
            if not info.get('unique_id'):
                continue
            pais, _, liga = clave.partition('_')
            cur.execute("""
                SELECT m.name, m.status FROM match m
                  JOIN league  l ON m.league_id  = l.league_id
                  JOIN sport   s ON l.sport_id   = s.sport_id
                  JOIN country c ON l.country_id = c.country_id
                 WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s
                   AND m.match_date=%s AND m.status <> 'COMPLETED'
            """, (dep, pais, liga, hoy))
            pendientes = cur.fetchall()
            if not pendientes:
                continue
            evs = tournament_events(d, info['unique_id'], hoy, dep)
            for name, status in pendientes:
                ev, _s, _m = best_match(name, [e for e in evs if e['score_home'] is not None])
                if ev:
                    plan.append({'deporte': dep, 'liga': clave, 'partido': name,
                                 'estado_bd': status,
                                 'marcador_respaldo': f"{ev['score_home']}-{ev['score_away']}",
                                 'estado_respaldo': ev['status']})
    return plan, None

print(f'\n{"="*90}')
print('  SIMULACIÓN DE CONMUTACIÓN AL RESPALDO — no se escribe nada en la base de datos')
print(f'  dueño al empezar: {maquina.dueño}'
      f"{'   ·  MODO: caída simulada' if args.simular_caida else ''}")
print(f'{"="*90}')

for i in range(1, args.lecturas + 1):
    forzar = args.simular_caida and (args.recuperar_en == 0 or i < args.recuperar_en)
    veredicto, señales, detalle = evaluar_primario(cur, forzar_caida=forzar)
    dueño_antes = maquina.dueño
    dueño, evento = maquina.actualizar(veredicto, señales)
    maquina.guardar()

    marca = {'OK': '✓', 'WARN': '!', 'STALE': '✗', 'DESCONOCIDO': '?'}[veredicto]
    vit = maquina.estado['ultima_lectura'].get('vitalidad', '?')
    print(f'\n  ronda {i}/{args.lecturas}  {marca} veredicto={veredicto:6s} '
          f'vitalidad={vit:6s} malas={maquina.estado["malas"]} '
          f'buenas={maquina.estado["buenas"]}  dueño={dueño}')
    for k, v in detalle.items():
        print(f'      · {v}')
    if evento:
        print(f'      ►►► {evento}')
        if dueño == 'respaldo':
            plan, err = plan_de_escritura()
            if err:
                print(f'      (no se pudo calcular el plan: {err})')
            elif not plan:
                print('      el respaldo no tendría nada que escribir ahora mismo')
            else:
                print(f'      ESCRIBIRÍA {len(plan)} partidos (SIMULADO, no se aplica):')
                for p in plan[:12]:
                    print(f'         {p["liga"]:26s} {p["partido"][:38]:40s} '
                          f'{p["estado_bd"]:10s} → {p["marcador_respaldo"]:7s} {p["estado_respaldo"]}')
    if args.pausa and i < args.lecturas:
        time.sleep(args.pausa)

cur.close(); con.close()
print(f'\n{"="*90}')
print(f'  ESTADO FINAL: manda el {maquina.dueño.upper()}')
for h in maquina.estado.get('historial', [])[-6:]:
    print(f'    {h["cuando"][11:19]}  {h["evento"]}')
print(f'  estado en tmp/failover_state.json   ·   NADA fue escrito en la base de datos')
print(f'{"="*90}')
