"""
db_delta.py
-----------
Muestra el estado actual de la DB del scraper y el delta vs el último snapshot.

Uso:
    env_sports/bin/python scripts/db_delta.py              # mostrar + guardar snapshot
    env_sports/bin/python scripts/db_delta.py --no-save    # solo mostrar
    env_sports/bin/python scripts/db_delta.py --reset      # borrar snapshot guardado
    env_sports/bin/python scripts/db_delta.py --top 5      # top N ligas afectadas

Snapshot persiste en tmp/db_delta_snapshot.json.
"""

import os, sys, json, argparse
from datetime import datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

SNAPSHOT = os.path.join(ROOT, 'tmp', 'db_delta_snapshot.json')


def fetch_state():
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME,
                            user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    out = {}

    cur.execute("SELECT COUNT(*) FROM match_detail WHERE team_id IS NULL")
    out['null_team_rows'] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(DISTINCT match_id) FROM match_detail WHERE team_id IS NULL")
    out['null_team_matches'] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM match
         WHERE status='COMPLETED'
           AND (statistic IS NULL OR statistic IN ('', '{}'))
    """)
    out['completed_no_stats'] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT m.match_id)
          FROM match m
          JOIN match_detail md ON md.match_id = m.match_id
          LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
         WHERE m.status='COMPLETED' AND se.score_id IS NULL
    """)
    out['completed_no_score'] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM match_detail")
    out['match_detail_total'] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM match")
    out['match_total'] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM team")
    out['team_total'] = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM score_entity")
    out['score_entity_total'] = cur.fetchone()[0]

    cur.close()
    conn.close()
    out['timestamp'] = datetime.now().isoformat(timespec='seconds')
    return out


def fetch_top_leagues(limit=5):
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME,
                            user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.league_id, COALESCE(l.league_name, '') AS name,
               COUNT(DISTINCT md.match_id) AS matches
          FROM match_detail md
          JOIN match m ON m.match_id = md.match_id
          LEFT JOIN league l ON l.league_id = m.league_id
         WHERE md.team_id IS NULL
         GROUP BY m.league_id, l.league_name
         ORDER BY matches DESC
         LIMIT %s
    """, (limit,))
    top_null = [(r[0], r[1], r[2]) for r in cur.fetchall()]

    cur.execute("""
        SELECT m.league_id, COALESCE(l.league_name, ''), COUNT(*) AS n
          FROM match m
          LEFT JOIN league l ON l.league_id = m.league_id
         WHERE m.status='COMPLETED'
           AND (m.statistic IS NULL OR m.statistic IN ('', '{}'))
         GROUP BY m.league_id, l.league_name
         ORDER BY n DESC
         LIMIT %s
    """, (limit,))
    top_stats = [(r[0], r[1], r[2]) for r in cur.fetchall()]

    cur.close()
    conn.close()
    return top_null, top_stats


def load_snapshot():
    if not os.path.exists(SNAPSHOT):
        return None
    try:
        return json.load(open(SNAPSHOT))
    except Exception:
        return None


def save_snapshot(state):
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    json.dump(state, open(SNAPSHOT, 'w'), indent=2)


def fmt_delta(curr, prev):
    if prev is None:
        return '       —'
    d = curr - prev
    if d == 0:
        return '       0'
    sign = '+' if d > 0 else ''
    return f'{sign}{d:>7d}'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--no-save', action='store_true', help='no actualizar snapshot')
    p.add_argument('--reset',   action='store_true', help='borrar snapshot previo y salir')
    p.add_argument('--top',     type=int, default=5, help='top N ligas (default 5)')
    args = p.parse_args()

    if args.reset:
        if os.path.exists(SNAPSHOT):
            os.remove(SNAPSHOT)
            print(f'snapshot borrado: {SNAPSHOT}')
        else:
            print('no había snapshot.')
        return

    prev = load_snapshot()
    curr = fetch_state()

    print('=' * 60)
    print(f"DB delta scraper_V2.0 — {curr['timestamp']}")
    if prev:
        print(f"vs snapshot anterior  — {prev.get('timestamp', '?')}")
    else:
        print('vs snapshot anterior  — (no hay; se creará uno tras este run)')
    print('=' * 60)

    rows = [
        ('match_detail NULL filas',  'null_team_rows'),
        ('Matches afectados',        'null_team_matches'),
        ('COMPLETED sin stats',      'completed_no_stats'),
        ('COMPLETED sin score',      'completed_no_score'),
        ('— teams totales',          'team_total'),
        ('— score_entity totales',   'score_entity_total'),
        ('— match_detail totales',   'match_detail_total'),
        ('— match totales',          'match_total'),
    ]
    print(f"{'métrica':<28} {'ahora':>10} {'antes':>10} {'Δ':>10}")
    print('-' * 60)
    for label, key in rows:
        curr_v = curr[key]
        prev_v = prev[key] if prev and key in prev else None
        prev_s = f'{prev_v:>10}' if prev_v is not None else f"{'—':>10}"
        print(f'{label:<28} {curr_v:>10} {prev_s} {fmt_delta(curr_v, prev_v):>10}')

    if args.top > 0:
        top_null, top_stats = fetch_top_leagues(limit=args.top)
        print()
        print(f'Top {args.top} ligas con team_id NULL:')
        for lid, name, n in top_null:
            print(f"  {str(lid)[:8]}  {(name or '')[:32]:<32} {n:>5} matches")
        print()
        print(f'Top {args.top} ligas con COMPLETED sin stats:')
        for lid, name, n in top_stats:
            print(f"  {str(lid)[:8]}  {(name or '')[:32]:<32} {n:>5} matches")

    if not args.no_save:
        save_snapshot(curr)
        print(f'\n[snapshot actualizado: {SNAPSHOT}]')


if __name__ == '__main__':
    main()
