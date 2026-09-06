#!/usr/bin/env python3
"""READ-ONLY audit 2026-06-29. No writes whatsoever."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from api.services.database import get_conn

con = get_conn()
con.set_session(readonly=True, autocommit=True)
cur = con.cursor()
cur.execute("SET client_min_messages TO ERROR")

def q(sql, p=None):
    cur.execute(sql, p)
    return cur.fetchall()

print("== 1. score=-1 en partidos PASADOS (por liga) ==")
rows = q("""
    SELECT sp.name AS sport, co.country_name, l.league_name, COUNT(DISTINCT m.match_id) AS n
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
    JOIN league l ON l.league_id = m.league_id
    JOIN sport sp ON sp.sport_id = l.sport_id
    LEFT JOIN country co ON co.country_id = m.country_id
    WHERE se.points = -1 AND m.match_date < CURRENT_DATE
    GROUP BY sp.name, co.country_name, l.league_name
    ORDER BY n DESC
""")
total = 0
for r in rows:
    print(f"   {r[0]:<18} {str(r[1]):<22} {r[2]:<25} {r[3]}")
    total += r[3]
print(f"   TOTAL partidos pasados score=-1: {total}")

print("\n== 1b. Detalle Bolivia Division Profesional (score=-1 pasados) ==")
rows = q("""
    SELECT m.match_date, l.league_name, m.name, m.match_id
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
    JOIN league l ON l.league_id = m.league_id
    LEFT JOIN country co ON co.country_id = m.country_id
    WHERE se.points = -1 AND m.match_date < CURRENT_DATE
      AND co.country_name = 'BOLIVIA'
    GROUP BY m.match_date, l.league_name, m.name, m.match_id
    ORDER BY m.match_date
""")
for r in rows:
    print(f"   {r[0]}  {r[1]:<22}  {r[2]}")
print(f"   (Bolivia count: {len(rows)})")

print("\n== 1c. TODOS los score=-1 pasados (fecha, liga, equipos) NO-Bolivia ==")
rows = q("""
    SELECT m.match_date, co.country_name, l.league_name, m.name
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
    JOIN league l ON l.league_id = m.league_id
    LEFT JOIN country co ON co.country_id = m.country_id
    WHERE se.points = -1 AND m.match_date < CURRENT_DATE
      AND (co.country_name IS NULL OR co.country_name <> 'BOLIVIA')
    GROUP BY m.match_date, co.country_name, l.league_name, m.name
    ORDER BY m.match_date
""")
for r in rows:
    print(f"   {r[0]}  {str(r[1]):<20} {r[2]:<22}  {r[3]}")

print("\n== 2. Estados parciales/huérfanos ==")
# 2a. score real (>=0) pero status SCHEDULED
n = q("""
    SELECT COUNT(DISTINCT m.match_id)
    FROM match m
    JOIN match_detail md ON md.match_id=m.match_id
    JOIN score_entity se ON se.match_detail_id=md.match_detail_id
    WHERE se.points >= 0 AND m.status = 'SCHEDULED'
""")[0][0]
print(f"   score>=0 con status=SCHEDULED: {n}")

# 2b. distribucion de status
print("   distribucion status match:")
for r in q("SELECT status, COUNT(*) FROM match GROUP BY status ORDER BY 2 DESC"):
    print(f"      {str(r[0]):<14} {r[1]}")

# 2c. match con match_detail != 2
rows = q("""
    SELECT m.match_id, m.name, m.match_date, co.country_name, l.league_name, c.n
    FROM (SELECT match_id, COUNT(*) n FROM match_detail GROUP BY match_id HAVING COUNT(*)<>2) c
    JOIN match m ON m.match_id=c.match_id
    JOIN league l ON l.league_id=m.league_id
    LEFT JOIN country co ON co.country_id=m.country_id
    ORDER BY m.match_date DESC
