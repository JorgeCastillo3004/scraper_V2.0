#!/usr/bin/env python3
"""_debug_tennis_schema.py — READ-ONLY. Introspección del esquema de las tablas
que toca la creación de partidos de tenis. NO escribe nada (set_session readonly).
Scratchpad (_debug_) para validar campos obligatorios antes de armar la rama tenis."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER,
                       password=DB_PASS, connect_timeout=10)
con.set_session(readonly=True)  # el servidor RECHAZA cualquier escritura
cur = con.cursor()

TABLES = ['match', 'match_detail', 'score_entity', 'team', 'player',
          'league_team', 'team_players_entity', 'league', 'country', 'season']

for t in TABLES:
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default,
               character_maximum_length
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (t,))
    rows = cur.fetchall()
    if not rows:
        print(f"\n### {t}: (NO EXISTE)")
        continue
    print(f"\n### {t}")
    for name, dtype, nullable, default, maxlen in rows:
        req = 'NOT NULL' if nullable == 'NO' else 'null-ok '
        ln = f"({maxlen})" if maxlen else ''
        dv = f" default={default}" if default else ''
        print(f"   {req}  {name:24s} {dtype}{ln}{dv}")
    # PK
    cur.execute("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
    """, (t,))
    pk = [r[0] for r in cur.fetchall()]
    print(f"   PK: {pk}")

con.close()
print("\n[OK] introspección read-only completada (0 escrituras)")
