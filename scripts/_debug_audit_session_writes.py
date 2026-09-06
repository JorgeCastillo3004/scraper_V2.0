#!/usr/bin/env python3
"""READ-ONLY audit of this session's writes. No INSERT/UPDATE/DELETE, no driver.

Audits:
  1) OLD_SEASON tagging (69 matches)
  2) NFL 2026/2027 new season (32 new matches, season=272 total)
  3-6) General DB health post-writes
"""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER,
                       password=DB_PASS, connect_timeout=20)
con.set_session(readonly=True, autocommit=True)
con.set_client_encoding('UTF8')
cur = con.cursor()
cur.execute("SET client_min_messages TO ERROR")  # silence collation WARNING


def q(sql, p=None):
    cur.execute(sql, p or ())
    return cur.fetchall()


def scalar(sql, p=None):
    cur.execute(sql, p or ())
    r = cur.fetchone()
    return r[0] if r else None


NFL_LEAGUE = '1daffbae-2eb6-4fd4-a764-e15c5a0eec82'
NFL_SEASON_NEW = '7b2ebe64-a906-4367-a30e-7be2e0272565'

print("="*78)
print("  AUDIT — session writes (READ-ONLY)")
print("="*78)

# ─────────────────────────────────────────────────────────────────────────────
# 1) OLD_SEASON tagging
# ─────────────────────────────────────────────────────────────────────────────
print("\n########## 1) OLD_SEASON TAGGING ##########")

total_old = scalar("SELECT COUNT(*) FROM match WHERE status='OLD_SEASON'")
print(f"\n[1.1] Total matches status='OLD_SEASON': {total_old}  (expected 69)")

# breakdown by league + season
print("\n[1.2] Breakdown by league / season:")
rows = q("""
  SELECT sp.name AS sport, l.league_name, se.season_name, m.season_id, COUNT(*) AS n
    FROM match m
    JOIN league l  ON l.league_id  = m.league_id
    JOIN sport  sp ON sp.sport_id  = l.sport_id
    LEFT JOIN season se ON se.season_id = m.season_id
   WHERE m.status='OLD_SEASON'
   GROUP BY sp.name, l.league_name, se.season_name, m.season_id
   ORDER BY n DESC
""")
for r in rows:
    print(f"    {r[0]:<14} {str(r[1]):<28} season={str(r[2]):<12} n={r[4]}  (season_id={r[3]})")

# Are any OLD_SEASON in a future date? (should all be past)
fut = scalar("SELECT COUNT(*) FROM match WHERE status='OLD_SEASON' AND match_date >= CURRENT_DATE")
print(f"\n[1.3] OLD_SEASON with match_date >= today (should be 0): {fut}")

# Do all OLD_SEASON have score -1? (premise of the tagging)
notm1 = scalar("""
  SELECT COUNT(DISTINCT m.match_id)
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
   WHERE m.status='OLD_SEASON' AND se.points <> -1
""")
print(f"[1.4] OLD_SEASON matches having ANY score_entity.points<>-1 (expected 0): {notm1}")

# Detail/score untouched: every OLD_SEASON match should still have exactly 2 details
bad_detail = q("""
  SELECT m.match_id, COUNT(md.match_detail_id) AS n
    FROM match m
    LEFT JOIN match_detail md ON md.match_id = m.match_id
   WHERE m.status='OLD_SEASON'
   GROUP BY m.match_id HAVING COUNT(md.match_detail_id) <> 2
""")
print(f"[1.5] OLD_SEASON matches with match_detail count != 2 (expected 0): {len(bad_detail)}")
for r in bad_detail[:10]:
    print(f"        {r[0]} -> {r[1]} details")

# detail without score among OLD_SEASON
nodist = scalar("""
  SELECT COUNT(*) FROM match m
   JOIN match_detail md ON md.match_id=m.match_id
   LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.status='OLD_SEASON' AND se.score_id IS NULL
""")
print(f"[1.6] OLD_SEASON match_detail rows without score_entity (expected 0): {nodist}")

# Over-tagging check: is any of the listed leagues' CURRENT season tagged OLD_SEASON?
# Identify, per affected league, the seasons present and whether the *latest* season
# (by season_start) got tagged.
print("\n[1.7] Over-tagging check — for each affected league, list all its seasons")
print("      and whether each was tagged OLD_SEASON (the latest/current should NOT be):")
aff_leagues = q("""
  SELECT DISTINCT l.league_id, l.league_name
    FROM match m JOIN league l ON l.league_id=m.league_id
   WHERE m.status='OLD_SEASON'
""")
for lid, lname in aff_leagues:
    seasons = q("""
      SELECT se.season_id, se.season_name, se.season_start, se.season_end,
             (SELECT COUNT(*) FROM match m2
               WHERE m2.season_id=se.season_id AND m2.status='OLD_SEASON') AS tagged,
             (SELECT COUNT(*) FROM match m3 WHERE m3.season_id=se.season_id) AS total
        FROM season se
       WHERE se.league_id=%s
       ORDER BY se.season_start DESC NULLS LAST, se.season_name DESC
    """, (lid,))
    print(f"\n    LEAGUE {lname} ({lid}):")
    for i, s in enumerate(seasons):
        flag = "  <-- LATEST" if i == 0 else ""
        warn = "  !!! LATEST SEASON HAS TAGGED MATCHES" if (i == 0 and s[4] > 0) else ""
        print(f"      season={s[1]:<14} start={s[2]} tagged={s[4]:>3}/{s[5]:<3}{flag}{warn}")

