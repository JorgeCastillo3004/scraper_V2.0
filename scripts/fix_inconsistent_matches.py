"""
fix_inconsistent_matches.py
============================
Detecta y completa partidos cuyo match_detail está incompleto
(no aparecen los 2 equipos / falta home o visitor).

Estrategia:
  1. Detectar matches con menos de 2 filas en match_detail
     o que no tienen exactamente 1 home + 1 visitor.
  2. Excluir deportes individuales (Formula 1, Boxing, Tennis, Golf)
     porque su modelo no es team-vs-team con home/visitor.
  3. Parsear `match.name` por el separador '~' → (home_name, visitor_name).
  4. Buscar team_id de cada lado usando team_name + league_id + season_id.
  5. Insertar las filas faltantes en match_detail.

Uso:
    python scripts/fix_inconsistent_matches.py                # dry-run (default)
    python scripts/fix_inconsistent_matches.py --apply        # escribe en DB
    python scripts/fix_inconsistent_matches.py --sport Football --apply
"""

import sys, os, argparse
from collections import Counter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from data_base import getdb
from common_functions import generate_uuid

# Deportes individuales — su match_detail no sigue el patrón home/visitor.
EXCLUDED_SPORTS = ('MOTOR SPORT', 'Boxing', 'Tennis', 'GOLF')
NAME_SEP = '~'


def find_inconsistent_matches(con, sport=None, league=None):
    """
    Retorna lista de dicts con los partidos incompletos.

    Cada elemento:
      {
        match_id, name, match_date, sport_name, league_name, league_id,
        season_id, n_details, has_home, has_visitor,
        existing_team_ids: set
      }
    """
    cur = con.cursor()
    params = []
    extra = ''
    if sport:
        extra += ' AND s.name = %s'
        params.append(sport)
    if league:
        extra += ' AND l.league_name = %s'
        params.append(league)

    cur.execute(f"""
        SELECT m.match_id, m.name, m.match_date,
               s.name AS sport_name, l.league_name,
               m.league_id, m.season_id,
               COUNT(md.match_detail_id) AS n_details,
               COALESCE(SUM(CASE WHEN md.home    THEN 1 ELSE 0 END), 0) AS homes,
               COALESCE(SUM(CASE WHEN md.visitor THEN 1 ELSE 0 END), 0) AS visitors,
               COALESCE(ARRAY_AGG(md.team_id) FILTER (WHERE md.team_id IS NOT NULL), '{{}}') AS team_ids
          FROM match m
          JOIN league l ON l.league_id = m.league_id
          JOIN sport  s ON s.sport_id  = l.sport_id
          LEFT JOIN match_detail md ON md.match_id = m.match_id
         WHERE s.name NOT IN %s
           {extra}
         GROUP BY m.match_id, m.name, m.match_date, s.name, l.league_name,
                  m.league_id, m.season_id
        HAVING COUNT(md.match_detail_id) < 2
            OR COALESCE(SUM(CASE WHEN md.home    THEN 1 ELSE 0 END), 0) <> 1
            OR COALESCE(SUM(CASE WHEN md.visitor THEN 1 ELSE 0 END), 0) <> 1
         ORDER BY m.match_date DESC NULLS LAST
    """, (EXCLUDED_SPORTS, *params))

    cols = ['match_id', 'name', 'match_date', 'sport_name', 'league_name',
            'league_id', 'season_id', 'n_details', 'homes', 'visitors', 'team_ids']
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def parse_match_name(name):
    """'TeamA~TeamB' → ('TeamA', 'TeamB'). Retorna (None, None) si no se puede."""
    if not name or NAME_SEP not in name:
        return None, None
    parts = name.split(NAME_SEP, 1)
    home    = parts[0].strip() or None
    visitor = parts[1].strip() or None
    return home, visitor


def lookup_team_id(con, team_name, league_id, season_id):
    """Busca team_id por nombre, league_id y season_id."""
    if not team_name:
        return None
    cur = con.cursor()
    cur.execute("""
        SELECT t.team_id
          FROM league_team lt
          JOIN team t ON lt.team_id = t.team_id
         WHERE lt.league_id = %s
           AND lt.season_id = %s
           AND t.team_name  = %s
         LIMIT 1
    """, (league_id, season_id, team_name))
    row = cur.fetchone()
    return row[0] if row else None


