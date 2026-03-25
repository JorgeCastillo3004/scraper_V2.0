#!/usr/bin/env python3
"""
validacion.py
=============
Valida partidos en curso consultando match, match_detail, team,
sport, score_entity y country.

Uso:
  python3 scripts/validacion.py                        # todos los LIVE
  python3 scripts/validacion.py --status "IN PROGRESS" # otro valor de status
  python3 scripts/validacion.py --sport_id <id>        # filtrar por deporte
  python3 scripts/validacion.py --team_id <id>         # filtrar por equipo
  python3 scripts/validacion.py --sport_id <id> --team_id <id>
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

# ── Colores ANSI ──────────────────────────────────────────────────────────────
G   = "\033[92m"
Y   = "\033[93m"
C   = "\033[96m"
W   = "\033[97m"
DIM = "\033[2m"
RST = "\033[0m"


def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def run_validation(status='IN PROGRESS', sport_id=None, team_id=None):
    query = """
    SELECT
        match.match_id,
        match_detail.home,
        match.name,
        match.statistic,
        sport.name          AS sport_name,
        team.team_name,
        team.team_logo,
        country.country_name,
        score_entity.points
    FROM match
    JOIN match_detail  ON match.match_id              = match_detail.match_id
    JOIN team          ON team.team_id                = match_detail.team_id
    JOIN sport         ON sport.sport_id              = team.sport_id
    JOIN score_entity  ON score_entity.match_detail_id = match_detail.match_detail_id
    JOIN country       ON team.country_id             = country.country_id
    WHERE match.status = %s
    """
    params = [status]

    if sport_id:
        query += "  AND sport.sport_id = %s\n"
        params.append(sport_id)
    if team_id:
        query += "  AND team.team_id = %s\n"
        params.append(team_id)

    query += "  ORDER BY sport.name, match.name, match_detail.home DESC;"

    con = get_connection()
    cur = con.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    con.close()
    return rows


def print_results(rows, status, sport_id, team_id):
    # ── Cabecera ──────────────────────────────────────────────────────────────
    filters = f"status='{status}'"
    if sport_id:
        filters += f"  sport_id='{sport_id}'"
    if team_id:
        filters += f"  team_id='{team_id}'"

    print(f"\n{W}{'═'*72}{RST}")
    print(f"{W}  VALIDACIÓN DE PARTIDOS  —  {filters}{RST}")
    print(f"{W}{'═'*72}{RST}")

    if not rows:
        print(f"\n  {Y}Sin resultados para los filtros indicados.{RST}")
        print(f"  {DIM}Tip: los valores de status en uso son COMPLETED, SCHEDULED, IN PROGRESS{RST}\n")
        return

    # ── Agrupar por partido ───────────────────────────────────────────────────
    matches = {}
    for match_id, home, name, statistic, sport_name, team_name, team_logo, country_name, points in rows:
        if match_id not in matches:
            matches[match_id] = {
                'name': name,
                'sport': sport_name,
                'statistic': statistic,
                'teams': []
            }
        matches[match_id]['teams'].append({
            'home': home,
            'team_name': team_name,
            'team_logo': team_logo,
            'country': country_name,
            'points': points,
        })

    print(f"  {G}Partidos encontrados: {len(matches)}{RST}  {DIM}({len(rows)} registros match_detail){RST}\n")

    for match_id, data in matches.items():
        print(f"  {C}{'─'*68}{RST}")
        print(f"  {W}{data['sport']:<14}{RST}  {data['name']}")
        print(f"  {DIM}match_id : {match_id}{RST}")
        if data['statistic']:
            print(f"  {DIM}statistic: {data['statistic']}{RST}")

        # ordenar: home primero
        teams = sorted(data['teams'], key=lambda t: not t['home'])
        for t in teams:
            role   = f"{G}HOME   {RST}" if t['home'] else f"{Y}VISITOR{RST}"
            points = t['points'] if t['points'] is not None else '-'
            logo   = f"  logo={t['team_logo']}" if t['team_logo'] else ""
            print(f"    {role}  {t['team_name']:<30} pts={str(points):<6} ({t['country']}){logo}")

    print(f"\n  {DIM}Total registros: {len(rows)}{RST}\n")


def main():
    parser = argparse.ArgumentParser(description="Validación de partidos en la DB")
    parser.add_argument("--status",   default="IN PROGRESS",  help="Valor de match.status (default: 'IN PROGRESS')")
    parser.add_argument("--sport_id", default=None, help="Filtrar por sport_id")
    parser.add_argument("--team_id",  default=None, help="Filtrar por team_id")
    args = parser.parse_args()

    print(f"\n{DIM}Conectando a {DB_HOST}/{DB_NAME}...{RST}")
    rows = run_validation(
        status=args.status,
        sport_id=args.sport_id,
        team_id=args.team_id
    )
    print_results(rows, args.status, args.sport_id, args.team_id)


if __name__ == "__main__":
    main()