# ─────────────────────────────────────────────────────────────────────────────
# 2) NFL new season 2026/2027
# ─────────────────────────────────────────────────────────────────────────────
print("\n\n########## 2) NFL 2026/2027 NEW SEASON ##########")

sea = q("""SELECT season_id, season_name, season_start, season_end, league_id
             FROM season WHERE season_id=%s""", (NFL_SEASON_NEW,))
print(f"\n[2.0] Season row: {sea}")

tot_season = scalar("SELECT COUNT(*) FROM match WHERE season_id=%s", (NFL_SEASON_NEW,))
print(f"[2.1] Total matches in season {NFL_SEASON_NEW[:8]}..: {tot_season}  (expected 272)")

# All matches of this season should belong to NFL league
wrong_league = scalar("""SELECT COUNT(*) FROM match
                          WHERE season_id=%s AND league_id<>%s""",
                      (NFL_SEASON_NEW, NFL_LEAGUE))
print(f"[2.2] Matches in this season NOT in NFL league (expected 0): {wrong_league}")

# Detail cardinality for the whole season (the 32 new + any pre-existing)
bad2 = q("""
  SELECT m.match_id, COUNT(md.match_detail_id) AS n
    FROM match m LEFT JOIN match_detail md ON md.match_id=m.match_id
   WHERE m.season_id=%s
   GROUP BY m.match_id HAVING COUNT(md.match_detail_id) <> 2
""", (NFL_SEASON_NEW,))
print(f"[2.3] Season matches with match_detail count != 2 (expected 0): {len(bad2)}")
for r in bad2[:10]:
    print(f"        {r[0]} -> {r[1]}")

# team_id NOT NULL and distinct between home/away
bad_team = q("""
  SELECT md.match_id,
         SUM(CASE WHEN md.team_id IS NULL THEN 1 ELSE 0 END) AS nulls,
         COUNT(DISTINCT md.team_id) AS distinct_teams,
         COUNT(*) AS n
    FROM match_detail md
    JOIN match m ON m.match_id=md.match_id
   WHERE m.season_id=%s
   GROUP BY md.match_id
  HAVING SUM(CASE WHEN md.team_id IS NULL THEN 1 ELSE 0 END) > 0
      OR COUNT(DISTINCT md.team_id) <> COUNT(*)
""", (NFL_SEASON_NEW,))
print(f"[2.4] Season matches with NULL team_id OR home==away team (expected 0): {len(bad_team)}")
for r in bad_team[:15]:
    print(f"        match={r[0]} nulls={r[1]} distinct={r[2]} n={r[3]}")

# home/visitor flags correct (1 home + 1 visitor)
bad_hv = scalar("""
  SELECT COUNT(*) FROM (
    SELECT md.match_id,
           SUM(CASE WHEN md.home THEN 1 ELSE 0 END) h,
           SUM(CASE WHEN md.visitor THEN 1 ELSE 0 END) v,
           COUNT(*) n
      FROM match_detail md JOIN match m ON m.match_id=md.match_id
     WHERE m.season_id=%s
     GROUP BY md.match_id
  ) t WHERE NOT (n=2 AND h=1 AND v=1)
""", (NFL_SEASON_NEW,))
print(f"[2.5] Season matches not exactly 1 home + 1 visitor (expected 0): {bad_hv}")

# all referenced team_id exist in team
fk_broken = q("""
  SELECT DISTINCT md.team_id
    FROM match_detail md JOIN match m ON m.match_id=md.match_id
    LEFT JOIN team t ON t.team_id=md.team_id
   WHERE m.season_id=%s AND md.team_id IS NOT NULL AND t.team_id IS NULL
""", (NFL_SEASON_NEW,))
print(f"[2.6] Season team_id with no row in team (FK broken, expected 0): {len(fk_broken)}")
for r in fk_broken:
    print(f"        orphan team_id={r[0]}")

# score_entity present for every detail in the season
no_score = scalar("""
  SELECT COUNT(*) FROM match m
   JOIN match_detail md ON md.match_id=m.match_id
   LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.season_id=%s AND se.score_id IS NULL
""", (NFL_SEASON_NEW,))
print(f"[2.7] Season match_detail rows without score_entity (expected 0): {no_score}")

