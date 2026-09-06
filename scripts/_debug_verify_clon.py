"""Verifica que la copia LOCAL coincide con el remoto (READ-ONLY en ambos).
Compara: conjunto de tablas, nº de columnas por tabla (esquema) y nº de filas.
Remoto via get_conn() (config.py) ; local via localhost:5432 (sports_container)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import psycopg2
from api.services.database import get_conn  # remoto

LOCAL = dict(host='127.0.0.1', port=5432, dbname='sports_db',
             user='DB_USER', password='DB_PASS', connect_timeout=10)

def snapshot(cur):
    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' ORDER BY 1""")
    tables = [r[0] for r in cur.fetchall()]
    cols, rows = {}, {}
    for t in tables:
        cur.execute("""SELECT count(*) FROM information_schema.columns
                       WHERE table_schema='public' AND table_name=%s""", (t,))
        cols[t] = cur.fetchone()[0]
        cur.execute(f'SELECT count(*) FROM public."{t}"')
        rows[t] = cur.fetchone()[0]
    return tables, cols, rows

rc = get_conn(); rcur = rc.cursor()
lc = psycopg2.connect(**LOCAL); lcur = lc.cursor()
rt, rcol, rrow = snapshot(rcur)
lt, lcol, lrow = snapshot(lcur)

solo_remoto = sorted(set(rt) - set(lt))
solo_local  = sorted(set(lt) - set(rt))
print(f"Tablas: remoto={len(rt)}  local={len(lt)}")
print(f"  solo en remoto (faltan en local): {solo_remoto or 'ninguna'}")
print(f"  solo en local  (extra)          : {solo_local or 'ninguna'}")

print("\n%-26s %8s %8s   %10s %10s  %s" % ("tabla","col_R","col_L","filas_R","filas_L","estado"))
print("-"*82)
todo_ok = True
for t in sorted(set(rt) & set(lt)):
    col_ok = rcol[t] == lcol[t]
    row_ok = rrow[t] == lrow[t]
    estado = "OK" if (col_ok and row_ok) else ("DIFF-ESQUEMA" if not col_ok else "DIFF-FILAS")
    if not (col_ok and row_ok): todo_ok = False
    print("%-26s %8d %8d   %10d %10d  %s" %
          (t, rcol[t], lcol[t], rrow[t], lrow[t], estado))

print("-"*82)
print("RESULTADO:", "✅ COPIA IDÉNTICA (tablas, columnas y filas coinciden)"
      if (todo_ok and not solo_remoto and not solo_local)
      else "⚠️ HAY DIFERENCIAS (ver arriba)")
rcur.close(); rc.close(); lcur.close(); lc.close()