""")
print(f"\n   match con match_detail != 2: {len(rows)}")
for r in rows:
    print(f"      {r[2]}  {str(r[3]):<10} {r[4]:<22} {r[1]}  (details={r[5]})")

# 2d. match_detail sin score_entity
rows = q("""
    SELECT md.match_detail_id, md.match_id, m.match_date, co.country_name, l.league_name, m.name
    FROM match_detail md
    LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
    JOIN match m ON m.match_id=md.match_id
    JOIN league l ON l.league_id=m.league_id
    LEFT JOIN country co ON co.country_id=m.country_id
    WHERE se.match_detail_id IS NULL
    ORDER BY m.match_date DESC
""")
print(f"\n   match_detail sin score_entity: {len(rows)}")
for r in rows:
    print(f"      {r[2]}  {str(r[3]):<10} {r[4]:<22} {r[5]}")

# 2e. score_entity huerfano (sin match_detail)
n = q("""
    SELECT COUNT(*) FROM score_entity se
    LEFT JOIN match_detail md ON md.match_detail_id=se.match_detail_id
    WHERE md.match_detail_id IS NULL
""")[0][0]
print(f"\n   score_entity huerfano (sin match_detail): {n}")

print("\n== 3. FK rota: match_detail.team_id NULL o inexistente ==")
n_null = q("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")[0][0]
print(f"   team_id NULL: {n_null}")
rows = q("""
    SELECT md.match_detail_id, md.match_id, md.team_id, m.match_date, co.country_name, l.league_name, m.name
    FROM match_detail md
    LEFT JOIN team t ON t.team_id=md.team_id
    JOIN match m ON m.match_id=md.match_id
    JOIN league l ON l.league_id=m.league_id
    LEFT JOIN country co ON co.country_id=m.country_id
    WHERE md.team_id IS NOT NULL AND t.team_id IS NULL
    ORDER BY m.match_date DESC
""")
print(f"   team_id inexistente (FK rota): {len(rows)}")
for r in rows:
    print(f"      md={r[0]} match={r[1]} team_id={r[2]} {r[3]} {r[4]}/{r[5]} {r[6]}")

print("\n== 4. Duplicados ==")
for label, sql in [
    ("sport(name)", "SELECT name FROM sport GROUP BY name HAVING COUNT(*)>1"),
    ("league(country,name,sport)", "SELECT country_id,league_name,sport_id FROM league GROUP BY country_id,league_name,sport_id HAVING COUNT(*)>1"),
    ("country(name)", "SELECT country_name FROM country GROUP BY country_name HAVING COUNT(*)>1"),
    ("team(name,sport,country)", "SELECT team_name,sport_id,country_id FROM team GROUP BY team_name,sport_id,country_id HAVING COUNT(*)>1"),
    ("season(league,name)", "SELECT league_id,season_name FROM season GROUP BY league_id,season_name HAVING COUNT(*)>1"),
    ("match(league,date,name)", "SELECT league_id,match_date,name FROM match GROUP BY league_id,match_date,name HAVING COUNT(*)>1"),
]:
    rows = q(sql)
    print(f"   {label:<30} grupos duplicados: {len(rows)}")
    for r in rows[:5]:
        print(f"        {r}")

print("\n== 5. COMPLETED sanity (status + score real + exactamente 2 detail/score) ==")
# completed con score -1
n = q("""SELECT COUNT(DISTINCT m.match_id) FROM match m
    JOIN match_detail md ON md.match_id=m.match_id
    JOIN score_entity se ON se.match_detail_id=md.match_detail_id
    WHERE m.status IN ('COMPLETED','FINISHED','FINAL') AND se.points = -1""")[0][0]
print(f"   COMPLETED-ish con algun score=-1: {n}")
# completed con != 2 detail
n = q("""SELECT COUNT(*) FROM (
    SELECT m.match_id FROM match m JOIN match_detail md ON md.match_id=m.match_id
    WHERE m.status IN ('COMPLETED','FINISHED','FINAL')
    GROUP BY m.match_id HAVING COUNT(*)<>2) t""")[0][0]
print(f"   COMPLETED-ish con match_detail != 2: {n}")

print("\n== match_date max y rango ==")
print("   ", q("SELECT MIN(match_date), MAX(match_date), CURRENT_DATE FROM match")[0])

con.close()
print("\nDONE (read-only).")
