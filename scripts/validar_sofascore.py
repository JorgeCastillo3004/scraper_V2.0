"""Validación EXTENSIVA SofaScore ↔ BD: hoy y próximas fechas. SOLO LECTURA.

Para cada liga mapeada (check_points/sofascore_map.json) y cada fecha, compara TODOS
los partidos que la BD tiene contra los que SofaScore publica, y verifica que el
emparejamiento es correcto y sin ambigüedad: nombres, fecha, HORA y estado.

Usa el DRIVER YA ABIERTO (tmp/sofascore_driver.json) y no lo cierra. No escribe nada.

  sports_env/bin/python scripts/validar_sofascore.py --deporte Football --dias 4
  sports_env/bin/python scripts/validar_sofascore.py --deporte Football --dias 4 --detalle
"""
import sys, os, json, time, argparse
from datetime import date, timedelta
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from driver_session import get_driver
from sofascore_provider import tournament_events, norm_name, best_match

ap = argparse.ArgumentParser()
ap.add_argument('--deporte', default='Football')
ap.add_argument('--desde', default=None,
                help='fecha inicial YYYY-MM-DD (por defecto hoy). Sirve para deportes\n                      fuera de temporada: se valida contra sus últimas jornadas.')
ap.add_argument('--dias', type=int, default=4)
ap.add_argument('--detalle', action='store_true', help='listar partido por partido')
ap.add_argument('--session-file', default=os.path.join(ROOT, 'tmp', 'sofascore_driver.json'))
args = ap.parse_args()

mapa = json.load(open(os.path.join(ROOT, 'check_points', 'sofascore_map.json'), encoding='utf-8'))
ligas_map = {k: v for k, v in mapa.get(args.deporte, {}).items() if v.get('unique_id')}
print(f'Ligas mapeadas para {args.deporte}: {len(ligas_map)}')

hoy = date.fromisoformat(args.desde) if args.desde else date.today()
fechas = [(hoy + timedelta(days=i)).isoformat() for i in range(args.dias + 1)]

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()
d = get_driver(args.session_file)

TOT = defaultdict(int)
problemas = []
print('\n%-30s %-12s %5s %5s %7s %7s' % ('LIGA', 'FECHA', 'BD', 'SS', 'CRUZAN', 'HORA OK'))
print('-' * 78)

