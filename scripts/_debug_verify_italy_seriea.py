"""Verificación READ-ONLY de la última corrida (update_matches · ITALY Serie A).
Reusa get_conn() del panel. No abre driver, no escribe nada (solo SELECT)."""
import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)

from api.services.database import get_conn

LEAGUE_ID = 'ad4c30d6-4ec3-4dcc-9d23-57c9bc91c86e'   # ITALY Serie A (de la selección 16:12)
HAS_STATS = "(m.statistic IS NOT NULL AND m.statistic NOT IN ('', '{}'))"

conn = get_conn()
cur = conn.cursor()

# 0) Identidad de la liga
cur.execute("""
    SELECT s.name, c.country_name, l.league_name
    FROM league l JOIN sport s ON s.sport_id=l.sport_id
                  JOIN country c ON c.country_id=l.country_id
    WHERE l.league_id = %s
""", (LEAGUE_ID,))
row = cur.fetchone()
print("LIGA:", row, "\n" + "="*70)

# 1) Conteos agregados de la liga
cur.execute(f"""
    SELECT
      COUNT(*)                                                       AS total,
      COUNT(*) FILTER (WHERE m.status='COMPLETED')                   AS completed,
      COUNT(*) FILTER (WHERE m.status='COMPLETED' AND {HAS_STATS})   AS completed_con_stats,
      COUNT(*) FILTER (WHERE {HAS_STATS})                            AS con_stats
    FROM match m
    WHERE m.league_id = %s
""", (LEAGUE_ID,))
total, completed, comp_stats, con_stats = cur.fetchone()
print(f"total partidos liga      : {total}")
print(f"  COMPLETED              : {completed}")
print(f"  COMPLETED con stats    : {comp_stats}")
print(f"  con statistic (cualq.) : {con_stats}")

# 2) Inconsistencias residuales en esta liga (deberían ser 0 tras la corrida)
cur.execute("""
    SELECT COUNT(DISTINCT m.match_id)
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
    WHERE m.league_id = %s AND se.points = -1 AND m.match_date < CURRENT_DATE
""", (LEAGUE_ID,))
score_minus1 = cur.fetchone()[0]

cur.execute(f"""
    SELECT COUNT(*)
    FROM match m
    WHERE m.league_id = %s AND m.status='COMPLETED' AND NOT {HAS_STATS}
      AND NOT EXISTS (SELECT 1 FROM match_detail md
                      JOIN score_entity se ON se.match_detail_id=md.match_detail_id
                      WHERE md.match_id=m.match_id AND se.points=-1)
""", (LEAGUE_ID,))
completed_sin_stats = cur.fetchone()[0]
print(f"\nINCONSISTENCIAS RESIDUALES (esperado 0):")
print(f"  pasados con score=-1         : {score_minus1}")
print(f"  COMPLETED con resultado y SIN stats: {completed_sin_stats}")

# 3) Muestra de los últimos 8 partidos COMPLETED (score + largo de statistic)
print("\n" + "="*70 + "\nMUESTRA (últimos 8 COMPLETED): fecha | score | n_ind_stats | match_id")
cur.execute(f"""
    SELECT m.match_date,
           string_agg(se.points::text, '-' ORDER BY md.match_detail_id) AS score,
           length(m.statistic) AS stat_len,
           m.statistic LIKE '%%,%%' AS tiene_dict,
           m.match_id
    FROM match m
    JOIN match_detail md ON md.match_id = m.match_id
    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
    WHERE m.league_id = %s AND m.status='COMPLETED'
    GROUP BY m.match_id, m.match_date, m.statistic
    ORDER BY m.match_date DESC
    LIMIT 8
""", (LEAGUE_ID,))
for d, score, slen, _, mid in cur.fetchall():
    print(f"  {d} | {score:>6} | stat_len={slen} | {mid}")

cur.close(); conn.close()
