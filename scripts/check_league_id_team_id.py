#!/usr/bin/env python3
"""
check_league_id_team_id.py
==========================
Muestra ligas y equipos de un deporte, con sus IDs.

Uso:
  python3 scripts/check_league_id_team_id.py FOOTBALL
  python3 scripts/check_league_id_team_id.py BASKETBALL
  python3 scripts/check_league_id_team_id.py HOCKEY
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

# ── Colores ANSI ──────────────────────────────────────────────────────────────
W   = "\033[97m"
C   = "\033[96m"
G   = "\033[92m"
Y   = "\033[93m"
DIM = "\033[2m"
RST = "\033[0m"


def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def fetch_data(sport_name):
    query = """
    SELECT
        sport.name          AS sport_name,
        league.league_id,
        league.league_name,
        country.country_name,
        team.team_id,
        team.team_name
    FROM sport
    JOIN league  ON league.sport_id   = sport.sport_id
    JOIN country ON league.country_id = country.country_id
    JOIN league_team ON league_team.league_id = league.league_id
    JOIN team    ON team.team_id      = league_team.team_id
    WHERE UPPER(sport.name) = UPPER(%s)
    ORDER BY league.league_name, team.team_name;
    """
    con = get_connection()
    cur = con.cursor()
    cur.execute(query, (sport_name,))
    rows = cur.fetchall()
    cur.close()
    con.close()
    return rows


def print_results(sport_name, rows):
    if not rows:
        print(f"\n  {Y}Sin resultados para el deporte: '{sport_name}'{RST}")
        print(f"  {DIM}Verifica que el nombre sea exacto: FOOTBALL, BASKETBALL, HOCKEY, TENNIS, GOLF...{RST}\n")
        return

    # ── Agrupar por liga ──────────────────────────────────────────────────────
    leagues = {}
    for sport_name_, league_id, league_name, country_name, team_id, team_name in rows:
        key = (league_id, league_name, country_name)
        if key not in leagues:
            leagues[key] = []
        leagues[key].append((team_id, team_name))

    # ── Sección deporte ───────────────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print(f"  {W}{sport_name}{RST}  {DIM}({len(leagues)} ligas  |  {len(rows)} equipos){RST}")
    print(f"{'═'*60}")

    for (league_id, league_name, country_name), teams in leagues.items():
        # subsección liga
        print(f"\n  {C}▸ {league_name}{RST}  {DIM}[{country_name}]{RST}")
        print(f"    {DIM}league_id: {league_id}{RST}")
        print(f"    {'─'*50}")

        for team_id, team_name in teams:
            print(f"    {G}{team_id}{RST}  {team_name}")

    print()


def main():
    if len(sys.argv) < 2:
        print(f"\n  {Y}Uso: python3 scripts/check_league_id_team_id.py <DEPORTE>{RST}")
        print(f"  {DIM}Ejemplo: python3 scripts/check_league_id_team_id.py FOOTBALL{RST}\n")
        sys.exit(1)

    sport_name = " ".join(sys.argv[1:])
    print(f"\n{DIM}Conectando a {DB_HOST}/{DB_NAME}...{RST}")
    rows = fetch_data(sport_name)
    print_results(sport_name, rows)


if __name__ == "__main__":
    main()
