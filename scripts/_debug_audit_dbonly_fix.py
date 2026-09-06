#!/usr/bin/env python3
"""READ-ONLY audit of the --db-only NULL team_id repair. No writes, no driver."""
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
con.set_session(readonly=True, autocommit=True)
con.set_client_encoding('UTF8')
cur = con.cursor()
cur.execute("SET client_min_messages TO ERROR")

def q(sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()

MATCHES = {
    'Liga MX (Mexico)': ['eb6dd8be-f63e-4a3c-8008-a05485acc557'],
    'MLS (USA)': ['d7df98fb-29fc-40f9-a6b8-e795ec80594c'],
    'Costa Rica Primera Division': [
        '6b2e245d-ef8f-48bf-af63-16079cdc8aa6', '6d6e7983-bbaa-4aa9-b230-86ac3f80101b',
        'a2613026-2e53-428d-9b1c-1920467f997c', 'a353b25c-2d5f-4ef9-988b-6b87982fe3bb',
        '03faf860-5c94-40c8-aa6f-6f295d04de36', 'b3440e78-9cc4-4ba4-875a-66e9919b84b0',
    ],
}
ALL_IDS = [mid for v in MATCHES.values() for mid in v]

EXPECTED_TEAMS = {
    'Pachuca': 'd965595c', 'Tigres UANL': 'dbc67ccc',
    'Houston Dynamo': '8165bc19', 'Los Angeles FC': '9a0fe8c6',
    'Sporting FC': '1d2fffab', 'San Carlos': '69914b33', 'Guadalupe': '8adb7537',
    'Cartagines': '95c75d2a', 'Alajuelense': 'b82315df', 'Liberia': 'e04de846',
    'Puntarenas FC': 'ddad000f',
}

def parse_teams(name):
    if not name or '~' not in name:
        return (None, None)
    home_raw, _, away = name.partition('~')
    home = home_raw.split('\n')[0].strip()
    return (home, away.strip())

print("="*80)
print("AUDIT: --db-only NULL team_id repair (READ-ONLY)")
print("="*80)

# ---- Per-match verification (1,2,3,4,5) ----
for grp, ids in MATCHES.items():
    print(f"\n##### {grp}")
    for mid in ids:
        mrow = q("""SELECT m.match_id, m.name, m.status, m.match_date,
                           l.league_id, l.league_name, l.sport_id, l.country_id,
                           s.name AS sport, c.country_name
                      FROM match m
                      JOIN league l ON l.league_id=m.league_id
                      JOIN sport s ON s.sport_id=l.sport_id
                      LEFT JOIN country c ON c.country_id=l.country_id
                     WHERE m.match_id=%s""", (mid,))
        if not mrow:
            print(f"  [{mid}] ⚠️ MATCH NOT FOUND")
            continue
        (_, name, status, mdate, league_id, league_name, l_sport, l_country,
         sport, country) = mrow[0]
        home, away = parse_teams(name)
        print(f"\n  match {mid}")
        print(f"    name={name!r}  status={status} date={mdate}")
        print(f"    league={league_name} sport={sport} country={country}")
        print(f"    parsed: home={home!r}  away={away!r}")

        # (1) exactly 2 match_detail rows, both NOT NULL, distinct
        md = q("""SELECT md.team_id, md.match_detail_id, t.team_name,
                         t.sport_id, t.country_id, tc.country_name,
                         md.home, md.visitor
                    FROM match_detail md
                    LEFT JOIN team t ON t.team_id=md.team_id
                    LEFT JOIN country tc ON tc.country_id=t.country_id
                   WHERE md.match_id=%s
                   ORDER BY md.match_detail_id""", (mid,))
        n = len(md)
        tids = [r[0] for r in md]
        nn = [t for t in tids if t is not None]
        ok1 = (n == 2 and len(nn) == 2 and len(set(nn)) == 2)
        print(f"    (1) match_detail rows={n}  team_ids={[str(t)[:8] for t in tids]}  "
              f"-> {'✅' if ok1 else '⚠️'}")
        if n != 2:
            print(f"        ⚠️ expected 2 rows, got {n}")
        if len(nn) != 2:
            print(f"        ⚠️ {n-len(nn)} NULL team_id still present")
        if len(set(nn)) != len(nn):
            print(f"        ⚠️ DUPLICATE/self-match team_id")

        # (2) team_id matches parsed name + sport + country
        for side, tname in (('home', home), ('away', away)):
            tr = q("SELECT team_id, team_name, sport_id, country_id FROM team "
                   "WHERE team_name=%s", (tname,))
            # find which md row corresponds (by team_name match)
            md_match = [r for r in md if r[2] == tname]
            present = bool(md_match)
            sport_ok = country_ok = None
            short = None
            if md_match:
                r = md_match[0]
                short = str(r[0])[:8]
                sport_ok = (r[3] == l_sport)
                country_ok = (r[4] == l_country)
            print(f"    (2) {side}={tname!r}: assigned_team={short} present_in_md={present} "
                  f"sport_ok={sport_ok} country_ok={country_ok} "
                  f"{'✅' if present and sport_ok and country_ok else '⚠️'}")
            # expected uuid prefix
            exp = EXPECTED_TEAMS.get(tname)
            if exp and short and not short.startswith(exp):
                print(f"        ⚠️ expected team_id prefix {exp}, got {short}")

            # (3) league_team link
            if md_match:
                lt = q("SELECT 1 FROM league_team WHERE team_id=%s AND league_id=%s",
                       (md_match[0][0], league_id))
                print(f"    (3) {side} in league_team? {'✅ yes' if lt else '⚠️ MISSING'}")

        # (4) score_entity intact / not orphaned (linked via match_detail_id)
        md_ids = [r[1] for r in md]
        se = q("""SELECT se.score_id, se.match_detail_id, se.points
                    FROM score_entity se
                    JOIN match_detail md ON md.match_detail_id=se.match_detail_id
                   WHERE md.match_id=%s
                   ORDER BY se.match_detail_id""", (mid,))
        # orphan score_entity = match_detail_id not existing
        orph_se = q("""SELECT se.score_id, se.match_detail_id
                         FROM score_entity se
                        WHERE se.match_detail_id IN %s
                          AND NOT EXISTS (SELECT 1 FROM match_detail md
                                          WHERE md.match_detail_id=se.match_detail_id)""",
                    (tuple(md_ids) if md_ids else ('',),)) if md_ids else []
        print(f"    (4) score_entity rows (via match_detail)={len(se)}  "
              f"orphans={'⚠️ '+str(orph_se) if orph_se else '✅ none'}")
        # duplicate score_entity per match_detail
        dup_se = q("""SELECT match_detail_id, COUNT(*) FROM score_entity
                       WHERE match_detail_id IN %s GROUP BY match_detail_id
                       HAVING COUNT(*)>1""", (tuple(md_ids),)) if md_ids else []
        if dup_se:
            print(f"        ⚠️ duplicate score_entity per detail: {dup_se}")

        # (5) duplicate match_detail rows for same (match,team)
        dup = q("""SELECT team_id, COUNT(*) FROM match_detail
                    WHERE match_id=%s AND team_id IS NOT NULL
                    GROUP BY team_id HAVING COUNT(*)>1""", (mid,))
        print(f"    (5) duplicate match_detail (same team): "
              f"{'⚠️ '+str(dup) if dup else '✅ none'}")

# ---- GLOBAL HEALTH (6,7,8) ----
print("\n" + "="*80)
print("GLOBAL HEALTH")
print("="*80)

# (6) total NULL team_id + breakdown
tot = q("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")[0][0]
print(f"\n(6) match_detail.team_id IS NULL total: {tot}")
brk = q("""SELECT s.name AS sport, l.league_name, c.country_name, COUNT(*) AS n
             FROM match_detail md
             JOIN match m ON m.match_id=md.match_id
             JOIN league l ON l.league_id=m.league_id
             JOIN sport s ON s.sport_id=l.sport_id
             LEFT JOIN country c ON c.country_id=l.country_id
            WHERE md.team_id IS NULL
            GROUP BY s.name, l.league_name, c.country_name
            ORDER BY n DESC, s.name, l.league_name""")
print(f"    breakdown ({len(brk)} league groups)  [sport / league / country / n]:")
for r in brk:
    print(f"      n={r[3]:<5} {r[0]:<14} {r[1]:<42} {r[2]}")

# (7) match_detail with team_id NOT in team (real broken FK)
bad_fk = q("""SELECT COUNT(*) FROM match_detail md
               WHERE md.team_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM team t WHERE t.team_id=md.team_id)""")[0][0]
print(f"\n(7) match_detail.team_id pointing to non-existent team (broken FK): {bad_fk}")
if bad_fk:
    ex = q("""SELECT md.match_id, md.team_id FROM match_detail md
               WHERE md.team_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM team t WHERE t.team_id=md.team_id)
               LIMIT 10""")
    for r in ex:
        print(f"      match={r[0]} team_id={r[1]}")

# (8) self-match: same team_id on both sides of a match globally
self_m2 = q("""SELECT COUNT(*) FROM (
                SELECT match_id FROM match_detail WHERE team_id IS NOT NULL
                GROUP BY match_id
                HAVING COUNT(DISTINCT team_id)=1 AND COUNT(*)>=2
              ) y""")[0][0]
print(f"\n(8) matches with >=2 detail rows ALL pointing to the SAME team (auto-match): {self_m2}")
if self_m2:
    ex = q("""SELECT md.match_id, md.team_id, m.name FROM match_detail md
               JOIN match m ON m.match_id=md.match_id
               WHERE md.team_id IS NOT NULL
               AND md.match_id IN (
                 SELECT match_id FROM match_detail WHERE team_id IS NOT NULL
                 GROUP BY match_id HAVING COUNT(DISTINCT team_id)=1 AND COUNT(*)>=2)
               GROUP BY md.match_id, md.team_id, m.name LIMIT 10""")
    for r in ex:
        print(f"      match={r[0]} team={str(r[1])[:8]} name={r[2]!r}")

con.close()
print("\nDONE (read-only).")
