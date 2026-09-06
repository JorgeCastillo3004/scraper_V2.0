"""Inventario READ-ONLY de partidos pendientes de completar.

Reusa las MISMAS consultas que usa el completado real (fix_live_matches):
  - get_pending_live_matches  : fecha < hoy Y (status LIVE  ó  algún score = -1)
  - get_stats_backfill_matches: COMPLETED con score real pero sin estadísticas

No escribe absolutamente nada. Agrupa por deporte/liga y por antigüedad para
decidir el orden de ataque y estimar el trabajo.

  sports_env/bin/python scripts/_debug_inventario_pendientes.py
"""
import sys, os
from collections import Counter, defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src'), os.path.join(ROOT, 'scripts')]

from scripts.fix_live_matches import get_pending_live_matches, get_stats_backfill_matches

hoy = date.today()

def bucket(d):
    dd = (hoy - d).days
    return ('1 esta semana' if dd <= 7 else '2 este mes' if dd <= 31 else
            '3 hasta 6 meses' if dd <= 186 else '4 más de 6 meses')

print('\n' + '='*78)
print('A) PARTIDOS A CERRAR  (fecha < hoy  Y  [status LIVE  ó  algún score = -1])')
print('='*78)
pend = get_pending_live_matches(verbose=False)
print(f'TOTAL: {len(pend)} partidos')

print('\n  por status:')
for k, v in Counter(p['status'] for p in pend).most_common():
    print(f'    {k:12s} {v:5d}')

print('\n  por antigüedad:')
for k, v in sorted(Counter(bucket(p['match_date']) for p in pend).items()):
    print(f'    {k[2:]:18s} {v:5d}')

print('\n  por deporte:')
for k, v in Counter(p['sport_name'] for p in pend).most_common():
    print(f'    {k:15s} {v:5d}')

print('\n  por liga (las que hay que correr, con el --league del script):')
porliga = defaultdict(list)
for p in pend:
    porliga[(p['sport_name'], p['country_name'], p['league_name'])].append(p)
for (sp, co, le), ms in sorted(porliga.items(), key=lambda kv: -len(kv[1])):
    fechas = sorted(m['match_date'] for m in ms)
    sts = '+'.join(sorted({m['status'] for m in ms}))
    print(f'    {len(ms):4d}  {sp:12s} {co} / {le}   [{sts}]  {fechas[0]} → {fechas[-1]}')

print('\n' + '='*78)
print('B) BACKFILL DE ESTADÍSTICAS  (COMPLETED, score real, sin statistic)')
print('='*78)
bf = get_stats_backfill_matches(verbose=False)
print(f'TOTAL: {len(bf)} partidos')
for k, v in Counter(b['sport_name'] for b in bf).most_common(8):
    print(f'    {k:15s} {v:5d}')
print('\n  por liga (top 12):')
pl2 = Counter((b['sport_name'], b['country_name'], b['league_name']) for b in bf)
for (sp, co, le), n in pl2.most_common(12):
    print(f'    {n:4d}  {sp:12s} {co} / {le}')

print('\n' + '='*78)
print(f'RESUMEN: {len(pend)} a cerrar  +  {len(bf)} sin estadísticas  = {len(pend)+len(bf)} pendientes')
print(f'Ligas distintas a recorrer: {len(porliga)} (cerrar) / {len(pl2)} (stats)')
print('='*78)
