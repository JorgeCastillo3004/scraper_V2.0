#!/usr/bin/env python3
"""
Etiqueta partidos PASADOS con score -1 que pertenecen a una TEMPORADA VIEJA
(nombre de season en DB != nombre de season actual en FlashScore, verificado con
_debug_verify_seasons_flashscore.py).

Etiqueta = UPDATE match.status = 'ARCHIVED_OLD_SEASON' (reversible, consultable).
NO borra. dry-run por defecto; --apply escribe.
"""
import sys, argparse
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
import psycopg2

LABEL = 'OLD_SEASON'   # status es varchar(17); mantener corto

# Mapa verificado 2026-06-16: league_key -> season_name ACTUAL en FlashScore.
FS_SEASON = {
    'BRAZIL_Serie A Betano': '2026', 'USA_NFL': '2026/2027',
    'COLOMBIA_Primera A': '2026', 'ECUADOR_Liga Pro': '2026',
    'PERU_Liga 1': '2026', 'EUROPE_Conference League': '2026/2027',
    'PARAGUAY_Copa de Primera': '2026', 'CHILE_Liga de Primera': '2026',
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args(); dry = not args.apply

    import json
    aff = json.load(open('tmp/_affected_leagues.json'))
    # (league_id, season_id) de grupos VIEJOS: db_season_name != FS_SEASON[league_key]
    old_groups = []
    for x in aff:
        fs = FS_SEASON.get(x['league_key'])
        if fs and x['db_season_name'] and x['db_season_name'] != fs:
            old_groups.append((x['league_id'], x['db_season_id'], x['league_key'],
                               x['db_season_name'], fs, x['n_matches']))

    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    con.set_client_encoding('UTF8')
    if dry: con.set_session(readonly=True, autocommit=True)
    cur = con.cursor()

    total = 0
    print(f"=== TEMPORADAS VIEJAS a etiquetar como '{LABEL}' (dry_run={dry}) ===")
    all_ids = []
    for lid, sid, key, dbs, fs, n in old_groups:
        cur.execute("""SELECT DISTINCT m.match_id FROM match m
                       JOIN match_detail md ON md.match_id=m.match_id
                       JOIN score_entity se ON se.match_detail_id=md.match_detail_id
                       WHERE se.points=-1 AND m.match_date<CURRENT_DATE
                         AND m.league_id=%s AND m.season_id=%s""", (lid, sid))
        ids = [r[0] for r in cur.fetchall()]
        all_ids += ids
        total += len(ids)
        print(f"  {key:<32} DB={dbs!r} vs FlashScore={fs!r} -> {len(ids)} partidos")

    print(f"\n  TOTAL a etiquetar: {total}")
    if dry:
        print("  [DRY-RUN] no se escribió. Re-correr con --apply.")
        con.close(); return

    cur.execute("UPDATE match SET status=%s WHERE match_id = ANY(%s)", (LABEL, all_ids))
    print(f"  [APPLY] match etiquetados (status='{LABEL}'): {cur.rowcount}")
    con.commit(); con.close()


if __name__ == '__main__':
    main()
