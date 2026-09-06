"""
db_history.py
-------------
Guarda un snapshot del estado de la DB y muestra la comparación con el anterior.

Uso:
    python scripts/db_history.py          # snapshot + comparación
    python scripts/db_history.py --list   # ver historial completo
"""

import sys
import json
import os
import psycopg2
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', 'db_history.json')


def get_snapshot():
    conn = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur  = conn.cursor()

    cur.execute("""
        SELECT sp.name, l.league_name,
               COUNT(m.match_id) AS total,
               COUNT(*) FILTER (WHERE m.status = 'COMPLETED') AS completed,
               COUNT(*) FILTER (WHERE m.statistic IS NOT NULL AND m.statistic NOT IN ('', '{}')) AS with_stats
        FROM league l
        JOIN sport sp ON l.sport_id = sp.sport_id
        LEFT JOIN match m ON l.league_id = m.league_id
        GROUP BY sp.name, l.league_name
    """)
    rows = cur.fetchall()

    leagues = {}
    leagues_completed = {}
    leagues_with_stats = {}
    for sport, league, count, completed, with_stats in rows:
        sport = sport.upper()
        leagues.setdefault(sport, {})[league] = count
        leagues_completed.setdefault(sport, {})[league] = completed
        leagues_with_stats.setdefault(sport, {})[league] = with_stats

    total = sum(c for s in leagues.values() for c in s.values())

    # Conteo global por status (refleja el cambio SCHEDULED → COMPLETED)
    cur.execute("SELECT status, COUNT(*) FROM match GROUP BY status")
    status_counts = {row[0]: row[1] for row in cur.fetchall()}

    # Partidos con estadísticas cargadas (match.statistic no vacío)
    cur.execute("SELECT COUNT(*) FROM match WHERE statistic IS NOT NULL AND statistic NOT IN ('', '{}')")
    matches_with_stats = cur.fetchone()[0]

    # Pendientes: partidos pasados con score = -1 (lo que completa update_pending_matches)
    cur.execute("""
        SELECT COUNT(DISTINCT m.match_id)
        FROM match m
        JOIN match_detail md ON md.match_id = m.match_id
        JOIN score_entity se ON se.match_detail_id = md.match_detail_id
        WHERE se.points = -1 AND m.match_date < CURRENT_DATE
    """)
    score_minus_one = cur.fetchone()[0]

    # Partidos con AL MENOS un match_detail.team_id NULL (equipos sin crear/enlazar)
    cur.execute("""
        SELECT COUNT(DISTINCT m.match_id)
        FROM match m
        JOIN match_detail md ON md.match_id = m.match_id
        WHERE md.team_id IS NULL
    """)
    matches_no_team_id = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM team")
    teams = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM news")
    news_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM sport")
    sports_count = cur.fetchone()[0]

    cur.execute("SELECT name FROM sport ORDER BY name")
    sports_list = [row[0] for row in cur.fetchall()]

    cur.execute("SELECT COUNT(*) FROM league")
    leagues_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM season")
    seasons_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM player")
    players_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_matches': total,
        'total_teams': teams,
        'total_news': news_count,
        'total_sports': sports_count,
        'sports_list': sports_list,
        'total_leagues': leagues_count,
        'total_seasons': seasons_count,
        'total_players': players_count,
        'matches_with_stats': matches_with_stats,
        'score_minus_one': score_minus_one,
        'matches_no_team_id': matches_no_team_id,
        'status_counts': status_counts,
        'leagues': leagues,
        'leagues_completed': leagues_completed,
        'leagues_with_stats': leagues_with_stats,
    }


def load_history():
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, 'r') as f:
        return json.load(f)


def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)


