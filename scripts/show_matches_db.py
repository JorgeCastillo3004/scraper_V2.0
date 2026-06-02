"""
show_matches_db.py — Listado READ-ONLY de partidos en la base de datos
======================================================================
Muestra los partidos existentes en `match`, agrupados por DEPORTE -> LIGA.

Filtro por `match.match_date`:
  - sin argumentos        -> día en curso (hoy)
  - 1 fecha (YYYY-MM-DD)   -> ese día puntual
  - 2 fechas (YYYY-MM-DD)  -> rango [desde .. hasta] inclusive

Solo ejecuta SELECT (no escribe ni borra nada). Reusa data_base.getdb().

Uso:
  env_sports/bin/python scripts/show_matches_db.py
  env_sports/bin/python scripts/show_matches_db.py 2026-05-30
  env_sports/bin/python scripts/show_matches_db.py 2026-05-25 2026-05-30
"""
import os, sys
from datetime import datetime, date

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from data_base import getdb


def parse_args(argv):
    """Devuelve (desde, hasta) como date. Sin args -> hoy..hoy."""
    if not argv:
        today = datetime.now().date()
        return today, today
    try:
        fechas = [datetime.strptime(a, '%Y-%m-%d').date() for a in argv[:2]]
    except ValueError:
        print('ERROR: las fechas deben tener formato YYYY-MM-DD')
        sys.exit(1)
    if len(fechas) == 1:
        return fechas[0], fechas[0]
    desde, hasta = sorted(fechas)   # tolera orden invertido
    return desde, hasta


def main():
    desde, hasta = parse_args(sys.argv[1:])
    con = getdb()
    cur = con.cursor()

    # SELECT read-only: match ⋈ league ⋈ sport ⋈ country.
    # Agrupación/orden por deporte -> país/liga -> hora -> nombre.
    cur.execute(
        """
        SELECT COALESCE(sport.name, '(sin deporte)')      AS sport_name,
               COALESCE(country.country_name, '(sin pais)') AS country_name,
               COALESCE(league.league_name, '(sin liga)')   AS league_name,
               match.match_date,
               match.start_time,
               match.name,
               COALESCE(match.status, '')                   AS status
        FROM match
        LEFT JOIN league  ON league.league_id  = match.league_id
        LEFT JOIN sport   ON sport.sport_id     = league.sport_id
        LEFT JOIN country ON country.country_id = league.country_id
        WHERE match.match_date BETWEEN %s AND %s
        ORDER BY sport_name, country_name, league_name,
                 match.match_date, match.start_time, match.name
        """,
        (desde, hasta))
    rows = cur.fetchall()

    rango = f'{desde}' if desde == hasta else f'{desde} .. {hasta}'
    print(f'\n=== PARTIDOS EN DB | match_date: {rango} ===')
    print(f'total partidos: {len(rows)}\n')

    if not rows:
        print('(no hay partidos en ese rango)')
        return

    cur_sport = cur_league = None
    n_sport = n_league = 0
    for sport_name, country_name, league_name, m_date, m_time, m_name, status in rows:
        if sport_name != cur_sport:
            cur_sport = sport_name
            cur_league = None
            n_sport += 1
            print(f'\n############  {sport_name}  ############')

        liga_key = (country_name, league_name)
        if liga_key != cur_league:
            cur_league = liga_key
            n_league += 1
            print(f'\n  -- {country_name} / {league_name} --')

        hora = m_time.strftime('%H:%M') if m_time else '  -  '
        fecha = f'{m_date} ' if desde != hasta else ''
        print(f'     {fecha}{hora:>5}  {m_name:<45}  [{status}]')

    print(f'\n{"="*55}')
    print(f'RESUMEN: {len(rows)} partidos | {n_league} ligas | {n_sport} deportes')
    print('(read-only: no se modificó la base de datos)')


if __name__ == '__main__':
    main()
