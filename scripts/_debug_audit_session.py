#!/usr/bin/env python3
"""READ-ONLY session audit. No writes, no driver. set_session(readonly=True)."""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'src'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
con.set_session(readonly=True, autocommit=True)
con.set_client_encoding('UTF8')
cur = con.cursor()
cur.execute("SET client_min_messages TO ERROR")

def q(sql, p=None):
    cur.execute(sql, p or ()); return cur.fetchall()
def s(sql, p=None):
    cur.execute(sql, p or ()); r = cur.fetchone(); return r[0] if r else None

FW = '2e7ee992-42e9-4347-927e-a2bc27e08027'  # FOOTBALL WORLD World Cup
BW = 'd2171201-3062-4757-9b57-4e46e723bc0f'  # Basketball World Cup
BOL = '070d6690-9fb3-446a-9eda-d3fafb7911c2'  # FOOTBALL BOLIVIA Division Profesional

print("="*78)
print("DB:", DB_HOST, "/", DB_NAME, "  (read-only)")
print("="*78)

# ── 1. FOOTBALL WORLD World Cup borrado de 64 ────────────────────────────────
print("\n### 1. FOOTBALL WORLD World Cup (league 2e7e...027) — post-borrado 64")
n_fw = s("SELECT COUNT(*) FROM match WHERE league_id=%s", (FW,))
print(f"  matches restantes en la liga: {n_fw}")
# scores -1 remanentes en esa liga
fw_minus = s("""SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.league_id=%s AND se.points=-1""", (FW,))
print(f"  matches con score -1 remanentes: {fw_minus}")
# huérfanos globales: match_detail apuntando a match inexistente
md_orphan = s("""SELECT COUNT(*) FROM match_detail md
  LEFT JOIN match m ON m.match_id=md.match_id WHERE m.match_id IS NULL""")
print(f"  match_detail huérfanos GLOBAL (match_id inexistente): {md_orphan}")
# score_entity apuntando a match_detail inexistente
se_orphan = s("""SELECT COUNT(*) FROM score_entity se
  LEFT JOIN match_detail md ON md.match_detail_id=se.match_detail_id
  WHERE md.match_detail_id IS NULL""")
print(f"  score_entity huérfanos GLOBAL (match_detail inexistente): {se_orphan}")

# ── Basketball World Cup intacta ─────────────────────────────────────────────
print("\n### 1b. Basketball World Cup (league d217...c0f) — debe estar INTACTA")
n_bw = s("SELECT COUNT(*) FROM match WHERE league_id=%s", (BW,))
md_bw = s("""SELECT COUNT(*) FROM match_detail md JOIN match m ON m.match_id=md.match_id
  WHERE m.league_id=%s""", (BW,))
se_bw = s("""SELECT COUNT(*) FROM score_entity se JOIN match_detail md ON md.match_detail_id=se.match_detail_id
  JOIN match m ON m.match_id=md.match_id WHERE m.league_id=%s""", (BW,))
bw_minus = s("""SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.league_id=%s AND se.points=-1""", (BW,))
print(f"  matches={n_bw}  match_detail={md_bw}  score_entity={se_bw}  (score-1 dentro: {bw_minus})")
lname = q("SELECT league_name FROM league WHERE league_id=%s", (BW,))
print(f"  liga existe: {bool(lname)}  name={lname[0][0] if lname else None}")

# ── 2. FOOTBALL BOLIVIA Division Profesional borrado de 21 ───────────────────
print("\n### 2. FOOTBALL BOLIVIA Division Profesional (070d...11c2) — post-borrado 21")
n_bol = s("SELECT COUNT(*) FROM match WHERE league_id=%s", (BOL,))
# ghosts Jun 3-15
bol_ghost = s("""SELECT COUNT(*) FROM match WHERE league_id=%s
  AND match_date BETWEEN '2026-06-03' AND '2026-06-15'""", (BOL,))