# duplicate matches within the season (exact: name+match_date+start_time)
dups_season = q("""
  SELECT name, match_date, start_time, COUNT(*) n
    FROM match WHERE season_id=%s
   GROUP BY name, match_date, start_time HAVING COUNT(*) > 1
   ORDER BY n DESC
""", (NFL_SEASON_NEW,))
print(f"[2.8] Duplicate matches in season (name+date+start_time) (expected 0): {len(dups_season)}")
for r in dups_season[:15]:
    print(f"        {r[0]!r} {r[1]} {r[2]} x{r[3]}")

# duplicate NFL teams (team_name+sport+country >1) — focus on teams used by this season
print("\n[2.9] Duplicate NFL teams used by this season (team_name+sport_id+country_id >1):")
dup_teams = q("""
  WITH season_teams AS (
    SELECT DISTINCT t.team_name, t.sport_id, t.country_id
      FROM match_detail md
      JOIN match m ON m.match_id=md.match_id
      JOIN team t  ON t.team_id=md.team_id
     WHERE m.season_id=%s
  )
  SELECT t.team_name, t.sport_id, t.country_id, COUNT(*) n,
         array_agg(t.team_id) AS ids
    FROM team t
    JOIN season_teams st
      ON st.team_name=t.team_name AND st.sport_id=t.sport_id
     AND (st.country_id=t.country_id OR (st.country_id IS NULL AND t.country_id IS NULL))
   GROUP BY t.team_name, t.sport_id, t.country_id
  HAVING COUNT(*) > 1
   ORDER BY n DESC
""", (NFL_SEASON_NEW,))
print(f"      Duplicate team groups among this season's teams (expected 0): {len(dup_teams)}")
for r in dup_teams[:30]:
    print(f"        {r[0]!r} sport={r[1]} country={r[2]} x{r[3]} ids={r[4]}")

# how many distinct teams does the season use (NFL should be 32)
ndist_teams = scalar("""
  SELECT COUNT(DISTINCT md.team_id)
    FROM match_detail md JOIN match m ON m.match_id=md.match_id
   WHERE m.season_id=%s
""", (NFL_SEASON_NEW,))
print(f"      Distinct teams used by season (NFL expected 32): {ndist_teams}")

# ─────────────────────────────────────────────────────────────────────────────
# 3-6) GLOBAL HEALTH
# ─────────────────────────────────────────────────────────────────────────────
print("\n\n########## 3-6) GLOBAL HEALTH POST-WRITES ##########")

null_team = scalar("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")
print(f"\n[3] match_detail.team_id NULL total (expected 3 'Great Britain'): {null_team}")
nt = q("""
  SELECT m.match_id, m.name, m.match_date, sp.name AS sport, l.league_name
    FROM match_detail md
    JOIN match m ON m.match_id=md.match_id
    JOIN league l ON l.league_id=m.league_id
    JOIN sport sp ON sp.sport_id=l.sport_id
   WHERE md.team_id IS NULL
   ORDER BY m.match_date
""")
for r in nt[:20]:
    print(f"      {r[0]} | {r[1]!r} | {r[2]} | {r[3]} / {r[4]}")

fk_all = q("""
  SELECT md.match_detail_id, md.match_id, md.team_id
    FROM match_detail md
    LEFT JOIN team t ON t.team_id=md.team_id
   WHERE md.team_id IS NOT NULL AND t.team_id IS NULL
""")
print(f"\n[4] match_detail.team_id non-null but missing in team (FK broken, expected 0): {len(fk_all)}")
for r in fk_all[:20]:
    print(f"      detail={r[0]} match={r[1]} team_id={r[2]}")

dups_all = q("""
  SELECT league_id, name, match_date, start_time, COUNT(*) n
    FROM match
   GROUP BY league_id, name, match_date, start_time HAVING COUNT(*) > 1
   ORDER BY n DESC
""")
print(f"\n[5] EXACT duplicate matches globally (league_id+name+date+start_time) >1: {len(dups_all)}")
for r in dups_all[:40]:
    print(f"      league={r[0]} {r[1]!r} {r[2]} {r[3]} x{r[4]}")

# 6 covered in 2.9; global NFL team dup sweep
print("\n[6] Global NFL-league team duplicate sweep (teams with sport=NFL sport):")
nfl_sport = scalar("SELECT sport_id FROM league WHERE league_id=%s", (NFL_LEAGUE,))
print(f"      NFL sport_id={nfl_sport}")
dup_nfl = q("""
  SELECT team_name, country_id, COUNT(*) n, array_agg(team_id) ids
    FROM team WHERE sport_id=%s
   GROUP BY team_name, country_id HAVING COUNT(*) > 1 ORDER BY n DESC
""", (nfl_sport,))
print(f"      Duplicate team groups in NFL sport (report only): {len(dup_nfl)}")
for r in dup_nfl[:40]:
    print(f"        {r[0]!r} country={r[1]} x{r[2]} ids={r[3]}")

con.close()
print("\n" + "="*78)
print("  DONE (no writes performed)")
print("="*78)
