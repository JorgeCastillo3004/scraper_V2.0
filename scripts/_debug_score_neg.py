import os, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
from data_base import get_connection

con = get_connection()
cur = con.cursor()

def q(title, sql):
    print("\n=== " + title + " ===")
    cur.execute(sql)
    for r in cur.fetchall():
        print("  " + " | ".join("" if v is None else str(v) for v in r))

# 0) columnas de match (¿hay created_at / inserted_at?)
q("columnas de match", """
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='match' ORDER BY ordinal_position;
""")

# 1) total de PASADOS con score -1
q("TOTAL pasados con score=-1", """
SELECT count(DISTINCT m.match_id)
FROM match m
JOIN match_detail md ON md.match_id=m.match_id
JOIN score_entity se ON se.match_detail_id=md.match_detail_id
WHERE se.points=-1 AND m.match_date < CURRENT_DATE;
""")

# 2) por liga (top 25)
q("pasados -1 por liga (top 25)", """
SELECT s.name, l.league_name, count(DISTINCT m.match_id) c
FROM match m
JOIN match_detail md ON md.match_id=m.match_id
JOIN score_entity se ON se.match_detail_id=md.match_detail_id
LEFT JOIN league l ON l.league_id=m.league_id
LEFT JOIN sport  s ON s.sport_id=l.sport_id
WHERE se.points=-1 AND m.match_date < CURRENT_DATE
GROUP BY 1,2 ORDER BY c DESC LIMIT 25;
""")

# 3) distribución por status de esos -1 pasados
q("status de los -1 pasados", """
SELECT COALESCE(m.status,'(null)'), count(DISTINCT m.match_id) c
FROM match m
JOIN match_detail md ON md.match_id=m.match_id
JOIN score_entity se ON se.match_detail_id=md.match_detail_id
WHERE se.points=-1 AND m.match_date < CURRENT_DATE
GROUP BY 1 ORDER BY c DESC;
""")

# 4) por fecha de partido (últimos días) para ver el "atraso en un día"
q("-1 pasados por match_date (ultimos 15 dias)", """
SELECT m.match_date::date, count(DISTINCT m.match_id) c
FROM match m
JOIN match_detail md ON md.match_id=m.match_id
JOIN score_entity se ON se.match_detail_id=md.match_detail_id
WHERE se.points=-1 AND m.match_date < CURRENT_DATE
  AND m.match_date >= CURRENT_DATE - INTERVAL '15 days'
GROUP BY 1 ORDER BY 1 DESC;
""")

con.close()
print("\n[read-only, sin commit]")