print(f"  matches restantes en Bolivia Div Prof: {n_bol}")
print(f"  matches en rango Jun 3-15 (fantasmas esperado 0... verificar): {bol_ghost}")
bol_ghost_rows = q("""SELECT m.match_id, m.name, m.match_date, m.status FROM match m
  WHERE m.league_id=%s AND m.match_date BETWEEN '2026-06-03' AND '2026-06-15'
  ORDER BY m.match_date""", (BOL,))
for r in bol_ghost_rows[:25]:
    print(f"     {r[0]} | {r[1]!r} | {r[2]} | {r[3]}")

# ── 3. OLD_SEASON ────────────────────────────────────────────────────────────
print("\n### 3. Etiquetado OLD_SEASON")
n_old = s("SELECT COUNT(*) FROM match WHERE status='OLD_SEASON'")
print(f"  matches con status='OLD_SEASON': {n_old}  (esperado 69)")
# de esos, cuántos tienen score_entity -1
old_minus = s("""SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='OLD_SEASON' AND se.points=-1""")
print(f"  de esos OLD_SEASON, con score_entity.points=-1: {old_minus}  (esperado 0)")
# distribución de puntos para esos 69
dist = q("""SELECT se.points, COUNT(*) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='OLD_SEASON' GROUP BY se.points ORDER BY se.points""")
print("  distribución score_entity.points de OLD_SEASON:", [(int(p), n) for p, n in dist])
# count match_detail por esos matches (no debió tocarse: deben ser 2 c/u)
old_md = q("""SELECT cnt, COUNT(*) FROM (
  SELECT m.match_id, COUNT(md.match_detail_id) cnt FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  WHERE m.status='OLD_SEASON' GROUP BY m.match_id) t GROUP BY cnt ORDER BY cnt""")
print("  match_detail por match OLD_SEASON (cnt->#matches):", [(int(c), n) for c, n in old_md])

# ── 4. FK rotas ──────────────────────────────────────────────────────────────
print("\n### 4. FK rotas (esperado 0 las 4 primeras)")
fk_team = s("""SELECT COUNT(*) FROM match_detail md LEFT JOIN team t ON t.team_id=md.team_id
  WHERE md.team_id IS NOT NULL AND t.team_id IS NULL""")
fk_team_null = s("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")
fk_league = s("""SELECT COUNT(*) FROM match m LEFT JOIN league l ON l.league_id=m.league_id
  WHERE l.league_id IS NULL""")
fk_se_md = s("""SELECT COUNT(*) FROM score_entity se LEFT JOIN match_detail md ON md.match_detail_id=se.match_detail_id
  WHERE md.match_detail_id IS NULL""")
fk_md_match = s("""SELECT COUNT(*) FROM match_detail md LEFT JOIN match m ON m.match_id=md.match_id
  WHERE m.match_id IS NULL""")
print(f"  match_detail.team_id -> team (rota, team_id NOT NULL): {fk_team}")
print(f"  match_detail.team_id IS NULL (FK rota tipo NULL):      {fk_team_null}")
print(f"  match.league_id -> league:                             {fk_league}")
print(f"  score_entity.match_detail_id -> match_detail:          {fk_se_md}")
print(f"  match_detail.match_id -> match:                        {fk_md_match}")

# season huérfana
print("\n  match.season_id -> season (season huérfana, esperado ~2285):")
fk_season = s("""SELECT COUNT(*) FROM match m
  WHERE m.season_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM season se WHERE se.season_id=m.season_id)""")
fk_season_null = s("SELECT COUNT(*) FROM match WHERE season_id IS NULL")
print(f"    total matches con season_id huérfano: {fk_season}")
print(f"    matches con season_id NULL:           {fk_season_null}")
orph = q("""SELECT s.name sport, l.league_name, m.season_id, COUNT(*) n FROM match m
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  WHERE m.season_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM season se WHERE se.season_id=m.season_id)
  GROUP BY s.name, l.league_name, m.season_id ORDER BY n DESC""")
print(f"    desglose por (sport,liga,season): {len(orph)} grupos. Top 25:")
for r in orph[:25]:
    print(f"      {r[0]:<14} | {r[1]:<32} | season={r[2]} | n={r[3]}")
