import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'src'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2
con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
con.set_session(readonly=True, autocommit=True); con.set_client_encoding('UTF8')
cur = con.cursor(); cur.execute("SET client_min_messages TO ERROR")
def q(sql,p=None): cur.execute(sql,p or ()); return cur.fetchall()
print("## score_entity columns:")
print([c[0] for c in q("SELECT column_name FROM information_schema.columns WHERE table_name='score_entity'")])
print("\n## D.Concepcion~Nublense detail+score:")
for x in q("""SELECT md.match_detail_id, md.team_id, md.home, md.visitor
  FROM match_detail md WHERE md.match_id='347c6402-fefa-41ca-98f5-fe9855605436'"""): print(" ",x)
for x in q("""SELECT se.* FROM score_entity se JOIN match_detail md ON md.match_detail_id=se.match_detail_id
  WHERE md.match_id='347c6402-fefa-41ca-98f5-fe9855605436'"""): print("  score:",x)
print("\n## 6 SCHEDULED matches sin score_entity:")
for x in q("""SELECT DISTINCT m.match_id, m.name, m.match_date, l.league_name, s.name
  FROM match_detail md LEFT JOIN score_entity se ON se.match_detail_id=md.match_detail_id
  JOIN match m ON m.match_id=md.match_id
  JOIN league l ON l.league_id=m.league_id JOIN sport s ON s.sport_id=l.sport_id
  WHERE se.match_detail_id IS NULL ORDER BY m.match_date"""): print(" ",x)
con.close()
