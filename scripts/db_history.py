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

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'logs', 'db_history.json')


def get_snapshot():
    conn = psycopg2.connect(host='96.30.195.40', dbname='sports_db', user='wohhu', password='caracas123')
    cur  = conn.cursor()

    cur.execute("""
        SELECT sp.name, l.league_name, COUNT(m.match_id)
        FROM league l
        JOIN sport sp ON l.sport_id = sp.sport_id
        LEFT JOIN match m ON l.league_id = m.league_id
        GROUP BY sp.name, l.league_name
    """)
    rows = cur.fetchall()

    leagues = {}
    for sport, league, count in rows:
        sport = sport.upper()
        leagues.setdefault(sport, {})[league] = count

    total = sum(c for s in leagues.values() for c in s.values())

    cur.execute("SELECT COUNT(*) FROM team")
    teams = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM news")
    news_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'total_matches': total,
        'total_teams': teams,
        'total_news': news_count,
        'leagues': leagues,
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
    print(f"  Total partidos : {curr['total_matches']:>6}  (Δ {curr['total_matches'] - prev['total_matches']:+})")
    print(f"  Total equipos  : {curr['total_teams']:>6}  (Δ {curr['total_teams'] - prev['total_teams']:+})")
    print(f"  Total noticias : {curr['total_news']:>6}  (Δ {curr['total_news'] - prev.get('total_news', 0):+})")
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
    print(f"{'='*60}\n")


def show_list(history):
    print(f"\n{'='*50}")
    print(f"  HISTORIAL DE SNAPSHOTS ({len(history)} entradas)")
    print(f"{'='*50}")
    for i, h in enumerate(history):
        print(f"  [{i:02d}] {h['timestamp']}  partidos={h['total_matches']}  equipos={h['total_teams']}  noticias={h.get('total_news', '?')}")
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
        print(f"  Total partidos : {snapshot['total_matches']}")
        print(f"  Total equipos  : {snapshot['total_teams']}")
        print(f"  Total noticias : {snapshot['total_news']}")

    history.append(snapshot)
    save_history(history)
    print(f"Snapshot guardado en {HISTORY_FILE}")


if __name__ == '__main__':
    main()
