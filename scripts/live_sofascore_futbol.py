"""Convalidación SofaScore ↔ FlashScore — FÚTBOL, sección LIVE, SOLO LECTURA.

Qué hace:
  1. Abre un driver PROPIO e independiente (no toca el del panel ni el del live).
  2. Pide a SofaScore los partidos de fútbol EN VIVO.
  3. Los cruza contra lo que la BD ya tiene (escrito por FlashScore) y compara
     **liga, nombres de equipo, fecha, HORA, marcador y estado**.

NO escribe absolutamente nada: ni en la BD, ni en los checkpoints. Sirve para saber
si un respaldo con SofaScore encontraría los partidos correctos ANTES de dejarle
tocar nada.

  sports_env/bin/python scripts/live_sofascore_futbol.py [--no-headless] [--deporte Football]
"""
import sys, os, argparse, time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from common_functions import launch_navigator
from sofascore_provider import live_events, ensure_context, norm_name

ap = argparse.ArgumentParser()
ap.add_argument('--no-headless', dest='headless', action='store_false')
ap.add_argument('--deporte', default='Football', help='Football | Basketball | Baseball ...')
ap.add_argument('--margen-horas', type=float, default=3.0,
                help='diferencia de hora tolerada antes de marcarla como discrepancia')
ap.set_defaults(headless=True)
args = ap.parse_args()

DEPORTE = args.deporte
PERFIL = os.path.join(ROOT, 'tmp', 'profiles', 'sofascore_test')

# ── 1. Partidos que la BD ya tiene (ventana de ±1 día) ───────────────────────
hoy = datetime.now(timezone.utc).date()
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
cur = con.cursor()
cur.execute("""
    SELECT m.match_id, m.name, m.match_date, m.start_time, m.status,
           c.country_name, l.league_name,
           -- OJO: ordenar por `home` DESC, NO por match_detail_id (que es un UUID y
           -- alfabéticamente invierte el marcador). match_detail.home marca al local.
           (SELECT string_agg(se.points::text, '-' ORDER BY md.home DESC)
              FROM match_detail md
              JOIN score_entity se ON se.match_detail_id = md.match_detail_id
             WHERE md.match_id = m.match_id)
      FROM match m
      JOIN league  l ON m.league_id  = l.league_id
      JOIN sport   s ON l.sport_id   = s.sport_id
      JOIN country c ON l.country_id = c.country_id
     WHERE s.name = %s AND m.match_date BETWEEN %s AND %s
""", (DEPORTE, hoy - timedelta(days=1), hoy + timedelta(days=1)))
filas = cur.fetchall()
cur.close(); con.close()

por_equipos = {}
ligas_bd = set()
for mid, name, fecha, hora, status, pais, liga, score in filas:
    partes = str(name).split('~')
    if len(partes) == 2:
        clave = (norm_name(partes[0]), norm_name(partes[1]))
        por_equipos[clave] = dict(match_id=mid, name=name, fecha=fecha, hora=hora,
                                  status=status, pais=pais, liga=liga, score=score)
    ligas_bd.add((pais, liga))
# Índice por (fecha, hora): la hora de inicio coincide al MINUTO entre ambas fuentes,
# así que es un discriminante mucho más fiable que el nombre del equipo, que cada sitio
# escribe a su manera ('Henan FC' vs 'Henan Songshan Longmen').
por_horario = defaultdict(list)
for mid, name, fecha, hora, status, pais, liga, score in filas:
    if hora:
        por_horario[(str(fecha), hora.hour, hora.minute)].append(
            dict(match_id=mid, name=name, fecha=fecha, hora=hora, status=status,
                 pais=pais, liga=liga, score=score))

print(f'BD: {len(filas)} partidos de {DEPORTE} entre {hoy - timedelta(days=1)} y {hoy + timedelta(days=1)}'
      f' | {len(ligas_bd)} ligas')


def emparejar(ev):
    """Localiza el partido en la BD. Devuelve (partido, cómo se encontró).

    1) por nombre normalizado de los dos equipos (exacto);
    2) si falla, por FECHA+HORA exactas: si a esa hora solo hay un partido y al menos
       un token del nombre coincide, es ese. Resuelve las variantes de nombre
       ('Zhejiang' ↔ 'Zhejiang Professional') sin inventar nada."""
    hit = por_equipos.get((norm_name(ev['home']), norm_name(ev['away'])))
    if hit:
        return hit, 'nombre'
    if not ev['start_time']:
        return None, None
    h, m = int(ev['start_time'][:2]), int(ev['start_time'][3:])
    candidatos = por_horario.get((ev['match_date'], h, m), [])
    toks_ss = set(norm_name(ev['home']).split()) | set(norm_name(ev['away']).split())
    validos = []
    for c in candidatos:
        partes = str(c['name']).split('~')
        if len(partes) != 2:
            continue
        toks_bd = set(norm_name(partes[0]).split()) | set(norm_name(partes[1]).split())
        if toks_ss & toks_bd:                     # comparten al menos una palabra
            validos.append(c)
    if len(validos) == 1:                          # sin ambigüedad
        return validos[0], 'fecha+hora'
    return None, None

# ── 2. SofaScore en vivo, con driver propio ──────────────────────────────────
print(f'\nAbriendo driver PROPIO de pruebas (headless={args.headless})...')
d = launch_navigator('https://www.sofascore.com', headless=args.headless,
                     lightweight=True, profile_dir=PERFIL)
