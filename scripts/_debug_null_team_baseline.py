#!/usr/bin/env python3
"""READ-ONLY baseline audit of match_detail.team_id NULL. No writes, no driver."""
import sys, json
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

out = {}

# 1) Distinct matches with a NULL team_id in match_detail, with league context.
rows = q("""
  SELECT DISTINCT m.match_id, m.name, m.match_date, m.status, m.season_id,
         l.league_id, l.league_name, l.sport_id, l.country_id,
         s.name AS sport_name, c.country_name,
         (m.season_id IS NULL) AS season_is_null,
         EXISTS(SELECT 1 FROM season se WHERE se.season_id = m.season_id) AS season_exists
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id AND md.team_id IS NULL
    JOIN league l ON l.league_id = m.league_id
    JOIN sport  s ON s.sport_id  = l.sport_id
    LEFT JOIN country c ON c.country_id = l.country_id
   ORDER BY s.name, l.league_name, m.match_date
""")
cols = ['match_id','name','match_date','status','season_id','league_id',
        'league_name','sport_id','country_id','sport_name','country_name',
        'season_is_null','season_exists']
nulls = [dict(zip(cols, r)) for r in rows]
print(f"### TOTAL distinct matches with >=1 NULL team_id detail: {len(nulls)}")

# 2) For each, parse home/visitor and check team existence + league_team link.
def parse_teams(name):
    if not name or '~' not in name:
        return (None, None)
    home_raw, _, away = name.partition('~')
    # home may contain a trailing score after a newline
    home = home_raw.split('\n')[0].strip()
    return (home, away.strip())

for m in nulls:
    home, away = parse_teams(m['name'])
    m['home'] = home; m['away'] = away
    cause = None
    detail = {}
    for side, tname in (('home', home), ('away', away)):
        info = {'name': tname}
        if not tname:
            info['team_exists'] = None
            info['linked'] = None
            detail[side] = info
            continue
        # placeholder detection
        ph = any(tname.lower().startswith(p) for p in
                 ('winner ', 'loser ', 'group ', 'tbd', 'to be', 'qualifier', 'runner-up',
                  '1st ', '2nd ', '3rd ', 'play-off', 'playoff', 'preliminary'))
        info['placeholder'] = ph
        # team exists by name + sport + country of league
        tids = q("""SELECT team_id FROM team
                     WHERE team_name ILIKE %s AND sport_id = %s
                       AND (country_id = %s OR %s IS NULL)""",
                 (tname, m['sport_id'], m['country_id'], m['country_id']))
        info['team_ids'] = [t[0] for t in tids]
        info['team_exists'] = len(tids) > 0
        # also try without country restriction (broader)
        tids2 = q("SELECT team_id FROM team WHERE team_name ILIKE %s AND sport_id = %s",
                  (tname, m['sport_id']))
        info['team_ids_any_country'] = [t[0] for t in tids2]
        # linked in league_team for this league+season?
        linked = []
        for tid in info['team_ids_any_country']:
            lt = q("""SELECT 1 FROM league_team
                       WHERE team_id=%s AND league_id=%s
                         AND (season_id = %s OR %s IS NULL)""",
                   (tid, m['league_id'], m['season_id'], m['season_id']))
            if lt: linked.append(tid)
        info['linked_team_ids'] = linked
        info['linked'] = len(linked) > 0
        detail[side] = info
    m['parsed'] = detail

# classify
def classify(m):
    d = m['parsed']
    sides = [s for s in ('home','away') if d.get(s) and d[s].get('name')]
    # placeholder/scheduled future
    if m['status'] in ('SCHEDULED','POSTPONED','CANCELED') and any(d[s].get('placeholder') for s in sides):
        return 'd'
    any_placeholder = any(d[s].get('placeholder') for s in sides)
    if any_placeholder and m['status'] != 'COMPLETED':
        return 'd'
    # team inexistente
    missing = [s for s in sides if not d[s].get('team_ids_any_country')]
    if missing:
        return 'a'
    # team exists but not linked for this season
    notlinked = [s for s in sides if d[s].get('team_ids_any_country') and not d[s].get('linked')]
    if notlinked:
        return 'b'
    return 'b'  # exists+something off; default to enlazar review

for m in nulls:
    m['cause'] = classify(m)
    m['orphan_season'] = (not m['season_exists']) and (not m['season_is_null'])

# print per-league table
from collections import defaultdict
byleague = defaultdict(list)
for m in nulls:
    byleague[(m['sport_name'], m['league_name'])].append(m)

print("\n### PER-MATCH DETAIL")
for (sp, lg), ms in sorted(byleague.items()):
    print(f"\n-- {sp} / {lg}  (country={ms[0]['country_name']}, league_id={ms[0]['league_id']})")
    for m in ms:
        d = m['parsed']
        hi = d.get('home',{}); ai = d.get('away',{})
        print(f"  [{m['cause']}] {m['match_id']} | {m['name']!r} | {m['match_date']} | {m['status']} "
              f"| season={m['season_id']} exists={'S' if m['season_exists'] else 'N'} orphan={m['orphan_season']}")
        print(f"        home={hi.get('name')!r} exists={hi.get('team_exists')} any={bool(hi.get('team_ids_any_country'))} linked={hi.get('linked')} ph={hi.get('placeholder')}")
        print(f"        away={ai.get('name')!r} exists={ai.get('team_exists')} any={bool(ai.get('team_ids_any_country'))} linked={ai.get('linked')} ph={ai.get('placeholder')}")

# totals
cnt = defaultdict(int)
for m in nulls: cnt[m['cause']] += 1
print("\n### TOTALS BY CAUSE")
for k in ('a','b','c','d'):
    print(f"  ({k}): {cnt[k]}")
print(f"  orphan_season (overlaps): {sum(1 for m in nulls if m['orphan_season'])}")
print(f"  TOTAL: {len(nulls)}")

# 4) GLOBAL orphan season audit (all matches, not just NULL)
print("\n### GLOBAL: matches with non-null season_id NOT present in season")
orph = q("""
  SELECT s.name AS sport, l.league_name, m.season_id, COUNT(*) AS n
    FROM match m
    JOIN league l ON l.league_id = m.league_id
    JOIN sport  s ON s.sport_id  = l.sport_id
   WHERE m.season_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM season se WHERE se.season_id = m.season_id)
   GROUP BY s.name, l.league_name, m.season_id
   ORDER BY n DESC
""")
tot_orph = sum(r[3] for r in orph)
print(f"  Total matches with orphan season_id: {tot_orph} across {len(orph)} (league,season) groups")
for r in orph[:60]:
    print(f"    {r[0]} / {r[1]} | season={r[2]} | matches={r[3]}")

print("\n### GLOBAL: matches with NULL season_id")
nullseason = q("""SELECT COUNT(*) FROM match WHERE season_id IS NULL""")
print(f"  match.season_id NULL: {nullseason[0][0]}")

print("\n### GLOBAL: season rows with season_start = season_end (suspicious)")
badseason = q("""SELECT season_id, season_name, season_start, season_end, league_id
                  FROM season WHERE season_start = season_end""")
print(f"  count: {len(badseason)}")
for r in badseason[:30]:
    print(f"    {r[0]} | {r[1]!r} | {r[2]}..{r[3]} | league={r[4]}")

# total NULL match_detail rows (not matches)
nd = q("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")
print(f"\n### TOTAL match_detail rows with team_id NULL: {nd[0][0]}")

con.close()
