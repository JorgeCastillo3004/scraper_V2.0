#!/usr/bin/env python3
"""Auditoría READ-ONLY puntual (9 puntos). Solo SELECT. No modifica nada."""
import os, sys, warnings
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
con.set_session(readonly=True, autocommit=True)
cur = con.cursor()

def q(sql, p=None):
    cur.execute(sql, p)
    return cur.fetchall()

def scalar(sql, p=None):
    cur.execute(sql, p); r = cur.fetchone(); return r[0] if r else None

def H(t): print("\n" + "="*70 + f"\n{t}\n" + "="*70)

# 1. FK rotas
H("1. FK ROTAS (esperado 0, salvo match.season_id huerfana ~2285)")
print("md.team_id -> team:        ", scalar("""
  SELECT COUNT(*) FROM match_detail md LEFT JOIN team t ON t.team_id=md.team_id
  WHERE md.team_id IS NOT NULL AND t.team_id IS NULL"""))
print("md.team_id IS NULL:        ", scalar("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL"))
print("match.league_id -> league: ", scalar("""
  SELECT COUNT(*) FROM match m LEFT JOIN league l ON l.league_id=m.league_id
  WHERE l.league_id IS NULL"""))
print("score.match_detail_id->md: ", scalar("""
  SELECT COUNT(*) FROM score_entity se LEFT JOIN match_detail md ON md.match_detail_id=se.match_detail_id
  WHERE md.match_detail_id IS NULL"""))
print("md.match_id -> match:      ", scalar("""
  SELECT COUNT(*) FROM match_detail md LEFT JOIN match m ON m.match_id=md.match_id
  WHERE m.match_id IS NULL"""))
orf = scalar("""SELECT COUNT(*) FROM match m LEFT JOIN season s ON s.season_id=m.season_id
  WHERE m.season_id IS NULL OR s.season_id IS NULL""")
print("match.season_id huerfana:  ", orf)
print("  desglose por liga (top 15):")
for r in q("""
  SELECT l.league_name, sp.name AS sport, m.season_id, COUNT(*) n
  FROM match m
  LEFT JOIN season s ON s.season_id=m.season_id
  LEFT JOIN league l ON l.league_id=m.league_id
  LEFT JOIN sport sp ON sp.sport_id=l.sport_id
  WHERE m.season_id IS NULL OR s.season_id IS NULL
  GROUP BY l.league_name, sp.name, m.season_id ORDER BY n DESC LIMIT 15"""):
    print("   ", r)

# 2. Pasados con score=-1
H("2. PASADOS con score_entity.points=-1 (esperado 0)")
n = scalar("""
  SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE se.points=-1 AND m.match_date < CURRENT_DATE""")
print("matches pasados con -1:", n)
if n:
    for r in q("""
      SELECT m.match_id, m.name, m.match_date, m.status FROM match m
      JOIN match_detail md ON md.match_id=m.match_id
      JOIN score_entity se ON se.match_detail_id=md.match_detail_id
      WHERE se.points=-1 AND m.match_date < CURRENT_DATE
      GROUP BY m.match_id,m.name,m.match_date,m.status ORDER BY m.match_date DESC LIMIT 20"""):
        print("   ", r)

# 3. COMPLETED sin score + match_detail != 2
H("3a. COMPLETED sin score_entity (detail_no_score en COMPLETED)")
print("match_detail (status COMPLETED) sin score:", scalar("""
  SELECT COUNT(*) FROM match_detail md
  JOIN match m ON m.match_id=md.match_id
  LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='COMPLETED' AND se.match_detail_id IS NULL"""))
print("matches COMPLETED con algun detail sin score:", scalar("""
  SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='COMPLETED' AND se.match_detail_id IS NULL"""))
H("3b. match con match_detail != 2 (F1 con 22 es NORMAL)")
print("total matches con detail!=2:", scalar("""
  SELECT COUNT(*) FROM (SELECT match_id FROM match_detail GROUP BY match_id HAVING COUNT(*)<>2) t"""))
