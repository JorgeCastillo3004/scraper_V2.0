#!/usr/bin/env python3
"""
Reparación puntual: 11 matches quedaron asignados a un league_id/season_id
FANTASMA (sin fila en `league`/`season`): 67d12aac… / d07d9f9b…
Son partidos de CFL (Canadian Football League). La CFL REAL ya existe:
  league_id 4c56a043-898b-4df1-a507-e49425da3b9b  (AM._FOOTBALL/CANADA_CFL)
  season_id 3fb801c6-534f-4fca-a6f2-495912f9889c  (2026, canónica en leagues_info)

ACCIÓN: re-apuntar (UPDATE match.league_id/season_id) los matches huérfanos a la
CFL real, SALVO los que ya existan duplicados (mismo name+date) en la CFL real
(esos se reportan, NO se tocan; el borrado requiere aprobación explícita).

Solo UPDATE. Nunca DELETE. dry-run por defecto; --apply escribe.
"""
import sys, argparse
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

ORPH_LEAGUE = '67d12aac-c621-4f09-bb2e-4cfa73c600b7'
REAL_LEAGUE = '4c56a043-898b-4df1-a507-e49425da3b9b'
REAL_SEASON = '3fb801c6-534f-4fca-a6f2-495912f9889c'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='Escribe en DB (default dry-run)')
    args = ap.parse_args()
    dry = not args.apply

    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    con.set_client_encoding('UTF8')
    if dry:
        con.set_session(readonly=True, autocommit=True)
    cur = con.cursor()

    # Sanity: la liga/temporada destino existen; la huérfana NO.
    cur.execute("SELECT count(*) FROM league WHERE league_id=%s", (REAL_LEAGUE,))
    assert cur.fetchone()[0] == 1, "CFL real no existe; abortar"
    cur.execute("SELECT count(*) FROM season WHERE season_id=%s", (REAL_SEASON,))
    assert cur.fetchone()[0] == 1, "season CFL real no existe; abortar"
    cur.execute("SELECT count(*) FROM league WHERE league_id=%s", (ORPH_LEAGUE,))
    assert cur.fetchone()[0] == 0, "la liga 'huérfana' SÍ existe; revisar antes"

    cur.execute("SELECT match_id, name, match_date FROM match WHERE league_id=%s ORDER BY match_date",
                (ORPH_LEAGUE,))
    orphans = cur.fetchall()
    print(f"Huérfanos bajo {ORPH_LEAGUE[:8]}…: {len(orphans)}")

    to_repoint, dups = [], []
    for mid, name, dt in orphans:
        cur.execute("SELECT match_id FROM match WHERE league_id=%s AND name=%s AND match_date=%s",
                    (REAL_LEAGUE, name, dt))
        existing = cur.fetchall()
        if existing:
            dups.append((mid, name, dt, existing[0][0]))
        else:
            to_repoint.append((mid, name, dt))

    print(f"\n→ A RE-APUNTAR (no duplicados): {len(to_repoint)}")
    for mid, name, dt in to_repoint:
        print(f"   {mid[:8]} {name!r} {dt}")
    print(f"\n→ DUPLICADOS (NO se tocan; reportar para borrado con tu OK): {len(dups)}")
    for mid, name, dt, real_mid in dups:
        print(f"   huérfano {mid[:8]} == real {str(real_mid)[:8]} | {name!r} {dt}")

    if dry:
        print("\n[DRY-RUN] No se escribió nada. Re-correr con --apply.")
        # SQL listo para el borrado del duplicado (NO ejecutado):
        for mid, name, dt, real_mid in dups:
            print(f"   -- (requiere tu OK) borraría huérfano duplicado:\n"
                  f"   --   DELETE FROM match_detail WHERE match_id='{mid}';\n"
                  f"   --   DELETE FROM match WHERE match_id='{mid}';")
        con.close(); return

    # APPLY: UPDATE re-apuntando league_id + season_id
    ids = [m[0] for m in to_repoint]
    cur.execute("""UPDATE match SET league_id=%s, season_id=%s
                    WHERE match_id = ANY(%s)""", (REAL_LEAGUE, REAL_SEASON, ids))
    print(f"\n[APPLY] match re-apuntados: {cur.rowcount}")
    con.commit()
    print("[OK] commit. Duplicado(s) NO tocado(s):", [d[0][:8] for d in dups])
    con.close()


if __name__ == '__main__':
    main()
