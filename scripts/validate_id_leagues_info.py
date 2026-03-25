#!/usr/bin/env python3
"""
validate_id_leagues_info.py
===========================
Compara league_id, season_id y country_id del archivo leagues_info.json
contra los valores reales en la base de datos.

Muestra solo las ligas donde al menos un ID difiere.

Uso:
  python3 scripts/validate_id_leagues_info.py               # todos los deportes
  python3 scripts/validate_id_leagues_info.py FOOTBALL      # un deporte
  python3 scripts/validate_id_leagues_info.py FOOTBALL HOCKEY
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

LEAGUES_INFO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'check_points', 'leagues_info.json'
)

# DB sport name → JSON sport key
sport_name_map = {
    'Football': 'FOOTBALL', 'Basketball': 'BASKETBALL', 'Baseball': 'BASEBALL',
    'Hockey': 'HOCKEY', 'Tennis': 'TENNIS', 'Golf': 'GOLF',
    'Boxing': 'BOXING', 'American Football': 'AM._FOOTBALL',
}
# JSON sport key → DB sport name (reverso)
json_to_db_sport = {v: k for k, v in sport_name_map.items()}

# ── Colores ANSI ──────────────────────────────────────────────────────────────
W   = "\033[97m"
C   = "\033[96m"
G   = "\033[92m"
R   = "\033[91m"
Y   = "\033[93m"
DIM = "\033[2m"
RST = "\033[0m"


def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def fetch_db_ids(cur, league_name, sport_json_key, country_name):
    """Devuelve (league_id, season_id, country_id) desde la DB filtrando por liga, deporte y país."""
    db_sport_name = json_to_db_sport.get(sport_json_key, sport_json_key)
    cur.execute("""
        SELECT
            l.league_id,
            s.season_id,
            l.country_id
        FROM league l
        JOIN sport   sp ON sp.sport_id   = l.sport_id
        JOIN country c  ON c.country_id  = l.country_id
        LEFT JOIN season s ON s.league_id = l.league_id
        WHERE UPPER(l.league_name)   = UPPER(%s)
          AND UPPER(sp.name)         = UPPER(%s)
          AND UPPER(c.country_name)  = UPPER(%s)
        ORDER BY s.season_end DESC
        LIMIT 1;
    """, (league_name, db_sport_name, country_name))
    return cur.fetchone()


def parse_key(key):
    """Extrae (country, league_name) desde la clave 'PAIS_NombreLiga'."""
    parts = key.split('_', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return '', key


def compare_ids(json_val, db_val, field):
    """Retorna dict con info de la comparación si hay diferencia."""
    if json_val != db_val:
        return {'field': field, 'json': json_val, 'db': db_val}
    return None


def validate(data, sport_filter=None):
    con = get_connection()
    cur = con.cursor()

    total_leagues   = 0
    total_diffs     = 0
    total_not_found = 0
    # acumula los cambios pendientes: {sport: {key: {field: db_value}}}
    pending_fixes = {}

    for sport, leagues in data.items():
        if sport_filter and sport.upper() not in [s.upper() for s in sport_filter]:
            continue

        sport_diffs     = []
        sport_not_found = []
        sport_league_ids = []   # comparación league_id para todas las ligas del deporte

        for key, info in leagues.items():
            total_leagues += 1
            country_name, league_name_parsed = parse_key(key)
            league_name = info.get('league_name') or league_name_parsed
            # si league_name coincide con el key completo, fue guardado incorrectamente
            if league_name == key:
                league_name = league_name_parsed

            db_row = fetch_db_ids(cur, league_name, sport, country_name)

            if not db_row:
                sport_not_found.append((key, league_name, country_name))
                sport_league_ids.append((key, info.get('league_id'), None))
                total_not_found += 1
                continue

            db_league_id, db_season_id, db_country_id = db_row

            # registrar comparación de league_id siempre
            sport_league_ids.append((key, info.get('league_id'), db_league_id))

            diffs = []
            for field, json_val, db_val in [
                ('league_id',  info.get('league_id'),  db_league_id),
                ('season_id',  info.get('season_id'),  db_season_id),
                ('country_id', info.get('country_id'), db_country_id),
            ]:
                result = compare_ids(json_val, db_val, field)
                if result:
                    diffs.append(result)

            if diffs:
                sport_diffs.append((key, league_name, diffs))
                total_diffs += 1
                # registrar correcciones pendientes
                if sport not in pending_fixes:
                    pending_fixes[sport] = {}
                pending_fixes[sport][key] = {d['field']: d['db'] for d in diffs}

        # ── Imprimir sección deporte ──────────────────────────────────────────
        print(f"\n{'═'*65}")
        print(f"  {W}{sport}{RST}  {DIM}({len(leagues)} ligas){RST}")
        print(f"{'═'*65}")

        # comparación league_id para cada liga
        print(f"\n  {DIM}{'LIGA':<35} {'JSON league_id':<38} {'DB league_id'}{RST}")
        print(f"  {'─'*100}")
        for key, json_lid, db_lid in sport_league_ids:
            if db_lid is None:
                icon = Y + '?' + RST
                db_str = f"{Y}no encontrada{RST}"
            elif json_lid == db_lid:
                icon = G + '✓' + RST
                db_str = f"{G}{db_lid}{RST}"
            else:
                icon = R + '✗' + RST
                db_str = f"{R}{db_lid}{RST}"
            json_str = json_lid or f"{DIM}(vacío){RST}"
            print(f"  {icon} {key:<35} {json_str:<38} {db_str}")

        # detalle de campos con diferencias
        if sport_diffs:
            print(f"\n  {R}Campos con diferencias:{RST}")
            for key, league_name, diffs in sport_diffs:
                print(f"\n  {C}▸ {key}{RST}  {DIM}({league_name}){RST}")
                for d in diffs:
                    print(f"    {R}✗ {d['field']}{RST}")
                    print(f"      {DIM}JSON : {d['json']}{RST}")
                    print(f"      {G}DB   : {d['db']}{RST}")

        for key, league_name, country_name in sport_not_found:
            print(f"\n  {Y}▸ {key}{RST}  {DIM}— no encontrada en DB  liga='{league_name}'  país='{country_name}'  deporte='{sport}'{RST}")

    cur.close()
    con.close()

    # ── Resumen final ─────────────────────────────────────────────────────────
    print(f"\n{'═'*65}")
    print(f"  {W}RESUMEN{RST}")
    print(f"{'═'*65}")
    print(f"  Ligas revisadas  : {total_leagues}")
    print(f"  Con diferencias  : {R}{total_diffs}{RST}" if total_diffs else f"  Con diferencias  : {G}0{RST}")
    print(f"  No encontradas   : {Y}{total_not_found}{RST}" if total_not_found else f"  No encontradas   : {G}0{RST}")
    if total_diffs == 0 and total_not_found == 0:
        print(f"\n  {G}✔  Todos los IDs coinciden con la base de datos.{RST}")
    print()

    return pending_fixes, data


def apply_fixes(data, pending_fixes):
    """Aplica los IDs correctos de la DB sobre el dict data en memoria."""
    total = 0
    for sport, leagues in pending_fixes.items():
        for key, fields in leagues.items():
            for field, db_val in fields.items():
                data[sport][key][field] = db_val
                total += 1
    return total


def confirm_and_save(data, pending_fixes):
    if not pending_fixes:
        return

    total_fields = sum(len(f) for leagues in pending_fixes.values() for f in leagues.values())
    total_leagues = sum(len(leagues) for leagues in pending_fixes.values())

    print(f"{'═'*65}")
    print(f"  {W}ACTUALIZAR ARCHIVO{RST}")
    print(f"{'═'*65}")
    print(f"  Se corregirán {R}{total_fields} campo(s){RST} en {R}{total_leagues} liga(s){RST}.")
    print(f"  Archivo: {DIM}{LEAGUES_INFO_PATH}{RST}")
    print(f"\n  ¿Sobreescribir leagues_info.json con los IDs de la DB? [s/N]: ", end="")

    resp = input().strip().lower()
    if resp != 's':
        print(f"\n  {DIM}Cancelado. El archivo no fue modificado.{RST}\n")
        return

    applied = apply_fixes(data, pending_fixes)

    with open(LEAGUES_INFO_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"\n  {G}✔  {applied} campo(s) actualizados en leagues_info.json{RST}\n")


def main():
    sport_filter = sys.argv[1:] if len(sys.argv) > 1 else None

    with open(LEAGUES_INFO_PATH, encoding='utf-8') as f:
        data = json.load(f)

    print(f"\n{DIM}Conectando a {DB_HOST}/{DB_NAME}...{RST}")
    print(f"{DIM}Leyendo: {LEAGUES_INFO_PATH}{RST}")

    pending_fixes, data = validate(data, sport_filter)
    confirm_and_save(data, pending_fixes)


if __name__ == "__main__":
    main()