print("  desglose por sport/n (top 20):")
for r in q("""
  SELECT sp.name AS sport, t.n AS detalles, COUNT(*) AS matches
  FROM (SELECT match_id, COUNT(*) n FROM match_detail GROUP BY match_id HAVING COUNT(*)<>2) t
  JOIN match m ON m.match_id=t.match_id
  LEFT JOIN league l ON l.league_id=m.league_id
  LEFT JOIN sport sp ON sp.sport_id=l.sport_id
  GROUP BY sp.name, t.n ORDER BY matches DESC LIMIT 20"""):
    print("   ", r)

# 4. Auto-partidos
H("4. AUTO-PARTIDOS (home y visitor mismo team_id)")
n = scalar("""
  SELECT COUNT(*) FROM (
    SELECT match_id FROM match_detail WHERE team_id IS NOT NULL
    GROUP BY match_id, team_id HAVING COUNT(DISTINCT (home,visitor))>1 OR COUNT(*)>1
  ) t""")
# mejor: mismo team en 2 detalles distintos del mismo match
n2 = scalar("""
  SELECT COUNT(DISTINCT a.match_id)
  FROM match_detail a JOIN match_detail b
    ON a.match_id=b.match_id AND a.team_id=b.team_id AND a.match_detail_id<>b.match_detail_id
  WHERE a.team_id IS NOT NULL""")
print("matches con mismo team en 2 detalles:", n2)
if n2:
    for r in q("""
      SELECT DISTINCT a.match_id, a.team_id, m.name, m.match_date
      FROM match_detail a JOIN match_detail b
        ON a.match_id=b.match_id AND a.team_id=b.team_id AND a.match_detail_id<>b.match_detail_id
      JOIN match m ON m.match_id=a.match_id
      WHERE a.team_id IS NOT NULL ORDER BY m.match_date DESC LIMIT 20"""):
        print("   ", r)

# 5. Duplicados exactos
H("5. DUPLICADOS EXACTOS (league_id + name + match_date + start_time)")
n = scalar("""
  SELECT COUNT(*) FROM (
    SELECT league_id,name,match_date,start_time FROM match
    GROUP BY league_id,name,match_date,start_time HAVING COUNT(*)>1) t""")
print("grupos duplicados:", n)
tot = scalar("""
  SELECT COALESCE(SUM(c-1),0) FROM (
    SELECT COUNT(*) c FROM match
    GROUP BY league_id,name,match_date,start_time HAVING COUNT(*)>1) t""")
print("filas excedentes (total - 1 por grupo):", tot)
if n:
    for r in q("""
      SELECT l.league_name, m.name, m.match_date, m.start_time, COUNT(*) c
      FROM match m LEFT JOIN league l ON l.league_id=m.league_id
      GROUP BY l.league_name, m.name, m.match_date, m.start_time, m.league_id
      HAVING COUNT(*)>1 ORDER BY c DESC LIMIT 20"""):
        print("   ", r)

# 6. OLD_SEASON
H("6. OLD_SEASON (esperado ~69, ninguno con score=-1)")
print("total OLD_SEASON:", scalar("SELECT COUNT(*) FROM match WHERE status='OLD_SEASON'"))
print("OLD_SEASON con score=-1:", scalar("""
  SELECT COUNT(DISTINCT m.match_id) FROM match m
  JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='OLD_SEASON' AND se.points=-1"""))

# 7. Status anomalos
H("7. STATUS fuera de {SCHEDULED,COMPLETED,LIVE,OLD_SEASON}")
for r in q("SELECT status, COUNT(*) FROM match GROUP BY status ORDER BY COUNT(*) DESC"):
    print("   ", r)

# 8. Atascados en LIVE
H("8. LIVE con match_date < hoy (atascados)")
n = scalar("SELECT COUNT(*) FROM match WHERE status='LIVE' AND match_date < CURRENT_DATE")
print("atascados:", n)
for r in q("""
  SELECT m.match_id, l.league_name, m.name, m.match_date, m.start_time
  FROM match m LEFT JOIN league l ON l.league_id=m.league_id
  WHERE m.status='LIVE' AND m.match_date < CURRENT_DATE
  ORDER BY m.match_date ASC LIMIT 40"""):
    print("   ", r)

