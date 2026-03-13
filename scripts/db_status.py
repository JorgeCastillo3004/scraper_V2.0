"""
db_status.py
------------
Muestra el estado actual de la base de datos: deportes, ligas, equipos y partidos.

Uso:
    source /home/you/env/sports_env/bin/activate
    python db_status.py
"""

import psycopg2
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS


def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def print_status():
    con = get_connection()
    cur = con.cursor()

    # Deportes
    cur.execute("SELECT sport_id, name FROM sport ORDER BY name;")
    sports = cur.fetchall()

    # Ligas con equipos y partidos
    print()
    print("=" * 70)
    print("LIGAS")
    print("=" * 70)
    for sport_id, sport_name in sports:
        cur.execute("""
            SELECT l.league_id, l.league_name, c.country_name
            FROM league l JOIN country c ON l.country_id = c.country_id
            WHERE l.sport_id = %s ORDER BY c.country_name, l.league_name
        """, (sport_id,))
        leagues = cur.fetchall()
        if not leagues:
            continue
        print(f"\n  [{sport_name.upper()}]")
        for lid, lname, country in leagues:
            cur.execute("SELECT COUNT(DISTINCT team_id) FROM league_team WHERE league_id = %s", (lid,))
            teams = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM match WHERE league_id = %s", (lid,))
            matches = cur.fetchone()[0]
            print(f"    {country.upper():<30} {lname:<35} equipos={teams:>3}  partidos={matches:>4}")

    # Resumen por deporte
    print()
    print("=" * 70)
    print(f"{'DEPORTE':<22} {'LIGAS':>6} {'EQUIPOS':>8} {'PARTIDOS':>9}")
    print("-" * 70)
    total_leagues = total_teams = total_matches = 0
    for sport_id, sport_name in sports:
        cur.execute("SELECT COUNT(*) FROM league WHERE sport_id = %s", (sport_id,))
        n_leagues = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM team WHERE sport_id = %s", (sport_id,))
        n_teams = cur.fetchone()[0]
        cur.execute("""
            SELECT COUNT(*) FROM match
            WHERE league_id IN (SELECT league_id FROM league WHERE sport_id = %s)
        """, (sport_id,))
        n_matches = cur.fetchone()[0]
        print(f"  {sport_name.upper():<20} {n_leagues:>6} {n_teams:>8} {n_matches:>9}")
        total_leagues += n_leagues
        total_teams   += n_teams
        total_matches += n_matches
    print("-" * 70)
    print(f"  {'TOTAL':<20} {total_leagues:>6} {total_teams:>8} {total_matches:>9}")
    print("=" * 70)
    print()

    cur.close()
    con.close()


if __name__ == "__main__":
    print_status()