for clave, info in ligas_map.items():
    pais, _, liga = clave.partition('_')
    for f in fechas:
        cur.execute("""
            SELECT m.name, m.match_date, m.start_time, m.status
              FROM match m
              JOIN league  l ON m.league_id  = l.league_id
              JOIN sport   s ON l.sport_id   = s.sport_id
              JOIN country c ON l.country_id = c.country_id
             WHERE s.name=%s AND c.country_name=%s AND l.league_name=%s AND m.match_date=%s
        """, (args.deporte, pais, liga, f))
        en_bd = cur.fetchall()
        if not en_bd:
            continue
        # Ventana de ±1 día: SofaScore ubica el partido por su hora REAL en UTC, así que
        # un partido nocturno de América cae en el día siguiente. La BD, en cambio, guarda
        # la fecha local con hora placeholder.
        # PRIMERO la fecha exacta; el ±1 día solo si ahí no aparece nada.
        # En béisbol el MISMO enfrentamiento se repite días seguidos (KBO juega series
        # de 3: Kiwoom~NC Dinos el 4, el 5 y el 6 de septiembre, con marcadores
        # distintos), así que ampliar la ventana a ciegas puede asignar el marcador del
        # juego equivocado. La fecha manda; el margen es solo para el desfase horario.
        # OJO: pedir una fecha NO devuelve solo esa fecha. NPB pedido el día 8 devuelve
        # 12 eventos = los 6 del día 8 más los 6 del día 9 (misma serie, jornadas
        # seguidas). Sin filtrar por la fecha REAL del evento, cada partido tiene un
        # gemelo idéntico y todo se descarta por ambiguo.
        todos, vistos_id = [], set()
        for delta in (0, 1, -1):
            fx = (date.fromisoformat(f) + timedelta(days=delta)).isoformat()
            for e in tournament_events(d, info['unique_id'], fx, args.deporte):
                if e['event_id'] not in vistos_id:
                    vistos_id.add(e['event_id']); todos.append(e)
            time.sleep(0.35)
        evs = [e for e in todos if e['match_date'] == f]      # los de ESE día
        adyacentes = [e for e in todos if e['match_date'] != f]  # reserva por desfase horario

        # índices de SofaScore: por nombres y por hora
        por_nombre = {(norm_name(e['home']), norm_name(e['away'])): e for e in evs}
        por_hora = defaultdict(list)
        for e in evs:
            if e['start_time']:
                por_hora[e['start_time']].append(e)

        cruzan = hora_ok = 0
        ya_usados = set()          # eventos de SofaScore ya asignados en esta liga/fecha
        # ¿la hora de la BD es real o un placeholder? Si TODOS los partidos de la
        # jornada comparten start_time, es placeholder y compararla no significa nada.
        horas_bd = {r[2] for r in en_bd if r[2]}
        hora_es_real = len(horas_bd) > 1 or len(en_bd) <= 2
        for name, fecha_bd, hora_bd, status_bd in en_bd:
            partes = str(name).split('~')
            if len(partes) != 2:
                continue
            clave_n = (norm_name(partes[0]), norm_name(partes[1]))
            ev = por_nombre.get(clave_n)
            via, score = 'nombre', 1.0
            if not ev and hora_bd:
                # la hora solo sirve si es real: en los SCHEDULED la BD guarda un
                # placeholder (toda la jornada a la misma hora), así que solo se usa
                # cuando esa hora distingue de verdad
                hhmm = f'{hora_bd.hour:02d}:{hora_bd.minute:02d}'
                cands = por_hora.get(hhmm, [])
                toks = set(clave_n[0].split()) | set(clave_n[1].split())
                validos = [c for c in cands
                           if toks & (set(norm_name(c['home']).split()) | set(norm_name(c['away']).split()))]
                if len(validos) == 1:
                    ev, via = validos[0], 'fecha+hora'
            if not ev:
                # abreviaturas de FlashScore ('Atl. Nacional' ↔ 'Atlético Nacional').
                # Se ofrecen solo los eventos AÚN NO asignados en esta liga/fecha, para
                # que dos partidos no acaben apuntando al mismo evento.
                libres = [e for e in evs if id(e) not in ya_usados]
                ev, score, motivo = best_match(name, libres)
                via = 'similitud' if ev else motivo
                if not ev:
                    # último recurso: días contiguos (un partido nocturno de América
                    # cae en el día siguiente UTC). Nunca antes de agotar la fecha real.
                    libres2 = [e for e in adyacentes if id(e) not in ya_usados]
                    ev, score, motivo = best_match(name, libres2)
                    via = 'similitud±1d' if ev else motivo
            if ev:
                ya_usados.add(id(ev))
            if ev:
                cruzan += 1
                TOT['cruzan'] += 1
                TOT[f'via_{via}'] += 1
                if not hora_es_real:
                    TOT['hora_placeholder'] += 1
                elif hora_bd and ev['start_time'] == f'{hora_bd.hour:02d}:{hora_bd.minute:02d}':
                    hora_ok += 1; TOT['hora_ok'] += 1
                else:
                    problemas.append(('HORA', f'{pais}/{liga}', f, name,
                                      f"BD={hora_bd} SS={ev['start_time']}"))
                if args.detalle:
                    extra = f' score={score:.2f}' if via == 'similitud' else ''
                    print(f"    ✓ [{via:10s}] {name:38s} → {ev['match_name']}{extra}")
            else:
                TOT['sin_cruce'] += 1
                problemas.append(('NO ENCONTRADO', f'{pais}/{liga}', f, name,
                                  f'{via} | SofaScore tenía {len(evs)} partidos'))
                if args.detalle:
                    print(f'    ✗ NO ENCONTRADO: {name} (hora BD={hora_bd})')
        TOT['bd'] += len(en_bd); TOT['ss'] += len(evs)
        print('%-30s %-12s %5d %5d %7d %7d' % (f'{pais}/{liga}'[:29], f, len(en_bd), len(evs), cruzan, hora_ok))

cur.close(); con.close()
print('-' * 78)
print(f"TOTAL  partidos en la BD: {TOT['bd']} | localizados en SofaScore: {TOT['cruzan']} "
      f"({100.0*TOT['cruzan']/max(TOT['bd'],1):.0f}%) | sin cruce: {TOT['sin_cruce']}")
print(f"       por nombre: {TOT['via_nombre']} | por fecha+hora: {TOT['via_fecha+hora']} | por similitud: {TOT['via_similitud']}")
print(f"       hora coincidente al minuto: {TOT['hora_ok']} (de los {TOT['hora_ok']+len(([p for p in problemas if p[0]=='HORA']))} con hora real en la BD)")
print(f"       con hora placeholder en la BD (no comparable): {TOT['hora_placeholder']}")
if problemas:
    print(f'\nINCIDENCIAS ({len(problemas)}):')
    for tipo, liga, f, name, det in problemas[:25]:
        print(f'   [{tipo:14s}] {liga:26s} {f}  {name}  ({det})')
print('\n[fin] driver vivo intacto')
