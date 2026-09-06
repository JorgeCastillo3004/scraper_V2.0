import os,sys
ROOT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')
sys.path.insert(0,ROOT); sys.path.insert(0,os.path.join(ROOT,'src'))
import psycopg2
from config import DB_HOST,DB_NAME,DB_USER,DB_PASS
con=psycopg2.connect(host=DB_HOST,dbname=DB_NAME,user=DB_USER,password=DB_PASS,connect_timeout=10)
con.set_session(readonly=True); cur=con.cursor()
cur.execute("SELECT sport_id, name FROM sport ORDER BY name")
print("sport_id | name")
for sid,name in cur.fetchall(): print(f"  {sid!r:30s} | {name!r}")
# ¿cómo se arma dict_sport_id en el código?
con.close()