def insert_match_detail(con, match_id, team_id, home, visitor):
    """INSERT en match_detail. Caller hace el commit."""
    cur = con.cursor()
    cur.execute("""
        INSERT INTO match_detail (match_detail_id, home, visitor, match_id, team_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (generate_uuid(), home, visitor, match_id, team_id))


def plan_fix_for_match(con, m):
    """
    Determina qué filas hay que insertar para arreglar un match.

    Retorna lista de tuplas: [(team_name, team_id_or_None, role), ...]
      role: 'home' | 'visitor'
    Si team_id es None, no se podrá insertar (queda registrado como sin resolver).
    """
    home_name, visitor_name = parse_match_name(m['name'])

    has_home    = m['homes']    >= 1
    has_visitor = m['visitors'] >= 1

    to_insert = []

    # Si no aparece home y tenemos nombre → insertarlo
    if not has_home and home_name:
        tid = lookup_team_id(con, home_name, m['league_id'], m['season_id'])
        to_insert.append((home_name, tid, 'home'))

    # Si no aparece visitor y tenemos nombre → insertarlo
    if not has_visitor and visitor_name:
        tid = lookup_team_id(con, visitor_name, m['league_id'], m['season_id'])
        to_insert.append((visitor_name, tid, 'visitor'))

    return to_insert


def fix_inconsistent_matches(dry_run=True, sport=None, league=None, verbose=True):
    """
    Función principal — recorre los matches inconsistentes e intenta completarlos.

    Args:
        dry_run : True (default) imprime sin tocar la DB. False inserta.
        sport   : filtra por sport.name (ej. 'Football')
        league  : filtra por league.league_name
        verbose : imprime detalle por match

    Returns:
        dict con stats: { total, fixed, partially_fixed, unresolved, skipped }
    """
    con = getdb()
    try:
        matches = find_inconsistent_matches(con, sport=sport, league=league)
        stats = Counter()
        stats['total'] = len(matches)

        if verbose:
            print('=' * 72)
            print(f'INCONSISTENT MATCHES: {len(matches)}  (dry_run={dry_run})')
            if sport:  print(f'  filter sport = {sport}')
            if league: print(f'  filter league = {league}')
            print('=' * 72)

        for m in matches:
            home_name, visitor_name = parse_match_name(m['name'])

            if verbose:
                print(f"\n[{m['sport_name']}] {m['league_name']} — {m['match_date']}")
                print(f"  match_id : {m['match_id']}")
                print(f"  name     : {m['name']!r}")
                print(f"  details  : {m['n_details']} (homes={m['homes']}, visitors={m['visitors']})")

            if not home_name or not visitor_name:
                print(f"  [SKIP] no se pudo parsear name con separador '{NAME_SEP}'")
                stats['skipped'] += 1
                continue

            to_insert = plan_fix_for_match(con, m)
            if not to_insert:
                print('  [SKIP] nada para insertar (ya tenía home y visitor)')
                stats['skipped'] += 1
                continue

            unresolved_in_this = 0
            inserted = 0
            for team_name, team_id, role in to_insert:
                if not team_id:
                    print(f"  [UNRESOLVED] {role:7s} '{team_name}' no existe en league_team de esta liga/temporada")
                    unresolved_in_this += 1
                    continue
                action = 'WOULD INSERT' if dry_run else 'INSERT'
                print(f"  [{action}] {role:7s} '{team_name}' team_id={team_id}")
                if not dry_run:
                    insert_match_detail(
                        con, m['match_id'], team_id,
                        home=(role == 'home'), visitor=(role == 'visitor'),
                    )
                inserted += 1

            if not dry_run and inserted:
                con.commit()

            if unresolved_in_this == 0 and inserted == len(to_insert):
                stats['fixed'] += 1
            elif inserted > 0:
                stats['partially_fixed'] += 1
            else:
                stats['unresolved'] += 1

        # Resumen
        print('\n' + '=' * 72)
        print(f"RESUMEN  (dry_run={dry_run})")
        print(f"  Total inconsistentes : {stats['total']}")
        print(f"  Reparados            : {stats['fixed']}")
        print(f"  Reparados parcial    : {stats['partially_fixed']}")
        print(f"  Sin resolver         : {stats['unresolved']}")
        print(f"  Omitidos             : {stats['skipped']}")
        print('=' * 72)
        return dict(stats)
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',  action='store_true', help='Escribe en DB (default: dry-run)')
    p.add_argument('--sport',  default=None,        help='Filtra por sport.name (ej. Football)')
    p.add_argument('--league', default=None,        help='Filtra por league.league_name')
    p.add_argument('--quiet',  action='store_true', help='Menos verboso')
    args = p.parse_args()

    fix_inconsistent_matches(
        dry_run=not args.apply,
        sport=args.sport,
        league=args.league,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
