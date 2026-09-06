"""
_debug_seasons_check.py — ¿las ligas tienen season asociada en DB? (READ-ONLY)
=============================================================================
Diagnóstico para entender por qué "casi todas las ligas salen sin season_id".

Por deporte cuenta:
  - total ligas
  - ligas CON >=1 fila en `season`
  - ligas SIN ninguna season  (estas son las que aparecen "sin season_id")

Luego lista las ligas SIN season y, para las que SÍ tienen, muestra los
season_name guardados (para detectar mismatch de nombre: ej. DOM dice
'2025-2026' pero en DB está '2025').

Solo SELECT. No driver. No escribe nada.

Uso:
  env_sports/bin/python scripts/_debug_seasons_check.py            # todos
  env_sports/bin/python scripts/_debug_seasons_check.py FOOTBALL   # un deporte (sport.name)
"""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from data_base import getdb

SPORT = sys.argv[1] if len(sys.argv) > 1 else None


def main():
    con = getdb()
    cur = con.cursor()

    # una fila por liga, con conteo de seasons y los season_name presentes
    cur.execute(
        """
        SELECT COALESCE(s.name, '(sin deporte)')        AS sport,
               COALESCE(co.country_name, '(sin pais)')  AS country,
               COALESCE(l.league_name, '(sin nombre)')  AS league,
               l.league_id,
               COUNT(se.season_id)                      AS n_seasons,
               STRING_AGG(DISTINCT se.season_name, ', ') AS season_names
        FROM league l
        LEFT JOIN sport   s  ON s.sport_id   = l.sport_id
        LEFT JOIN country co ON co.country_id = l.country_id
        LEFT JOIN season  se ON se.league_id  = l.league_id
        GROUP BY s.name, co.country_name, l.league_name, l.league_id
        ORDER BY sport, n_seasons, country, league
        """)
    rows = cur.fetchall()

    if SPORT:
        rows = [r for r in rows if r[0] == SPORT]

    # resumen por deporte
    por_deporte = {}
    sin_season = []
    for sport, country, league, lid, n, names in rows:
        d = por_deporte.setdefault(sport, {'total': 0, 'con': 0, 'sin': 0})
        d['total'] += 1
        if n == 0:
            d['sin'] += 1
            sin_season.append((sport, country, league, lid))
        else:
            d['con'] += 1

    print('\n=== RESUMEN season POR DEPORTE ===')
    print(f'{"DEPORTE":<14} | {"TOTAL":>6} | {"CON season":>10} | {"SIN season":>10}')
    print('-' * 50)
    tot = con_t = sin_t = 0
    for sport in sorted(por_deporte):
        d = por_deporte[sport]
        tot += d['total']; con_t += d['con']; sin_t += d['sin']
        print(f'{sport:<14} | {d["total"]:>6} | {d["con"]:>10} | {d["sin"]:>10}')
    print('-' * 50)
    print(f'{"TOTAL":<14} | {tot:>6} | {con_t:>10} | {sin_t:>10}')

    # muestra de ligas CON season (para ver formato de season_name)
    print('\n=== MUESTRA: ligas CON season (season_name guardado) ===')
    shown = 0
    for sport, country, league, lid, n, names in rows:
        if n > 0:
            print(f'  [{sport}] {country} / {league}  -> seasons: {names}')
            shown += 1
            if shown >= 15:
                print('  ... (muestra truncada a 15)')
                break
    if shown == 0:
        print('  (ninguna liga tiene season)')

    # ligas SIN season
    print(f'\n=== LIGAS SIN season ({len(sin_season)}) ===')
    for sport, country, league, lid in sin_season[:60]:
        print(f'  [{sport}] {country} / {league}  (league_id={lid})')
    if len(sin_season) > 60:
        print(f'  ... y {len(sin_season) - 60} más')

    print('\n(read-only: no se modificó la base de datos)')


if __name__ == '__main__':
    main()
