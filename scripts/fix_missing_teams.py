"""
fix_missing_teams.py
=====================
Detecta equipos referenciados por nombre en `match.name` que no estan
registrados en `league_team` para esa liga+temporada (y opcionalmente
tampoco existen en la tabla `team`), y permite repararlos.

CONTEXTO
--------
Algunos partidos quedan en `match` con `match_detail` incompleto porque
en el momento de la extraccion uno de los equipos:

  * NO estaba registrado en `league_team` para la liga/temporada del partido
    (pero si existe en la tabla `team`, por ejemplo porque jugo en otra liga
    o temporada).
  * NO existe en absoluto en la tabla `team` (caso tipico: selecciones
    nacionales en torneos puntuales como World Cup, equipos recien creados,
    etc.).

Este script complementa a `fix_inconsistent_matches.py`: aquel solo puede
insertar `match_detail` cuando el `team_id` se encuentra via
`league_team`. Si el equipo no esta registrado en esa liga/temporada,
queda como "parcialmente reparable". Este script resuelve esa causa raiz.

CLASIFICACION DE FALTANTES
--------------------------
Para cada (sport_id, country_id_liga, team_name) faltante:

  REGISTRATION_MISSING : existe en `team` (uniquely match con sport_id
                         + country_id de la liga) pero no en `league_team`.
                         Solucion: INSERT en `league_team`.

  AMBIGUOUS            : existe mas de un `team` con ese nombre/sport
                         y no se pudo desambiguar por country_id.
                         Requiere revision manual.

  TEAM_MISSING         : no existe en `team`. Solucion (con --create-teams):
                         INSERT en `team` (usa country_id de la liga) +
                         INSERT en `league_team`.

USO
---
    # Solo reportar (default):
    python scripts/fix_missing_teams.py

    # Aplicar registracion (REGISTRATION_MISSING) — NO crea equipos nuevos:
    python scripts/fix_missing_teams.py --apply

    # Aplicar y ADEMAS crear equipos faltantes (TEAM_MISSING):
    python scripts/fix_missing_teams.py --apply --create-teams

    # Filtros:
    python scripts/fix_missing_teams.py --sport Football
    python scripts/fix_missing_teams.py --league "Liga de Primera"

DOCUMENTACION DE FUNCIONES
--------------------------
- detect_missing_teams(con, sport, league)
    → Recorre matches inconsistentes (mismo criterio que
      fix_inconsistent_matches), parsea match.name y devuelve una lista
      de dicts con la info de cada equipo faltante por liga+temporada.

- classify_team(con, team_name, sport_id, country_id_league)
    → Busca el team_name en `team`. Retorna (status, team_id_or_None,
      candidates) donde status ∈ {REGISTRATION_MISSING, AMBIGUOUS,
      TEAM_MISSING}.

- register_team_in_league(con, team_id, league_id, season_id)
    → INSERT en league_team. Caller hace commit.

- create_team(con, team_name, sport_id, country_id)
    → INSERT en team y retorna el nuevo team_id (UUID). Caller hace commit.

- fix_missing_teams(dry_run=True, apply_creates=False, sport=None,
                    league=None, verbose=True)
    → Funcion principal. Orquesta todo y reporta stats.
"""

import sys, os, argparse
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from data_base import getdb
from common_functions import generate_uuid

# Misma lista que en fix_inconsistent_matches.py — deportes que no siguen
# el modelo team-vs-team con home/visitor.
EXCLUDED_SPORTS = ('MOTOR SPORT', 'Boxing', 'Tennis', 'GOLF')
NAME_SEP = '~'

# Status de clasificacion
REGISTRATION_MISSING = 'REGISTRATION_MISSING'
AMBIGUOUS            = 'AMBIGUOUS'
TEAM_MISSING         = 'TEAM_MISSING'


# ─── Deteccion ──────────────────────────────────────────────────────────────