def show_comparison(prev, curr):
    print(f"\n{'='*60}")
    print(f"  SNAPSHOT: {curr['timestamp']}")
    print(f"{'='*60}")
    sports = curr.get('sports_list', [])
    print(f"  Total deportes : {curr['total_sports']:>6}  (Δ {curr['total_sports'] - prev.get('total_sports', 0):+})  {', '.join(sports)}")
    print(f"  Total ligas    : {curr['total_leagues']:>6}  (Δ {curr['total_leagues'] - prev.get('total_leagues', 0):+})")
    print(f"  Total temporadas:{curr['total_seasons']:>5}  (Δ {curr['total_seasons'] - prev.get('total_seasons', 0):+})")
    print(f"  Total partidos : {curr['total_matches']:>6}  (Δ {curr['total_matches'] - prev['total_matches']:+})")
    print(f"  Total equipos  : {curr['total_teams']:>6}  (Δ {curr['total_teams'] - prev['total_teams']:+})")
    print(f"  Total noticias : {curr['total_news']:>6}  (Δ {curr['total_news'] - prev.get('total_news', 0):+})")
    print(f"  Total jugadores: {curr['total_players']:>6}  (Δ {curr['total_players'] - prev.get('total_players', 0):+})")

    # ── Estado de partidos (refleja SCHEDULED → COMPLETED + carga de stats) ──
    cs = curr.get('status_counts', {})
    ps = prev.get('status_counts', {})
    print(f"\n  Estado de partidos (status):")
    for st in sorted(set(list(cs.keys()) + list(ps.keys()))):
        c = cs.get(st, 0)
        p = ps.get(st, 0)
        print(f"    {st:<14} {c:>6}  (Δ {c - p:+})")
    cws, pws = curr.get('matches_with_stats', 0), prev.get('matches_with_stats', 0)
    csm, psm = curr.get('score_minus_one', 0), prev.get('score_minus_one', 0)
    print(f"    {'con stats':<14} {cws:>6}  (Δ {cws - pws:+})")
    print(f"    {'score=-1 (pend)':<14} {csm:>6}  (Δ {csm - psm:+})")
    cnt, pnt = curr.get('matches_no_team_id', 0), prev.get('matches_no_team_id', 0)
    print(f"    {'sin team_id':<14} {cnt:>6}  (Δ {cnt - pnt:+})")

    print(f"\n  Cambios por liga (vs {prev['timestamp']}):")
    print(f"  {'-'*56}")

    changes = []
    all_sports = set(list(curr['leagues'].keys()) + list(prev['leagues'].keys()))
    for sport in sorted(all_sports):
        curr_leagues = curr['leagues'].get(sport, {})
        prev_leagues = prev['leagues'].get(sport, {})
        all_leagues  = set(list(curr_leagues.keys()) + list(prev_leagues.keys()))
        for league in sorted(all_leagues):
            c = curr_leagues.get(league, 0)
            p = prev_leagues.get(league, 0)
            delta = c - p
            if delta != 0:
                changes.append((sport, league, c, delta))

    if changes:
        for sport, league, count, delta in sorted(changes, key=lambda x: -x[3]):
            print(f"  [{sport}] {league:<35} {count:>5}  ({delta:+})")
    else:
        print("  Sin cambios desde el snapshot anterior.")

    # ── Partidos pasados a COMPLETED por liga (el cambio del último script) ──
    cc = curr.get('leagues_completed', {})
    pc = prev.get('leagues_completed', {})
    comp_changes = []
    for sport in sorted(set(list(cc.keys()) + list(pc.keys()))):
        cl = cc.get(sport, {})
        pl = pc.get(sport, {})
        for league in sorted(set(list(cl.keys()) + list(pl.keys()))):
            c = cl.get(league, 0)
            p = pl.get(league, 0)
            if c - p != 0:
                comp_changes.append((sport, league, c, c - p))
    if comp_changes:
        print(f"\n  Partidos COMPLETED nuevos por liga:")
        print(f"  {'-'*56}")
        for sport, league, count, delta in sorted(comp_changes, key=lambda x: -x[3]):
            print(f"  [{sport}] {league:<35} {count:>5}  ({delta:+})")
    print(f"{'='*60}\n")


def show_list(history):
    print(f"\n{'='*50}")
    print(f"  HISTORIAL DE SNAPSHOTS ({len(history)} entradas)")
    print(f"{'='*50}")
    for i, h in enumerate(history):
        completed = h.get('status_counts', {}).get('COMPLETED', '?')
        print(f"  [{i:02d}] {h['timestamp']}  deportes={h.get('total_sports','?')}  ligas={h.get('total_leagues','?')}  partidos={h['total_matches']}  COMPLETED={completed}  con_stats={h.get('matches_with_stats','?')}  equipos={h['total_teams']}  noticias={h.get('total_news','?')}  jugadores={h.get('total_players','?')}")
    print(f"{'='*50}\n")


def main():
    if '--list' in sys.argv:
        history = load_history()
        if not history:
            print("No hay historial guardado aún.")
        else:
            show_list(history)
        return

    history  = load_history()
    snapshot = get_snapshot()

    if history:
        show_comparison(history[-1], snapshot)
    else:
        print(f"\nPrimer snapshot guardado: {snapshot['timestamp']}")
        print(f"  Total deportes : {snapshot['total_sports']}  {', '.join(snapshot.get('sports_list', []))}")
        print(f"  Total ligas    : {snapshot['total_leagues']}")
        print(f"  Total temporadas: {snapshot['total_seasons']}")
        print(f"  Total partidos : {snapshot['total_matches']}")
        print(f"  Total equipos  : {snapshot['total_teams']}")
        print(f"  Total noticias : {snapshot['total_news']}")
        print(f"  Total jugadores: {snapshot['total_players']}")

    history.append(snapshot)
    save_history(history)
    print(f"Snapshot guardado en {HISTORY_FILE}")


if __name__ == '__main__':
    main()
