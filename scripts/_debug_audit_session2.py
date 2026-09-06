import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'src'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
con.set_session(readonly=True, autocommit=True); con.set_client_encoding('UTF8')
cur = con.cursor(); cur.execute("SET client_min_messages TO ERROR")
def q(sql,p=None): cur.execute(sql,p or ()); return cur.fetchall()

FW='2e7ee992-42e9-4347-927e-a2bc27e08027'
print("## FOOTBALL WORLD World Cup: los 76 con score -1, son pasados o futuros?")
r=q("""SELECT (m.match_date<CURRENT_DATE) AS pasado, m.status, COUNT(DISTINCT m.match_id)
  FROM match m JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE m.league_id=%s AND se.points=-1
  GROUP BY 1,2 ORDER BY 1,3 DESC""",(FW,))
for x in r: print("  pasado=%s status=%-12s n=%s"%(x[0],x[1],x[2]))

print("\n## Global: TODOS los matches con score -1 (pasados+futuros), por status")
r=q("""SELECT (m.match_date<CURRENT_DATE) pasado, m.status, COUNT(DISTINCT m.match_id)
  FROM match m JOIN match_detail md ON md.match_id=m.match_id
  JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE se.points=-1 GROUP BY 1,2 ORDER BY 3 DESC""")
for x in r: print("  pasado=%s status=%-12s n=%s"%(x[0],x[1],x[2]))

print("\n## El 1 match_detail con team_id NULL: contexto")
r=q("""SELECT md.match_detail_id, m.match_id, m.name, m.match_date, m.status, s.name, l.league_name
  FROM match_detail md JOIN match m ON m.match_id=md.match_id
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  WHERE md.team_id IS NULL""")
for x in r: print(" ",x)

print("\n## match_detail!=2 -> el match D.Concepcion~Nublense (1 detalle): scores?")
r=q("""SELECT md.match_detail_id, md.team_id, md.home, md.visitor, se.points, se.entity
  FROM match_detail md LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  WHERE md.match_id='347c6402-fefa-41ca-98f5-fe9855605436'""")
for x in r: print(" ",x)

print("\n## Los 6 matches SCHEDULED con match_detail sin score_entity")
r=q("""SELECT DISTINCT m.match_id, m.name, m.match_date, l.league_name, s.name
  FROM match_detail md LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  JOIN match m ON m.match_id=md.match_id
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  WHERE se.match_detail_id IS NULL ORDER BY m.match_date""")
for x in r: print(" ",x)
con.close()