def detect_missing_teams(con, sport=None, league=None):
    """
    Recorre matches inconsistentes y reporta los equipos faltantes.

    Para cada match incompleto:
      - parsea match.name por '~' para extraer home_name y visitor_name
      - identifica que lado(s) no estan en match_detail
      - el lado faltante => candidato a "equipo faltante"

    Args:
        con    : conexion psycopg2 activa.
        sport  : filtra por sport.name (str) o None.
        league : filtra por league.league_name (str) o None.

    Returns:
        list[dict] con keys:
            match_id, match_name, match_date,
            sport_name, sport_id,
            league_name, league_id, league_country_id,
            season_id,
            team_name        — nombre del equipo faltante
            role             — 'home' | 'visitor'
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
               s.name, s.sport_id,
               l.league_name, l.league_id, l.country_id,
               m.season_id,
               COALESCE(SUM(CASE WHEN md.home    THEN 1 ELSE 0 END), 0) AS homes,
               COALESCE(SUM(CASE WHEN md.visitor THEN 1 ELSE 0 END), 0) AS visitors
          FROM match m
          JOIN league l ON l.league_id = m.league_id
          JOIN sport  s ON s.sport_id  = l.sport_id
          LEFT JOIN match_detail md ON md.match_id = m.match_id
         WHERE s.name NOT IN %s
           {extra}
         GROUP BY m.match_id, m.name, m.match_date, s.name, s.sport_id,
                  l.league_name, l.league_id, l.country_id, m.season_id
        HAVING COUNT(md.match_detail_id) < 2
            OR COALESCE(SUM(CASE WHEN md.home    THEN 1 ELSE 0 END), 0) <> 1
            OR COALESCE(SUM(CASE WHEN md.visitor THEN 1 ELSE 0 END), 0) <> 1
         ORDER BY m.match_date DESC NULLS LAST
    """, (EXCLUDED_SPORTS, *params))

    missing = []
    for row in cur.fetchall():
        (match_id, match_name, match_date,
         sport_name, sport_id,
         league_name, league_id, league_country_id,
         season_id, homes, visitors) = row

        if not match_name or NAME_SEP not in match_name:
            continue

        home_part, visitor_part = match_name.split(NAME_SEP, 1)
        home_name    = home_part.strip()    or None
        visitor_name = visitor_part.strip() or None

        base = dict(
            match_id=match_id, match_name=match_name, match_date=match_date,
            sport_name=sport_name, sport_id=sport_id,
            league_name=league_name, league_id=league_id,
            league_country_id=league_country_id, season_id=season_id,
        )

        if homes < 1 and home_name:
            missing.append({**base, 'team_name': home_name, 'role': 'home'})
        if visitors < 1 and visitor_name:
            missing.append({**base, 'team_name': visitor_name, 'role': 'visitor'})

    return missing


# ─── Clasificacion ──────────────────────────────────────────────────────────

def classify_team(con, team_name, sport_id, country_id_league):
    """
    Determina si un team_name existe ya en `team` y si esta listo para
    registrar en `league_team`.

    Args:
        team_name         : nombre buscado.
        sport_id          : sport del partido (para evitar colisiones entre
                            deportes con mismo nombre de equipo).
        country_id_league : country_id de la liga; se usa para desambiguar
                            cuando hay varios teams con el mismo nombre.

    Returns:
        (status, team_id, candidates)

          status     : REGISTRATION_MISSING | AMBIGUOUS | TEAM_MISSING
          team_id    : team_id resuelto si status == REGISTRATION_MISSING;
                       None en los otros casos.
          candidates : lista de (team_id, country_id) — todos los teams
                       encontrados con ese nombre+sport (vacia si TEAM_MISSING).
    """
    cur = con.cursor()
    cur.execute(
        "SELECT team_id, country_id FROM team WHERE team_name = %s AND sport_id = %s",
        (team_name, sport_id),
    )
    candidates = cur.fetchall()

    if not candidates:
        return TEAM_MISSING, None, []

    if len(candidates) == 1:
        return REGISTRATION_MISSING, candidates[0][0], candidates

    # Mas de un candidato → desambiguar por country_id de la liga
    matches_country = [tid for tid, cid in candidates if cid == country_id_league]
    if len(matches_country) == 1:
        return REGISTRATION_MISSING, matches_country[0], candidates

    return AMBIGUOUS, None, candidates


# ─── Acciones de escritura ──────────────────────────────────────────────────

def register_team_in_league(con, team_id, league_id, season_id):
    """
    Crea la fila en `league_team` que asocia un team con una liga+temporada.
    Caller hace commit.

    Returns:
        instance_id (UUID) generado.
    """
    cur = con.cursor()
    instance_id = generate_uuid()
    cur.execute("""
        INSERT INTO league_team (instance_id, team_meta, team_position,
                                 league_id, season_id, team_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (instance_id, None, None, league_id, season_id, team_id))
    return instance_id


def create_team(con, team_name, sport_id, country_id):
    """
    Crea un team nuevo. Caller hace commit.

    Returns:
        nuevo team_id (UUID).
    """
    cur = con.cursor()
    team_id = generate_uuid()
    cur.execute("""
        INSERT INTO team (team_id, country_id, team_desc, team_logo, team_name, sport_id)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (team_id, country_id, None, None, team_name, sport_id))
    return team_id


# ─── Orquestacion ───────────────────────────────────────────────────────────