# por sport agregado
by_sport = {}
for r in orph:
    by_sport[r[0]] = by_sport.get(r[0], 0) + r[3]
print("    agregado por deporte:", sorted(by_sport.items(), key=lambda x:-x[1]))

# ── 5. matches con match_detail != 2 ─────────────────────────────────────────
print("\n### 5. Matches con match_detail != 2")
nb = q("""SELECT m.match_id, m.name, m.match_date, m.status, s.name sport, l.league_name, t.n
  FROM (SELECT match_id, COUNT(*) n FROM match_detail GROUP BY match_id HAVING COUNT(*)<>2) t
  JOIN match m ON m.match_id=t.match_id
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  ORDER BY t.n DESC""")
print(f"  total matches con detail!=2: {len(nb)}")
for r in nb:
    print(f"    n={r[6]} | {r[4]} | {r[5]} | {r[1]!r} | {r[2]} | {r[3]} | {r[0]}")

# ── 6. match_detail sin score_entity ─────────────────────────────────────────
print("\n### 6. match_detail sin score_entity")
md_no_se = s("""SELECT COUNT(*) FROM match_detail md
  LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE se.match_detail_id IS NULL""")
matches_no_se = s("""SELECT COUNT(DISTINCT md.match_id) FROM match_detail md
  LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE se.match_detail_id IS NULL""")
print(f"  match_detail filas sin score_entity: {md_no_se}  (matches afectados: {matches_no_se})")
by_status = q("""SELECT m.status, COUNT(DISTINCT m.match_id) FROM match_detail md
  LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  JOIN match m ON m.match_id=md.match_id
  WHERE se.match_detail_id IS NULL GROUP BY m.status ORDER BY 2 DESC""")
print("  por status:", [(r[0], r[1]) for r in by_status])

# ── 7. partidos pasados con score -1 ─────────────────────────────────────────
print("\n### 7. Partidos PASADOS con score_entity.points=-1")
past_minus = q("""SELECT m.match_id, m.name, m.match_date, m.status, s.name, l.league_name
  FROM match m JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  WHERE se.points=-1 AND m.match_date < CURRENT_DATE
  GROUP BY m.match_id, m.name, m.match_date, m.status, s.name, l.league_name
  ORDER BY m.match_date DESC""")
print(f"  total matches pasados con score -1: {len(past_minus)}  (esperado 0)")
for r in past_minus[:40]:
    print(f"    {r[2]} | {r[3]:<12} | {r[4]:<12} | {r[5]:<28} | {r[1]!r} | {r[0]}")
if len(past_minus) > 40:
    print(f"    ... (+{len(past_minus)-40} más)")
# por liga
if past_minus:
    by_lg = {}
    for r in past_minus:
        by_lg[(r[4], r[5])] = by_lg.get((r[4], r[5]), 0) + 1
    print("  por liga:", sorted(by_lg.items(), key=lambda x:-x[1])[:20])

# ── 8. duplicados exactos ────────────────────────────────────────────────────
print("\n### 8. Partidos duplicados EXACTOS (league_id+name+match_date+start_time)")
# detectar columna start_time
cols = [c[0] for c in q("""SELECT column_name FROM information_schema.columns
  WHERE table_name='match'""")]
has_start = 'start_time' in cols
print(f"  columna start_time existe: {has_start}  (cols match: {cols})")
if has_start:
    dups = q("""SELECT league_id, name, match_date, start_time, COUNT(*) n
      FROM match GROUP BY league_id, name, match_date, start_time
      HAVING COUNT(*)>1 ORDER BY n DESC""")
else:
    dups = q("""SELECT league_id, name, match_date, COUNT(*) n
      FROM match GROUP BY league_id, name, match_date
      HAVING COUNT(*)>1 ORDER BY n DESC""")
print(f"  grupos duplicados exactos: {len(dups)}")
for r in dups[:30]:
    print(f"    n={r[-1]} | league={r[0]} | {r[1]!r} | {r[2]} | start={r[3] if has_start else '(n/a)'}")

print("\n" + "="*78)
print("FIN AUDITORÍA (no se ejecutó ninguna escritura)")
con.close()
