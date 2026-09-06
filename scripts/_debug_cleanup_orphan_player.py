#!/usr/bin/env python3
"""Borra SOLO el player huérfano 4d563a81 (1er intento fallido). Scope exacto por ID.
Re-verifica que esté huérfano ANTES de borrar. NO toca nada más."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'src'))
import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
ORPHAN = '4d563a81-85fd-4ebf-9184-e8d06a5af963'
con = psycopg2.connect(host=DB_HOST,dbname=DB_NAME,user=DB_USER,password=DB_PASS,connect_timeout=10)
cur = con.cursor()
def one(sql,a=()): cur.execute(sql,a); return cur.fetchone()
row = one("SELECT player_id,player_name FROM player WHERE player_id=%s",(ORPHAN,))
if not row:
    print("No existe (ya no está). Nada que borrar."); sys.exit(0)
# GUARDA: confirmar que NO está referenciado en NINGÚN lado
refs = {
 'team(team_id)':        one("SELECT 1 FROM team WHERE team_id=%s",(ORPHAN,)),
 'team_players_entity':  one("SELECT 1 FROM team_players_entity WHERE player_id=%s",(ORPHAN,)),
 'match_detail(team_id)':one("SELECT 1 FROM match_detail WHERE team_id=%s",(ORPHAN,)),
 'league_team(team_id)': one("SELECT 1 FROM league_team WHERE team_id=%s",(ORPHAN,)),
}
print(f"Huérfano: {row[1]} ({ORPHAN})")
for k,v in refs.items(): print(f"   ref {k}: {bool(v)}")
if any(refs.values()):
    print("[ABORT] Tiene referencias — NO se borra."); sys.exit(1)
cur.execute("DELETE FROM player WHERE player_id=%s",(ORPHAN,))
print(f"DELETE player → filas afectadas: {cur.rowcount}")
con.commit()
# verificación post
gone = one("SELECT 1 FROM player WHERE player_id=%s",(ORPHAN,)) is None
print("Verificación: huérfano eliminado =", gone)
con.close()
