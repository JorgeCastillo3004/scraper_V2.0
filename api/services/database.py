import json
import sys, os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from api.config import LEAGUES_INFO_PATH

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
SPORT_NAME_MAP_PATH = os.path.join(PROJECT_ROOT, 'check_points', 'sport_name_map.json')
SPORTS_CACHE_TTL = 300
LEAGUE_STATS_CACHE_TTL = 60
_sports_cache = {'expires_at': 0, 'data': []}
_league_stats_cache = {'expires_at': 0, 'data': {}}


def get_conn():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        connect_timeout=10,
        options="-c statement_timeout=15000"
    )


def _default_project_sport(db_name: str) -> str:
    return db_name.upper().replace(' ', '_')


def get_sport_name_map() -> dict:
    try:
        with open(SPORT_NAME_MAP_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return data.get('db_to_project', {})
    except Exception:
        return {}


def db_sport_to_project(db_name: str) -> str:
    mapping = get_sport_name_map()
    return mapping.get(db_name, _default_project_sport(db_name))


def project_sport_to_db(project_name: str) -> str:
    mapping = get_sport_name_map()
    reverse = {project: db for db, project in mapping.items()}
    return reverse.get(project_name, project_name.replace('_', ' ').title())


def get_sports_from_db() -> list[str]:
    """Sports available in DB, mapped to project/checkpoint names."""
    now = time.time()
    if now < _sports_cache['expires_at']:
        return _sports_cache['data']
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM sport ORDER BY name")
                sports = [db_sport_to_project(row[0]) for row in cur.fetchall()]
                _sports_cache.update({
                    'expires_at': now + SPORTS_CACHE_TTL,
                    'data': sports,
                })
                return sports
    except Exception:
        return []


def get_all_league_stats() -> dict:
    """Stats for ALL leagues. Returns {league_id: {matches, results, fixtures, teams}}."""
    now = time.time()
    if now < _league_stats_cache['expires_at']:
        return _league_stats_cache['data']
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT league_id, COUNT(*) FROM match WHERE league_id IS NOT NULL GROUP BY league_id"
                )
                match_counts = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute(
                    """
                    SELECT league_id, COUNT(*)
                    FROM match
                    WHERE league_id IS NOT NULL AND status = 'COMPLETED'
                    GROUP BY league_id
                    """
                )
                result_counts = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute(
                    """
                    SELECT league_id, COUNT(*)
                    FROM match
                    WHERE league_id IS NOT NULL AND status = 'SCHEDULED'
                    GROUP BY league_id
                    """
                )
                fixture_counts = {r[0]: r[1] for r in cur.fetchall()}
                cur.execute(
                    "SELECT league_id, COUNT(DISTINCT team_id) FROM league_team WHERE league_id IS NOT NULL GROUP BY league_id"
                )
                team_counts = {r[0]: r[1] for r in cur.fetchall()}
        all_ids = set(match_counts) | set(result_counts) | set(fixture_counts) | set(team_counts)
        data = {
            lid: {
                'matches': match_counts.get(lid, 0),
                'results': result_counts.get(lid, 0),
                'fixtures': fixture_counts.get(lid, 0),
                'teams': team_counts.get(lid, 0),
            }
            for lid in all_ids
        }
        _league_stats_cache.update({
            'expires_at': now + LEAGUE_STATS_CACHE_TTL,
            'data': data,
        })
        return data
    except Exception:
        return {}


