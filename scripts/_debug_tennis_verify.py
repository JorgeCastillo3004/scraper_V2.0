#!/usr/bin/env python3
"""_debug_tennis_verify.py — READ-ONLY. Verifica que el partido recién creado quedó
completo y con el formato correcto en TODAS las tablas tocadas. NO escribe."""
import os, sys, json, datetime
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT,'src'))
import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

MATCH_ID = json.load(open(os.path.join(ROOT,'tmp','_last_written_match.json')))['match_id']
ORPHAN = '4d563a81-85fd-4ebf-9184-e8d06a5af963'   # player huérfano del 1er intento fallido
con = psycopg2.connect(host=DB_HOST,dbname=DB_NAME,user=DB_USER,password=DB_PASS,connect_timeout=10)
con.set_session(readonly=True); cur=con.cursor()
def q(sql,args=()):
    cur.execute(sql,args); return cur.fetchall()
def cols(table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position",(table,))
    return [r[0] for r in cur.fetchall()]
def show(table, sql, args):
    cs=cols(table); rows=q(sql,args)
    print(f"\n### {table}  ({len(rows)} fila/s)")
    for r in rows:
        for c,v in zip(cs,r): print(f"   {c:20s} = {v!r}")
        print("   " + "-"*30)
    return rows

print(f"=== VERIFICACIÓN match_id = {MATCH_ID} ===")
m = show('match',"SELECT * FROM match WHERE match_id=%s",(MATCH_ID,))
md = show('match_detail',"SELECT * FROM match_detail WHERE match_id=%s",(MATCH_ID,))
det_ids=[r[0] for r in md]; team_ids=[r[4] for r in md]
sc = show('score_entity',"SELECT * FROM score_entity WHERE match_detail_id = ANY(%s)",(det_ids,))
tm = show('team',"SELECT * FROM team WHERE team_id = ANY(%s)",(team_ids,))
lt = show('league_team',"SELECT * FROM league_team WHERE team_id = ANY(%s)",(team_ids,))
tpe = show('team_players_entity',"SELECT * FROM team_players_entity WHERE team_id = ANY(%s)",(team_ids,))
player_ids=[r[3] for r in tpe]
pl = show('player',"SELECT * FROM player WHERE player_id = ANY(%s)",(player_ids,))

# ── chequeos de integridad ─────────────────────────────────────────────────────
print("\n=== CHEQUEOS ===")
issues=[]
def chk(cond,msg):
    print(("  OK  " if cond else "  FAIL")+" "+msg); (None if cond else issues.append(msg))
chk(len(m)==1, "match existe (1 fila)")
chk(len(md)==2, "match_detail = 2")
homes=[r for r in md if r[1] is True]; vis=[r for r in md if r[2] is True]
chk(len(homes)==1 and len(vis)==1, "1 home + 1 visitor")
chk(all(t for t in team_ids), "match_detail.team_id no nulos")
chk(len(sc)==2, "score_entity = 2 (uno por detail)")
chk(all(isinstance(r[1],(int,float)) for r in sc), "points numéricos")
chk(len(tm)==2, "team = 2")
SPORT='31ddfbbd-5141-4b13-87bc-993552727af8'
chk(all(r[5]==SPORT for r in tm), "team.sport_id = UUID Tennis (FK válida)")
chk(len(lt)==2, "league_team = 2 (cada jugador en la liga/season)")
chk(len(tpe)>=2, "team_players_entity ≥ 2 (player↔team)")
chk(len(pl)==2, "player = 2 (los 2 jugadores)")
# FK countries
all_countries=set(r[1] for r in m)|set(r[1] for r in tm)|set(r[1] for r in pl)
all_countries={c for c in all_countries if c}
found=set(r[0] for r in q("SELECT country_id FROM country WHERE country_id = ANY(%s)",(list(all_countries),)))
chk(all_countries<=found, f"country_id de match/team/player existen en country ({len(found)}/{len(all_countries)})")
# formatos
if m:
    name=m[0][4]; status=m[0][13]; stat=m[0][12]
    chk(isinstance(name,str) and len(name)<=128, f"match.name ≤128 ('{name}')")
    chk(status in ('COMPLETED','SCHEDULED','LIVE'), f"status válido ('{status}')")
    chk(stat is None or len(stat)<=4000, "statistic ≤4000")

# ── player huérfano del intento fallido ────────────────────────────────────────
print("\n=== PLAYER HUÉRFANO (1er intento fallido) ===")
orph=q("SELECT player_id,player_name FROM player WHERE player_id=%s",(ORPHAN,))
if orph:
    pid=orph[0][0]
    in_team=q("SELECT 1 FROM team WHERE team_id=%s",(pid,))
    in_tpe=q("SELECT 1 FROM team_players_entity WHERE player_id=%s",(pid,))
    in_md=q("SELECT 1 FROM match_detail WHERE team_id=%s",(pid,))
    print(f"   EXISTE: {orph[0][1]} (player_id={pid})")
    print(f"   ¿tiene team? {bool(in_team)} | ¿team_players? {bool(in_tpe)} | ¿match_detail? {bool(in_md)}")
    print("   → es un player HUÉRFANO (sin team/match). Requiere tu decisión (no se borra sin permiso).")
else:
    print("   No existe (no quedó huérfano).")

con.close()
print("\n=== RESUMEN ===")
print("OK TOTAL — 0 problemas en el partido creado." if not issues else f"{len(issues)} PROBLEMA(S): "+ " | ".join(issues))