def fix_missing_teams(dry_run=True, apply_creates=False,
                      sport=None, league=None, verbose=True):
    """
    Funcion principal — detecta, clasifica y opcionalmente repara equipos
    faltantes referenciados por partidos inconsistentes.

    Args:
        dry_run       : True (default) NO escribe en DB; solo imprime el plan.
                        False ejecuta las INSERTS de `league_team` (siempre)
                        y de `team` si apply_creates=True.
        apply_creates : Solo aplica si dry_run=False. Si True, crea equipos
                        nuevos en `team` para los TEAM_MISSING. Si False,
                        los TEAM_MISSING se reportan pero no se crean.
        sport         : Filtra por sport.name.
        league        : Filtra por league.league_name.
        verbose       : Detalle por equipo.

    Returns:
        dict { total_missing, registered, created, ambiguous, skipped, errors }
        donde:
          registered = filas insertadas en league_team
          created    = teams nuevos creados en team
          ambiguous  = casos que requieren revision manual
          skipped    = TEAM_MISSING que no se crearon (apply_creates=False)
    """
    con = getdb()
    try:
        missing = detect_missing_teams(con, sport=sport, league=league)

        # Deduplicar por (sport_id, league_id, season_id, team_name) para no
        # intentar registrar dos veces el mismo equipo aunque aparezca en
        # varios partidos. Conservamos un match_id de muestra y la lista de
        # roles afectados para reportar.
        agg = defaultdict(lambda: {'matches': [], 'roles': set()})
        for m in missing:
            key = (m['sport_id'], m['league_id'], m['season_id'],
                   m['league_country_id'], m['team_name'])
            agg[key]['matches'].append(m['match_id'])
            agg[key]['roles'].add(m['role'])
            agg[key]['sport_name']  = m['sport_name']
            agg[key]['league_name'] = m['league_name']

        stats = Counter()
        stats['total_missing'] = len(agg)

        if verbose:
            print('=' * 72)
            print(f'EQUIPOS FALTANTES UNICOS: {len(agg)}  '
                  f'(dry_run={dry_run}, apply_creates={apply_creates})')
            if sport:  print(f'  filter sport  = {sport}')
            if league: print(f'  filter league = {league}')
            print('=' * 72)

        for (sport_id, league_id, season_id, country_id_league, team_name), info in agg.items():
            status, team_id, candidates = classify_team(
                con, team_name, sport_id, country_id_league,
            )

            if verbose:
                print(f"\n[{info['sport_name']}] {info['league_name']} — {team_name!r}")
                print(f"  partidos afectados : {len(info['matches'])}")
                print(f"  roles              : {sorted(info['roles'])}")
                print(f"  status             : {status}")
                if candidates:
                    print(f"  candidates en team : {candidates}")

            if status == AMBIGUOUS:
                print('  [REVISAR] mas de un team_id posible — saltado')
                stats['ambiguous'] += 1
                continue

            # Determinar team_id final
            if status == TEAM_MISSING:
                if not apply_creates:
                    print('  [SKIP] team no existe; usar --create-teams para crearlo')
                    stats['skipped'] += 1
                    continue
                if dry_run:
                    print(f"  [WOULD CREATE TEAM] '{team_name}' "
                          f"sport_id={sport_id} country_id={country_id_league}")
                    print('  [WOULD REGISTER] league_team (team_id=<nuevo>)')
                    stats['skipped'] += 1   # en dry-run no contamos como creado
                    continue
                if not country_id_league:
                    print('  [ERROR] liga sin country_id; no se puede crear team')
                    stats['errors'] += 1
                    continue
                try:
                    team_id = create_team(con, team_name, sport_id, country_id_league)
                    print(f"  [CREATED TEAM] team_id={team_id}")
                    stats['created'] += 1
                except Exception as e:
                    con.rollback()
                    print(f'  [ERROR] creando team: {e}')
                    stats['errors'] += 1
                    continue

            # REGISTRATION_MISSING (o TEAM_MISSING que acabamos de crear)
            if dry_run:
                print(f"  [WOULD REGISTER] league_team(team_id={team_id}, "
                      f"league_id={league_id}, season_id={season_id})")
                continue
            try:
                instance_id = register_team_in_league(
                    con, team_id, league_id, season_id,
                )
                con.commit()
                print(f"  [REGISTERED] instance_id={instance_id}")
                stats['registered'] += 1
            except Exception as e:
                con.rollback()
                print(f'  [ERROR] registrando en league_team: {e}')
                stats['errors'] += 1

        # ─── Resumen ────────────────────────────────────────────────────────
        print('\n' + '=' * 72)
        print(f"RESUMEN  (dry_run={dry_run}, apply_creates={apply_creates})")
        print(f"  Equipos faltantes unicos : {stats['total_missing']}")
        print(f"  Registrados en league_team: {stats['registered']}")
        print(f"  Teams creados             : {stats['created']}")
        print(f"  Ambiguos (revisar)        : {stats['ambiguous']}")
        print(f"  Omitidos                  : {stats['skipped']}")
        print(f"  Errores                   : {stats['errors']}")
        print('=' * 72)

        if not dry_run and stats['registered']:
            print('\nTIP: ahora corre `fix_inconsistent_matches.py --apply` '
                  'para completar los match_detail.')

        return dict(stats)
    finally:
        con.close()


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description='Detecta y crea equipos faltantes en league_team / team.',
    )
    p.add_argument('--apply',         action='store_true',
                   help='Aplica los cambios en DB (default: dry-run).')
    p.add_argument('--create-teams',  action='store_true',
                   help='Tambien crea teams nuevos para los TEAM_MISSING.')
    p.add_argument('--sport',         default=None,
                   help='Filtra por sport.name (ej. Football).')
    p.add_argument('--league',        default=None,
                   help='Filtra por league.league_name.')
    p.add_argument('--quiet',         action='store_true', help='Menos verboso.')
    args = p.parse_args()

    fix_missing_teams(
        dry_run=not args.apply,
        apply_creates=args.create_teams,
        sport=args.sport,
        league=args.league,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