def get_global_stats() -> list[dict]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        s.name                                  AS sport,
                        COUNT(DISTINCT l.league_id)             AS leagues,
                        COUNT(DISTINCT lt.team_id)              AS teams,
                        COUNT(DISTINCT m.match_id)              AS matches,
                        COUNT(DISTINCT p.player_id)             AS players
                    FROM sport s
                    LEFT JOIN league           l  ON l.sport_id  = s.sport_id
                    LEFT JOIN league_team       lt ON lt.league_id = l.league_id
                    LEFT JOIN match            m  ON m.league_id = l.league_id
                    LEFT JOIN team_players_entity tp ON tp.team_id = lt.team_id
                    LEFT JOIN player           p  ON p.player_id = tp.player_id
                    GROUP BY s.name
                    ORDER BY s.name
                """)
                rows = cur.fetchall()
                cols = ['sport', 'leagues', 'teams', 'matches', 'players']
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        return [{'error': str(e)}]


INCONSISTENCIAS_CACHE_TTL = 60
_inconsistencias_cache = {'expires_at': 0, 'data': None}

LEAGUE_KEY_INDEX_TTL = 300
_league_key_index = {'expires_at': 0, 'data': {}}


def get_league_key_index() -> dict:
    """Índice inverso {db_league_id: {'sport': SPORT_KEY, 'key': LEAGUE_KEY}}.

    Construido desde check_points/leagues_info.json (cada entrada trae su
    league_id de la DB). Permite mapear una liga con inconsistencias —que ya
    conocemos por su league_id desde la base de datos— a la key exacta que
    necesita fix_null_team_ids.py en --league SPORT_KEY/LEAGUE_KEY, sin pegar
    strings de nombres (evita problemas de mayúsculas / naming de deportes).
    """
    now = time.time()
    if now < _league_key_index['expires_at'] and _league_key_index['data']:
        return _league_key_index['data']
    index = {}
    try:
        with open(LEAGUES_INFO_PATH, encoding='utf-8') as f:
            info = json.load(f)
        for sport, leagues in info.items():
            for key, meta in (leagues or {}).items():
                lid = (meta or {}).get('league_id')
                if lid:
                    index[lid] = {'sport': sport, 'key': key}
    except Exception:
        pass
    _league_key_index.update({'expires_at': now + LEAGUE_KEY_INDEX_TTL, 'data': index})
    return index

# Mapa visible → query SQL. Cada uno devuelve filas (sport, country, league, count)
# salvo "status_legacy" que es status → count.
_INCONS_QUERIES = {
    'score_minus_one': {
        'label': 'Partidos pasados con score = -1',
        'severity': 'high',
        'total_sql': """
            SELECT COUNT(DISTINCT m.match_id)
            FROM match m
            JOIN match_detail md ON md.match_id = m.match_id
            JOIN score_entity se ON se.match_detail_id = md.match_detail_id
            WHERE se.points = -1 AND m.match_date < CURRENT_DATE
        """,
        'by_league_sql': """
            SELECT s.name, c.country_name, l.league_name,
                   COUNT(DISTINCT m.match_id) AS cnt, l.league_id
            FROM match m
            JOIN match_detail md ON md.match_id = m.match_id
            JOIN score_entity se ON se.match_detail_id = md.match_detail_id
            JOIN league  l ON l.league_id  = m.league_id
            JOIN sport   s ON s.sport_id   = l.sport_id
            JOIN country c ON c.country_id = l.country_id
            WHERE se.points = -1 AND m.match_date < CURRENT_DATE
            GROUP BY s.name, c.country_name, l.league_name, l.league_id
            ORDER BY cnt DESC
            LIMIT 15
        """,
    },
    'fk_roto_team': {
        'label': 'match_detail con team_id inexistente (FK rota)',
        'severity': 'high',
        'total_sql': """
            SELECT COUNT(*)
            FROM match_detail md
            LEFT JOIN team t ON t.team_id = md.team_id
            WHERE t.team_id IS NULL
        """,
        'by_league_sql': """
            SELECT s.name, c.country_name, l.league_name, COUNT(*) AS cnt, l.league_id
            FROM match_detail md
            LEFT JOIN team t ON t.team_id = md.team_id
            JOIN match  m ON m.match_id   = md.match_id
            JOIN league l ON l.league_id  = m.league_id
            JOIN sport  s ON s.sport_id   = l.sport_id
            JOIN country c ON c.country_id = l.country_id
            WHERE t.team_id IS NULL
            GROUP BY s.name, c.country_name, l.league_name, l.league_id
            ORDER BY cnt DESC
            LIMIT 15
        """,
    },
    'detail_no_2': {
        'label': 'Partidos con match_detail distinto de 2',
        'severity': 'medium',
        'total_sql': """
            SELECT COUNT(*) FROM (
              SELECT match_id FROM match_detail
              GROUP BY match_id HAVING COUNT(*) <> 2
            ) t
        """,
        'by_league_sql': """
            SELECT s.name, c.country_name, l.league_name, COUNT(*) AS cnt, l.league_id
            FROM (
              SELECT match_id FROM match_detail
              GROUP BY match_id HAVING COUNT(*) <> 2
            ) bad
            JOIN match  m ON m.match_id   = bad.match_id
            JOIN league l ON l.league_id  = m.league_id
            JOIN sport  s ON s.sport_id   = l.sport_id
            JOIN country c ON c.country_id = l.country_id
            GROUP BY s.name, c.country_name, l.league_name, l.league_id
            ORDER BY cnt DESC
            LIMIT 15
        """,
    },
    'detail_no_score': {
        'label': 'match_detail sin score_entity',
        'severity': 'medium',
        'total_sql': """
            SELECT COUNT(*)
            FROM match_detail md
            LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
            WHERE se.match_detail_id IS NULL
        """,
        'by_league_sql': """
            SELECT s.name, c.country_name, l.league_name, COUNT(*) AS cnt, l.league_id
            FROM match_detail md
            LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
            JOIN match  m ON m.match_id   = md.match_id
            JOIN league l ON l.league_id  = m.league_id
            JOIN sport  s ON s.sport_id   = l.sport_id
            JOIN country c ON c.country_id = l.country_id
            WHERE se.match_detail_id IS NULL
            GROUP BY s.name, c.country_name, l.league_name, l.league_id
            ORDER BY cnt DESC
            LIMIT 15
        """,
    },
    'no_statistics': {
        'label': 'Partidos sin estadísticas (con resultado)',
        'severity': 'medium',
        # COMPLETED con resultado real (ningún score = -1) y sin statistic.
        # Población de backfill de update_pending_matches --solo-sin-stats.
        'total_sql': """
            SELECT COUNT(*)
            FROM match m
            WHERE m.status = 'COMPLETED'
              AND (m.statistic IS NULL OR m.statistic IN ('', '{}'))
              AND NOT EXISTS (
                  SELECT 1 FROM match_detail md
                    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
                   WHERE md.match_id = m.match_id AND se.points = -1)
        """,
        'by_league_sql': """
            SELECT s.name, c.country_name, l.league_name,
                   COUNT(*) AS cnt, l.league_id
            FROM match m
            JOIN league  l ON l.league_id  = m.league_id
            JOIN sport   s ON s.sport_id   = l.sport_id
            JOIN country c ON c.country_id = l.country_id
            WHERE m.status = 'COMPLETED'
              AND (m.statistic IS NULL OR m.statistic IN ('', '{}'))
              AND NOT EXISTS (
                  SELECT 1 FROM match_detail md
                    JOIN score_entity se ON se.match_detail_id = md.match_detail_id
                   WHERE md.match_id = m.match_id AND se.points = -1)
            GROUP BY s.name, c.country_name, l.league_name, l.league_id
            ORDER BY cnt DESC
            LIMIT 15
        """,
    },
}

_STATUS_LEGACY_VALUES = ('completed', 'schedule', 'R', 'P', 'IN PROGRESS')


def get_inconsistencias_summary() -> dict:
    """
    Resumen de inconsistencias en la BD para la pantalla de control.
    Cachea 60 s para no martillar Postgres si el panel se refresca seguido.
    """
    now = time.time()
    if _inconsistencias_cache['data'] is not None and now < _inconsistencias_cache['expires_at']:
        return _inconsistencias_cache['data']

    summary = {}
    by_league = {}
    items = []
    key_index = get_league_key_index()

    def _row_to_dict(r):
        """Fila by_league → dict + mapeo a la key de leagues_info por league_id.

        r = (sport, country, league, count, league_id). mappable indica si la
        liga existe en leagues_info (condición para poder lanzar el fix).
        """
        league_id = r[4] if len(r) > 4 else None
        mapped = key_index.get(league_id)
        return {
            'sport': r[0], 'country': r[1], 'league': r[2], 'count': r[3],
            'league_id': league_id,
            'sport_key':  mapped['sport'] if mapped else None,
            'league_key': mapped['key'] if mapped else None,
            'mappable': bool(mapped),
        }

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                for key, cfg in _INCONS_QUERIES.items():
                    cur.execute(cfg['total_sql'])
                    total = cur.fetchone()[0] or 0
                    summary[key] = total
                    items.append({
                        'key': key,
                        'label': cfg['label'],
                        'severity': cfg['severity'],
                        'count': total,
                    })

                    cur.execute(cfg['by_league_sql'])
                    by_league[key] = [_row_to_dict(r) for r in cur.fetchall()]

                # Status legacy (no aplica mapeo por liga: es por status)
                cur.execute(
                    "SELECT status, COUNT(*) FROM match WHERE status = ANY(%s) GROUP BY status",
                    (list(_STATUS_LEGACY_VALUES),),
                )
                legacy_rows = cur.fetchall()
                legacy_total = sum(r[1] for r in legacy_rows)
                summary['status_legacy'] = legacy_total
                items.append({
                    'key': 'status_legacy',
                    'label': 'Status legacy en tabla match',
                    'severity': 'low',
                    'count': legacy_total,
                })
                by_league['status_legacy'] = [
                    {'sport': None, 'country': None, 'league': r[0], 'count': r[1],
                     'league_id': None, 'sport_key': None, 'league_key': None,
                     'mappable': False}
                    for r in legacy_rows
                ]

        data = {
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'summary': summary,
            'items': items,
            'by_league': by_league,
        }
        _inconsistencias_cache.update({'expires_at': now + INCONSISTENCIAS_CACHE_TTL, 'data': data})
        return data
    except Exception as e:
        return {'error': str(e), 'summary': {}, 'items': [], 'by_league': {}}


def get_news_stats() -> dict:
    """Resumen de la tabla `news` para la pantalla de Noticias (solo lectura).

    Devuelve el total de noticias en la BD y la fecha de la **última noticia
    extraída** (MAX(published)). Si no hay noticias, last_published es None.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*), MAX(published) FROM news")
                row = cur.fetchone()
        total = row[0] or 0
        last = row[1].isoformat() if row and row[1] else None
        return {'total': total, 'last_published': last}
    except Exception as e:
        return {'error': str(e), 'total': 0, 'last_published': None}


def get_live_matches() -> list[dict]:
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.match_id, m.name, m.match_date, m.status,
                           l.league_name, s.name as sport
                    FROM match m
                    JOIN league l ON l.league_id = m.league_id
                    JOIN sport  s ON s.sport_id  = l.sport_id
                    WHERE m.status IN ('LIVE','COMPLETED')
                      AND m.match_date = CURRENT_DATE
                    ORDER BY m.match_date DESC
                    LIMIT 50
                """)
                rows = cur.fetchall()
                cols = ['match_id', 'name', 'match_date', 'status', 'league_name', 'sport']
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        return [{'error': str(e)}]