try:
    ensure_context(d)
    eventos = live_events(d, DEPORTE)
    print(f'SofaScore: {len(eventos)} partidos de {DEPORTE} EN VIVO ahora')

    encontrados, no_encontrados = [], []
    ligas_ss = defaultdict(int)
    for ev in eventos:
        ligas_ss[(ev['country_raw'], ev['league_raw'])] += 1
        hit, via = emparejar(ev)
        (encontrados if hit else no_encontrados).append((ev, hit, via))

    # ── 3. Informe: partidos que SÍ cruzan ───────────────────────────────────
    print('\n' + '=' * 100)
    print(f'A) PARTIDOS QUE CRUZAN CON LA BD: {len(encontrados)} de {len(eventos)}')
    print('=' * 100)
    difs_hora, difs_score, difs_status = 0, 0, 0
    for ev, bd, via in encontrados:
        print(f"\n  {ev['home']} vs {ev['away']}   [emparejado por {via}]")
        print(f"     liga   SS={ev['country_raw']}/{ev['league_raw']:<28} BD={bd['pais']}/{bd['liga']}")
        print(f"     nombre SS={ev['match_name']:<45} BD={bd['name']}")
        igual_nombre = ev['match_name'] == bd['name']
        print(f"     ¿nombre idéntico? {'sí' if igual_nombre else 'NO (haría falta alias)'}")
        # HORA: ambas en UTC. La BD guarda time; SofaScore da el timestamp de inicio.
        h_bd = bd['hora'].strftime('%H:%M') if bd['hora'] else '--:--'
        dif = ''
        if bd['hora'] and ev['start_time']:
            m_bd = bd['hora'].hour * 60 + bd['hora'].minute
            m_ss = int(ev['start_time'][:2]) * 60 + int(ev['start_time'][3:])
            delta = abs(m_bd - m_ss)
            delta = min(delta, 1440 - delta)          # la medianoche no es una diferencia de 23 h
            dif = f'  → diferencia {delta} min' + ('  ⚠️' if delta > args.margen_horas * 60 else '  ✓')
            if delta > args.margen_horas * 60:
                difs_hora += 1
        print(f"     fecha  SS={ev['match_date']}   BD={bd['fecha']}")
        print(f"     hora   SS={ev['start_time']} UTC   BD={h_bd} UTC{dif}")
        print(f"     marcador SS={ev['score_home']}-{ev['score_away']}   BD={bd['score']}")
        print(f"     estado   SS={ev['status']} ({ev['status_raw']})   BD={bd['status']}")
        ss_score = f"{ev['score_home']}-{ev['score_away']}"
        if bd['score'] and ss_score != bd['score']:
            difs_score += 1
            print(f"     ⚠️  MARCADOR DISTINTO")
        if ev['status'] != bd['status']:
            difs_status += 1

    # ── 4. Informe: los que no cruzan ────────────────────────────────────────
    print('\n' + '=' * 100)
    print(f'B) EN VIVO EN SOFASCORE PERO NO LOCALIZADOS EN LA BD: {len(no_encontrados)}')
    print('=' * 100)
    en_liga_conocida = []
    for ev, _, _ in no_encontrados:
        pais_bd = ev['country_raw'].upper()
        cerca = [(p, l) for (p, l) in ligas_bd if norm_name(p) == norm_name(pais_bd)]
        if cerca:
            en_liga_conocida.append((ev, cerca))
    por_via = defaultdict(int)
    for _, _, via in encontrados:
        por_via[via] += 1
    print(f'  De ellos, {len(en_liga_conocida)} son de países que SÍ están en la BD')
    print('  (candidatos a alias de equipo/liga; el resto son ligas que no seguimos):')
    for ev, cerca in en_liga_conocida[:15]:
        print(f"     {ev['country_raw']:<16} {ev['league_raw']:<26} {ev['home']} ~ {ev['away']}")
        print(f"        ligas de ese país en la BD: {[l for _, l in cerca][:4]}")

    # ── 5. Mapeo de ligas ────────────────────────────────────────────────────
    print('\n' + '=' * 100)
    print('C) MAPEO DE LIGAS (las que SofaScore tiene en vivo ahora)')
    print('=' * 100)
    idx_bd = {(norm_name(p), norm_name(l)): (p, l) for p, l in ligas_bd}
    solo_liga_bd = {norm_name(l): (p, l) for p, l in ligas_bd}
    ok = falta = 0
    for (pais, liga), n in sorted(ligas_ss.items(), key=lambda kv: -kv[1]):
        nl = norm_name(liga)
        m = idx_bd.get((norm_name(pais), nl)) or solo_liga_bd.get(nl)
        if not m:   # 'Chinese Super League' ↔ 'Super League': uno contiene al otro
            for k, v in solo_liga_bd.items():
                if k and (k in nl or nl in k) and norm_name(v[0]) == norm_name(pais):
                    m = v; break
        if m:
            ok += 1
            marca = '✓ ' if (pais.upper() == m[0] and liga == m[1]) else '≈ '
            print(f'  {marca}{pais}/{liga}  →  BD: {m[0]}/{m[1]}   ({n} en vivo)')
        else:
            falta += 1
    print(f'\n  ligas de SofaScore que existen en la BD: {ok} | sin correspondencia: {falta}')
    print(f'\n  RESUMEN: {len(encontrados)}/{len(eventos)} cruzados | '
          f'{difs_score} con marcador distinto | {difs_status} con estado distinto | '
          f'{difs_hora} con hora fuera de margen')
    print(f'  emparejados por nombre: {por_via.get("nombre", 0)} | '
          f'rescatados por fecha+hora: {por_via.get("fecha+hora", 0)}')
    print('  (✓ = nombre idéntico, ≈ = cruza pero con nombre distinto → necesita alias)')
finally:
    try:
        d.quit()
        print('\n[cleanup] driver de pruebas cerrado (el de producción no se tocó)')
    except Exception:
        pass