# 9. World Cup consistencia entre copias
H("9. WORLD CUP - copias COMPLETED con mismo score?")
# Ligas World Cup de football
wc = q("""
  SELECT l.league_id, l.league_name, c.country_name FROM league l
  LEFT JOIN sport sp ON sp.sport_id=l.sport_id
  LEFT JOIN country c ON c.country_id=l.country_id
  WHERE l.league_name ILIKE '%World Cup%' AND sp.name ILIKE 'football'""")
print("ligas World Cup football:", len(wc))
for r in wc: print("   ", r)
# Muestra de partidos jugados agrupados por name+match_date, ver si scores difieren entre copias
print("\nPartidos WC jugados, consistencia de score entre copias (top 15 por name/fecha):")
rows = q("""
  WITH wc_leagues AS (
    SELECT l.league_id FROM league l
    LEFT JOIN sport sp ON sp.sport_id=l.sport_id
    WHERE l.league_name ILIKE '%World Cup%' AND sp.name ILIKE 'football'
  ),
  wc_matches AS (
    SELECT m.match_id, m.name, m.match_date, m.status
    FROM match m WHERE m.league_id IN (SELECT league_id FROM wc_leagues)
      AND m.match_date < CURRENT_DATE
  ),
  scored AS (
    SELECT wm.name, wm.match_date,
           STRING_AGG(DISTINCT wm.status, ',') AS statuses,
           COUNT(DISTINCT wm.match_id) AS copias,
           STRING_AGG(DISTINCT
             (SELECT CONCAT(MAX(CASE WHEN md.home THEN se.points END),'-',
                            MAX(CASE WHEN md.visitor THEN se.points END))
              FROM match_detail md JOIN score_entity se ON se.match_detail_id=md.match_detail_id
              WHERE md.match_id=wm.match_id), ' | ') AS scores
    FROM wc_matches wm
    GROUP BY wm.name, wm.match_date
  )
  SELECT name, match_date, copias, statuses, scores FROM scored
  ORDER BY match_date DESC LIMIT 15""")
for r in rows:
    name, md_date, copias, statuses, scores = r
    flag = ""
    if scores and '|' in (scores or ""): flag += " <SCORE-DISTINTO>"
    if statuses and ',' in (statuses or ""): flag += " <STATUS-MIXTO>"
    print(f"   {md_date} | copias={copias} | status={statuses} | score={scores}{flag}")

# resumen consistencia WC
print("\nResumen WC (partidos jugados):")
print("  grupos name/fecha con score distinto entre copias:", scalar("""
  WITH wc_leagues AS (
    SELECT l.league_id FROM league l LEFT JOIN sport sp ON sp.sport_id=l.sport_id
    WHERE l.league_name ILIKE '%World Cup%' AND sp.name ILIKE 'football'),
  per_match AS (
    SELECT m.match_id, m.name, m.match_date,
      (SELECT CONCAT(MAX(CASE WHEN md.home THEN se.points END),'-',MAX(CASE WHEN md.visitor THEN se.points END))
       FROM match_detail md JOIN score_entity se ON se.match_detail_id=md.match_detail_id
       WHERE md.match_id=m.match_id) sc
    FROM match m WHERE m.league_id IN (SELECT league_id FROM wc_leagues) AND m.match_date<CURRENT_DATE)
  SELECT COUNT(*) FROM (
    SELECT name,match_date FROM per_match GROUP BY name,match_date
    HAVING COUNT(DISTINCT sc)>1) t"""))
print("  grupos name/fecha con status mixto entre copias:", scalar("""
  WITH wc_leagues AS (
    SELECT l.league_id FROM league l LEFT JOIN sport sp ON sp.sport_id=l.sport_id
    WHERE l.league_name ILIKE '%World Cup%' AND sp.name ILIKE 'football')
  SELECT COUNT(*) FROM (
    SELECT name,match_date FROM match
    WHERE league_id IN (SELECT league_id FROM wc_leagues) AND match_date<CURRENT_DATE
    GROUP BY name,match_date HAVING COUNT(DISTINCT status)>1) t"""))

con.close()
print("\n[done] read-only, sin cambios.")
