#!/usr/bin/env python3
"""
verificar_integridad_db.py
==========================
Auditoría **read-only** de la integridad de `sports_db` (scraper_V2.0).

Recorre toda la información deportiva de la base y reporta inconsistencias
*sin tocar un solo dato*. Es la herramienta de la sección 4 del plan de
organización (`documentacion/organizacion_proyecto.md`).

────────────────────────────────────────────────────────────────────────────
GARANTÍA DE SOLO-LECTURA
────────────────────────────────────────────────────────────────────────────
La conexión se abre con `set_session(readonly=True)`, de modo que PostgreSQL
**rechaza** cualquier INSERT/UPDATE/DELETE/DDL a nivel de servidor. El script
solo ejecuta SELECT. Si detecta filas a corregir (duplicados, huérfanos, etc.)
las **reporta con su identificador**, nunca las modifica ni elimina. La
corrección se hace después, con los scripts `fix_*` ya existentes y bajo
confirmación explícita (regla no negociable del proyecto: solo INSERT/UPDATE,
y DELETE solo caso por caso con aprobación).

────────────────────────────────────────────────────────────────────────────
QUÉ VALIDA
────────────────────────────────────────────────────────────────────────────
Muchas FKs NO están declaradas en el esquema (son implícitas), así que pueden
romperse y se verifican a mano. Los chequeos se agrupan en 5 familias:

  1. RESUMEN POR TABLA   → conteo de filas de cada tabla deportiva.
  2. REFERENCIAL         → huérfanos por FK implícita
                           (match→league/season/country, league→sport/country,
                            team→country, match_detail→team [FK rota real]).
  3. ESTRUCTURA          → match con match_detail ≠ 2; que sean 1 home + 1
                           visitor; match sin ningún detail; match_detail sin
                           score_entity; league sin ninguna season.
  4. CALIDAD             → score = -1 en partidos pasados; status legacy.
  5. DUPLICADOS          → por clave natural: sport, league, country, team,
                           season, match (cubre los bugs Football/FOOTBALL y
                           Champions League x3).

Las familias 2-4 reutilizan, cuando existen, las queries ya probadas en
`api/services/database.py` (`_INCONS_QUERIES`, `_STATUS_LEGACY_VALUES`) para no
duplicar lógica y mantener un único origen de verdad con la pestaña
"Inconsistencias" del panel.

────────────────────────────────────────────────────────────────────────────
DIAGRAMA DE FUNCIONAMIENTO
────────────────────────────────────────────────────────────────────────────

      ┌──────────────────────────────────────────────────────────────┐
      │  main()  — parseo de flags (--only/--limit/--by-league/--json) │
      └───────────────────────────┬──────────────────────────────────┘
                                  ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  open_readonly_connection()                                    │
      │    get_conn() (api.services.database)  →  conexión psycopg2    │
      │    set_session(readonly=True)  ⇒  Postgres bloquea escrituras  │
      └───────────────────────────┬──────────────────────────────────┘
                                  ▼
      ┌──────────────── un solo cursor, solo SELECT ──────────────────┐
      │  run_table_counts(cur)        → COUNT(*) por tabla            │
      │  run_checks(cur, CHECKS, ...) → por cada chequeo:            │
      │       count_sql   → nº de inconsistencias                     │
      │       sample_sql  → muestra (LIMIT N) de filas ofensoras      │
      │       by_league_sql (opcional, con --by-league) → top 15      │
      └───────────────────────────┬──────────────────────────────────┘
                                  ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  print_report(...)  → salida coloreada por severidad          │
      │  build_json(...)    → (con --json) vuelca a logs/integridad_* │
      │  worst_severity()   → exit code: 2=high, 1=medium, 0=ok       │
      └──────────────────────────────────────────────────────────────┘

El exit code distinto de cero (2 si hay `high`, 1 si solo `medium`) deja listo
el gancho para alertas automáticas (Telegram §8.3) y cron, más adelante.

────────────────────────────────────────────────────────────────────────────
USO
────────────────────────────────────────────────────────────────────────────
  env_sports/bin/python scripts/verificar_integridad_db.py            # full
  env_sports/bin/python scripts/verificar_integridad_db.py --by-league
  env_sports/bin/python scripts/verificar_integridad_db.py --only dup_league
  env_sports/bin/python scripts/verificar_integridad_db.py --limit 30
  env_sports/bin/python scripts/verificar_integridad_db.py --json      # + archivo
  env_sports/bin/python scripts/verificar_integridad_db.py --no-color

NOTA: filtrar por deporte (--sport) queda como mejora futura; esta versión
reporta global. Antes de ejecutar, confirmar que `config.py` apunta a la BD
LOCAL (correrlo abre conexión a esa base).
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Raíz del proyecto en el path para poder reusar api.services.database y config.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Reutilizamos conexión + catálogo de inconsistencias ya probado (single source
# of truth con la pestaña "Inconsistencias" del panel).
from api.services.database import get_conn, _INCONS_QUERIES, _STATUS_LEGACY_VALUES  # noqa: E402

# ── Colores ANSI (se desactivan con --no-color) ───────────────────────────────
RED = "\033[91m"; YEL = "\033[93m"; GRN = "\033[92m"; CYA = "\033[96m"
WHT = "\033[97m"; DIM = "\033[2m"; RST = "\033[0m"

# Color por severidad para el resumen.
SEV_COLOR = {'high': RED, 'medium': YEL, 'low': CYA, 'ok': GRN}


# ══════════════════════════════════════════════════════════════════════════════
#  CONEXIÓN READ-ONLY
# ══════════════════════════════════════════════════════════════════════════════

def open_readonly_connection():
    """Abre la conexión reusando get_conn() y la fuerza a SOLO LECTURA.

    `set_session(readonly=True)` hace que Postgres rechace cualquier escritura
    (INSERT/UPDATE/DELETE/DDL) aunque, por error, alguna query intentara una.
    `autocommit=True` evita transacciones abiertas colgadas en una herramienta
    de diagnóstico. Es la primera línea de defensa de la garantía read-only.
    """
    conn = get_conn()
    conn.set_session(readonly=True, autocommit=True)
    return conn


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS DE CONSULTA (solo SELECT)
# ══════════════════════════════════════════════════════════════════════════════

def scalar(cur, sql, params=None):
    """Ejecuta una query que devuelve un único valor (p.ej. COUNT(*))."""
    cur.execute(sql, params)
    row = cur.fetchone()
    return (row[0] if row and row[0] is not None else 0)


def fetch(cur, sql, params=None):
    """Ejecuta una query y devuelve todas las filas (lista de tuplas)."""
    cur.execute(sql, params)
    return cur.fetchall()


# ══════════════════════════════════════════════════════════════════════════════
#  CATÁLOGO DE CHEQUEOS
# ══════════════════════════════════════════════════════════════════════════════
#
#  Cada chequeo es un dict:
#     key           clave estable (para --only y JSON)
#     label         descripción legible
#     severity      'high' | 'medium' | 'low'
#     count_sql     SELECT que devuelve el nº de inconsistencias (escalar)
#     sample_sql    SELECT con filas ofensoras de ejemplo (se le añade LIMIT N)
#     params        (opcional) parámetros para count_sql/sample_sql
#     by_league_sql (opcional) desglose por liga (top 15), mostrado con --by-league
#
#  Los chequeos que ya existen en api.services.database._INCONS_QUERIES se
#  envuelven con _reused() para no reescribir su SQL.

# Conteos simples por tabla para el panorama general.
TABLE_COUNTS = [
    ('sport', 'sport'), ('country', 'country'), ('league', 'league'),
    ('season', 'season'), ('team', 'team'), ('league_team', 'league_team'),
    ('match', 'match'), ('match_detail', 'match_detail'),
    ('score_entity', 'score_entity'), ('stadium', 'stadium'),
    ('player', 'player'), ('tournament', 'tournament'), ('news', 'news'),
]


def _reused(key, sample_sql):
    """Construye un chequeo a partir de un _INCONS_QUERIES ya existente.

    Reusa label/severity/total_sql/by_league_sql del catálogo del panel y solo
    le agrega una query de muestra (sample_sql) para listar filas ofensoras.
    """
    cfg = _INCONS_QUERIES[key]
    return {
        'key': key,
        'label': cfg['label'],
        'severity': cfg['severity'],
        'count_sql': cfg['total_sql'],
        'by_league_sql': cfg.get('by_league_sql'),
        'sample_sql': sample_sql,
    }


# ── 2. Integridad referencial (huérfanos por FK implícita) ────────────────────
REFERENTIAL_CHECKS = [
    {
        'key': 'match_no_league',
        'label': 'match sin league válida (league_id NULL o inexistente)',
        'severity': 'high',
        'count_sql': """
            SELECT COUNT(*) FROM match m
            LEFT JOIN league l ON l.league_id = m.league_id
            WHERE l.league_id IS NULL
        """,
        'sample_sql': """
            SELECT m.match_id, m.name, m.match_date, m.league_id
            FROM match m
            LEFT JOIN league l ON l.league_id = m.league_id
            WHERE l.league_id IS NULL
            ORDER BY m.match_date DESC
        """,
    },
    {
        'key': 'match_no_season',
        'label': 'match sin season válida (season_id NULL o inexistente)',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM match m
            LEFT JOIN season s ON s.season_id = m.season_id
            WHERE s.season_id IS NULL
        """,
        'sample_sql': """
            SELECT m.match_id, m.name, m.match_date, m.season_id
            FROM match m
            LEFT JOIN season s ON s.season_id = m.season_id
            WHERE s.season_id IS NULL
            ORDER BY m.match_date DESC
        """,
    },
    {
        'key': 'match_no_country',
        'label': 'match sin country válido (country_id NULL o inexistente)',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM match m
            LEFT JOIN country c ON c.country_id = m.country_id
            WHERE c.country_id IS NULL
        """,
        'sample_sql': """
            SELECT m.match_id, m.name, m.match_date, m.country_id
            FROM match m
            LEFT JOIN country c ON c.country_id = m.country_id
            WHERE c.country_id IS NULL
            ORDER BY m.match_date DESC
        """,
    },
    {
        'key': 'league_no_sport',
        'label': 'league con sport_id inexistente',
        'severity': 'high',
        'count_sql': """
            SELECT COUNT(*) FROM league l
            LEFT JOIN sport s ON s.sport_id = l.sport_id
            WHERE s.sport_id IS NULL
        """,
        'sample_sql': """
            SELECT l.league_id, l.league_name, l.sport_id
            FROM league l
            LEFT JOIN sport s ON s.sport_id = l.sport_id
            WHERE s.sport_id IS NULL
            ORDER BY l.league_name
        """,
    },
    {
        'key': 'league_no_country',
        'label': 'league con country_id inexistente',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM league l
            LEFT JOIN country c ON c.country_id = l.country_id
            WHERE c.country_id IS NULL
        """,
        'sample_sql': """
            SELECT l.league_id, l.league_name, l.country_id
            FROM league l
            LEFT JOIN country c ON c.country_id = l.country_id
            WHERE c.country_id IS NULL
            ORDER BY l.league_name
        """,
    },
    {
        'key': 'team_no_country',
        'label': 'team con country_id inexistente',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM team t
            LEFT JOIN country c ON c.country_id = t.country_id
            WHERE c.country_id IS NULL
        """,
        'sample_sql': """
            SELECT t.team_id, t.team_name, t.country_id
            FROM team t
            LEFT JOIN country c ON c.country_id = t.country_id
            WHERE c.country_id IS NULL
            ORDER BY t.team_name
        """,
    },
    # match_detail con team_id roto: reusa la query del panel.
    _reused('fk_roto_team', """
        SELECT md.match_detail_id, md.match_id, md.team_id
        FROM match_detail md
        LEFT JOIN team t ON t.team_id = md.team_id
        WHERE t.team_id IS NULL
    """),
]

# ── 3. Estructura / cardinalidad ──────────────────────────────────────────────
STRUCTURE_CHECKS = [
    # match con match_detail != 2: reusa la query del panel.
    _reused('detail_no_2', """
        SELECT match_id, COUNT(*) AS n
        FROM match_detail
        GROUP BY match_id
        HAVING COUNT(*) <> 2
        ORDER BY n DESC
    """),
    {
        'key': 'detail_home_visitor',
        'label': 'match con 2 detail pero no 1 home + 1 visitor',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM (
              SELECT match_id,
                     SUM(CASE WHEN home    THEN 1 ELSE 0 END) AS h,
                     SUM(CASE WHEN visitor THEN 1 ELSE 0 END) AS v,
                     COUNT(*) AS n
              FROM match_detail
              GROUP BY match_id
            ) t
            WHERE n = 2 AND NOT (h = 1 AND v = 1)
        """,
        'sample_sql': """
            SELECT match_id, h, v FROM (
              SELECT match_id,
                     SUM(CASE WHEN home    THEN 1 ELSE 0 END) AS h,
                     SUM(CASE WHEN visitor THEN 1 ELSE 0 END) AS v,
                     COUNT(*) AS n
              FROM match_detail
              GROUP BY match_id
            ) t
            WHERE n = 2 AND NOT (h = 1 AND v = 1)
        """,
    },
    {
        'key': 'match_no_detail',
        'label': 'match sin ningún match_detail',
        'severity': 'high',
        'count_sql': """
            SELECT COUNT(*) FROM match m
            LEFT JOIN match_detail md ON md.match_id = m.match_id
            WHERE md.match_id IS NULL
        """,
        'sample_sql': """
            SELECT m.match_id, m.name, m.match_date
            FROM match m
            LEFT JOIN match_detail md ON md.match_id = m.match_id
            WHERE md.match_id IS NULL
            ORDER BY m.match_date DESC
        """,
    },
    # match_detail sin score_entity: reusa la query del panel.
    _reused('detail_no_score', """
        SELECT md.match_detail_id, md.match_id
        FROM match_detail md
        LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
        WHERE se.match_detail_id IS NULL
    """),
    {
        'key': 'league_no_season',
        'label': 'league sin ninguna season',
        'severity': 'medium',
        'count_sql': """
            SELECT COUNT(*) FROM league l
            LEFT JOIN season s ON s.league_id = l.league_id
            WHERE s.season_id IS NULL
        """,
        'sample_sql': """
            SELECT l.league_id, l.league_name, l.sport_id
            FROM league l
            LEFT JOIN season s ON s.league_id = l.league_id
            WHERE s.season_id IS NULL
            ORDER BY l.league_name
        """,
    },
]

# ── 4. Calidad de datos ───────────────────────────────────────────────────────
QUALITY_CHECKS = [
    # score = -1 en partidos pasados: reusa la query del panel.
    _reused('score_minus_one', """
        SELECT m.match_id, m.name, m.match_date
        FROM match m
        JOIN match_detail md ON md.match_id = m.match_id
        JOIN score_entity se ON se.match_detail_id = md.match_detail_id
        WHERE se.points = -1 AND m.match_date < CURRENT_DATE
        GROUP BY m.match_id, m.name, m.match_date
        ORDER BY m.match_date DESC
    """),
    {
        'key': 'status_legacy',
        'label': 'match con status legacy (%s)' % ', '.join(_STATUS_LEGACY_VALUES),
        'severity': 'low',
        # Parametrizado: el valor viaja como lista a ANY(%s).
        'count_sql': "SELECT COUNT(*) FROM match WHERE status = ANY(%s)",
        'sample_sql': "SELECT status, COUNT(*) AS n FROM match WHERE status = ANY(%s) GROUP BY status ORDER BY n DESC",
        'params': (list(_STATUS_LEGACY_VALUES),),
    },
]


def _dup_check(key, label, table, cols, severity='medium'):
    """Genera un chequeo de duplicados por clave natural.

    `cols` son las columnas que definen "la misma entidad". El count cuenta
    cuántos GRUPOS están duplicados; la muestra lista cada grupo con su conteo.
    No borra nada: solo expone los grupos para revisión manual.
    """
    col_list = ', '.join(cols)
    return {
        'key': key,
        'label': label,
        'severity': severity,
        'count_sql': f"""
            SELECT COUNT(*) FROM (
              SELECT {col_list} FROM {table}
              GROUP BY {col_list} HAVING COUNT(*) > 1
            ) t
        """,
        'sample_sql': f"""
            SELECT {col_list}, COUNT(*) AS n FROM {table}
            GROUP BY {col_list} HAVING COUNT(*) > 1
            ORDER BY n DESC
        """,
    }


# ── 5. Duplicados por clave natural ───────────────────────────────────────────
DUPLICATE_CHECKS = [
    _dup_check('dup_sport',   'sport duplicado por name',
               'sport',   ['name'], severity='high'),
    _dup_check('dup_league',  'league duplicada por (country_id, league_name, sport_id)',
               'league',  ['country_id', 'league_name', 'sport_id'], severity='high'),
    _dup_check('dup_country', 'country duplicado por country_name',
               'country', ['country_name']),
    _dup_check('dup_team',    'team duplicado por (team_name, sport_id, country_id)',
               'team',    ['team_name', 'sport_id', 'country_id']),
    _dup_check('dup_season',  'season duplicada por (league_id, season_name)',
               'season',  ['league_id', 'season_name']),
    _dup_check('dup_match',   'match duplicado por (league_id, match_date, name)',
               'match',   ['league_id', 'match_date', 'name']),
]

# Familias en orden de presentación.
CHECK_FAMILIES = [
    ('REFERENCIAL  (huérfanos por FK implícita)', REFERENTIAL_CHECKS),
    ('ESTRUCTURA   (cardinalidad / consistencia)', STRUCTURE_CHECKS),
    ('CALIDAD      (valores anómalos)',            QUALITY_CHECKS),
    ('DUPLICADOS   (clave natural)',               DUPLICATE_CHECKS),
]

# Mapa key→check para --only.
ALL_CHECKS = {c['key']: c for _, fam in CHECK_FAMILIES for c in fam}


# ══════════════════════════════════════════════════════════════════════════════
#  EJECUCIÓN DE CHEQUEOS
# ══════════════════════════════════════════════════════════════════════════════

def run_table_counts(cur):
    """Devuelve [(label, count)] con el nº de filas de cada tabla deportiva."""
    out = []
    for label, table in TABLE_COUNTS:
        out.append((label, scalar(cur, f"SELECT COUNT(*) FROM {table}")))
    return out


def run_one_check(cur, check, limit):
    """Ejecuta un chequeo y devuelve su resultado como dict serializable.

    1) count_sql → nº de inconsistencias.
    2) si hay y se piden, sample_sql + LIMIT → filas de ejemplo.
    3) si el chequeo soporta desglose por liga → top 15 de ligas afectadas.
       Se obtiene SIEMPRE (no solo con --by-league) para que el log de salida
       pueda listar qué ligas necesitan corrección; la PANTALLA solo lo muestra
       con --by-league (ver print_report).
    El LIMIT se interpola como entero validado (no hay inyección posible).
    """
    params = check.get('params')
    count = scalar(cur, check['count_sql'], params)

    sample = []
    if count and limit > 0:
        sample_sql = check['sample_sql'].rstrip().rstrip(';') + f" LIMIT {int(limit)}"
        sample = [list(r) for r in fetch(cur, sample_sql, params)]

    by_league = []
    if count and check.get('by_league_sql'):
        by_league = [list(r) for r in fetch(cur, check['by_league_sql'], params)]

    return {
        'key': check['key'],
        'label': check['label'],
        'severity': check['severity'],
        'count': count,
        'sample': sample,
        'by_league': by_league,
    }


def run_checks(cur, checks, limit):
    """Corre una lista de chequeos y devuelve sus resultados en orden."""
    return [run_one_check(cur, c, limit) for c in checks]


def worst_severity(results):
    """Severidad más alta entre los chequeos con count > 0 ('high'/'medium'/None)."""
    sevs = {r['severity'] for r in results if r['count'] > 0}
    if 'high' in sevs:
        return 'high'
    if 'medium' in sevs:
        return 'medium'
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  SALIDA EN TEXTO
# ══════════════════════════════════════════════════════════════════════════════

def _c(text, color, use_color):
    """Envuelve `text` en color ANSI salvo que --no-color esté activo."""
    return f"{color}{text}{RST}" if use_color else str(text)


def print_report(table_counts, family_results, args, db_label):
    """Imprime el reporte completo: encabezado, conteos, chequeos y resumen."""
    uc = not args.no_color
    line = '═' * 74

    print(f"\n{_c(line, WHT, uc)}")
    print(_c(f"  AUDITORÍA DE INTEGRIDAD — {db_label}", WHT, uc))
    print(_c(f"  {datetime.now():%Y-%m-%d %H:%M:%S}   (read-only)", DIM, uc))
    print(_c(line, WHT, uc))

    # ── Resumen por tabla ─────────────────────────────────────────────────────
    if table_counts:
        print(_c("\n  RESUMEN POR TABLA", CYA, uc))
        for label, count in table_counts:
            print(f"    {label:<16} {count:>10,}")

    # ── Chequeos por familia ──────────────────────────────────────────────────
    # family_results es [(fam_title, results), ...] (ver main()): el primer
    # campo es el string del título, no la tupla (título, checks).
    for fam_title, results in family_results:
        print(_c(f"\n  {fam_title}", CYA, uc))
        for r in results:
            sev = r['severity']
            count = r['count']
            mark = SEV_COLOR['ok'] if count == 0 else SEV_COLOR.get(sev, WHT)
            status = 'OK' if count == 0 else f"{count:,}"
            sev_txt = f"{sev.upper():<6}"
            status_txt = f"{status:>8}"
            print(f"    [{_c(sev_txt, mark, uc)}] {_c(status_txt, mark, uc)}  {r['label']}")

            # Muestra de filas ofensoras (solo si hay).
            for row in r['sample']:
                vals = '  '.join('' if v is None else str(v) for v in row)
                print(_c(f"         · {vals}", DIM, uc))

            # Desglose por liga: en PANTALLA solo con --by-league.
            # (El log .json/.log SIEMPRE lo incluye, ver build_log_text / build_json.)
            if args.by_league:
                for row in r['by_league']:
                    print(_c(f"         → {row}", DIM, uc))

    # ── Resumen final ─────────────────────────────────────────────────────────
    flat = [r for _, results in family_results for r in results]
    n_high = sum(1 for r in flat if r['severity'] == 'high' and r['count'])
    n_med  = sum(1 for r in flat if r['severity'] == 'medium' and r['count'])
    n_low  = sum(1 for r in flat if r['severity'] == 'low' and r['count'])
    print(_c(f"\n{line}", WHT, uc))
    print(f"  Inconsistencias activas →  "
          f"{_c(f'high: {n_high}', SEV_COLOR['high'], uc)}   "
          f"{_c(f'medium: {n_med}', SEV_COLOR['medium'], uc)}   "
          f"{_c(f'low: {n_low}', SEV_COLOR['low'], uc)}")
    print(_c(line + "\n", WHT, uc))


# Sugerencias de corrección por chequeo, para el log accionable. Conectan cada
# inconsistencia con el camino de arreglo / script fix_* ya existente. Las lee
# tanto el humano (en el .log) como, vía JSON (campo "action"), un eventual
# script actualizador aguas abajo.
ACTION_HINTS = {
    'score_minus_one':
        'Buscar y actualizar resultados de estos partidos pasados (score = -1).',
    'fk_roto_team':
        'Registrar el team faltante (scripts/fix_null_team_ids.py).',
    'detail_no_2':
        'Completar match_detail incompleto (scripts/fix_inconsistent_matches.py).',
    'match_no_detail':
        'Re-extraer el partido: no tiene ningún match_detail.',
    'detail_no_score':
        'Cargar el score_entity faltante de estos match_detail.',
    'status_legacy':
        'Normalizar status (scripts/fix_live_matches.py para los que quedaron LIVE).',
}


def _by_league_dicts(rows):
    """Convierte filas de by_league_sql a dicts machine-friendly.

    Las queries by_league de los chequeos reusados devuelven la tupla
    (sport, country, league, count) → la clave natural que un script
    actualizador usa para localizar la liga en check_points/leagues_info.json
    y re-extraer sus datos obsoletos. Si la forma no es la esperada, se
    preserva la fila cruda en 'values' para no perder información.
    """
    out = []
    for row in rows:
        if len(row) >= 5:
            # (sport, country, league, count, league_id) — las by_league_sql
            # reusadas ahora incluyen league_id al final.
            out.append({'sport': row[0], 'country': row[1], 'league': row[2],
                        'count': row[3], 'league_id': row[4]})
        elif len(row) == 4:
            out.append({'sport': row[0], 'country': row[1],
                        'league': row[2], 'count': row[3]})
        else:
            out.append({'values': list(row)})
    return out


def build_log_text(table_counts, family_results, db_label, stamp):
    """Arma el log de texto accionable (sin ANSI) que se persiste en logs/.

    A diferencia de la pantalla, el log SIEMPRE incluye, por cada inconsistencia,
    el desglose de **ligas afectadas** (top 15) cuando el chequeo lo soporta —
    p. ej. para score=-1 lista las ligas cuyos partidos necesitan que se busquen
    y actualicen los resultados. Si el chequeo no tiene desglose por liga, vuelca
    la muestra de filas ofensoras (con sus IDs).
    """
    L = []
    line = '=' * 74
    L.append(line)
    L.append(f"  AUDITORÍA DE INTEGRIDAD — {db_label}")
    L.append(f"  {stamp:%Y-%m-%d %H:%M:%S}   (read-only)")
    L.append(line)

    if table_counts:
        L.append("")
        L.append("  RESUMEN POR TABLA")
        for label, count in table_counts:
            L.append(f"    {label:<16} {count:>10,}")

    for fam_title, results in family_results:
        L.append("")
        L.append(f"  {fam_title}")
        for r in results:
            count = r['count']
            status = 'OK' if count == 0 else f"{count:,}"
            L.append(f"    [{r['severity'].upper():<6}] {status:>8}  {r['label']}")
            if not count:
                continue
            hint = ACTION_HINTS.get(r['key'])
            if hint:
                L.append(f"         → acción: {hint}")
            if r['by_league']:
                L.append("         Ligas afectadas (necesitan corrección, top 15):")
                for row in r['by_league']:
                    *desc, cnt = row
                    desc_txt = ' / '.join('' if v is None else str(v) for v in desc)
                    L.append(f"            {desc_txt:<55} {cnt:>7,}")
            elif r['sample']:
                L.append("         Muestra (sin desglose por liga):")
                for row in r['sample']:
                    vals = '  '.join('' if v is None else str(v) for v in row)
                    L.append(f"            · {vals}")

    flat = [r for _, results in family_results for r in results]
    n_high = sum(1 for r in flat if r['severity'] == 'high' and r['count'])
    n_med  = sum(1 for r in flat if r['severity'] == 'medium' and r['count'])
    n_low  = sum(1 for r in flat if r['severity'] == 'low' and r['count'])
    L.append("")
    L.append(line)
    L.append(f"  Inconsistencias activas →  high: {n_high}   medium: {n_med}   low: {n_low}")
    L.append(line)
    return '\n'.join(L) + '\n'


def build_json(table_counts, family_results, db_label, stamp):
    """Reporte machine-readable para que OTRO script actúe sobre la data obsoleta.

    Esquema estable (contrato con el actualizador aguas abajo):
        {
          "timestamp": ISO8601, "db": str, "read_only": true,
          "table_counts": {tabla: n, ...},
          "summary": {"high": n, "medium": n, "low": n},
          "checks": [
             {"key", "label", "severity", "count",
              "action": str|null,                 # qué hacer para corregir
              "affected_leagues": [{"sport","country","league","count"}],
              "sample": [[...]]}                   # filas ofensoras de ejemplo
          ]
        }
    Un actualizador lee p.ej. el check key="score_minus_one" y recorre
    "affected_leagues" para re-extraer los resultados de esas ligas.
    """
    checks = []
    for _, results in family_results:
        for r in results:
            checks.append({
                'key': r['key'],
                'label': r['label'],
                'severity': r['severity'],
                'count': r['count'],
                'action': ACTION_HINTS.get(r['key']),
                'affected_leagues': _by_league_dicts(r['by_league']),
                'sample': r['sample'],
            })
    flat = [r for _, results in family_results for r in results]
    return {
        'timestamp': stamp.strftime('%Y-%m-%dT%H:%M:%S'),
        'db': db_label,
        'read_only': True,
        'table_counts': {label: count for label, count in table_counts},
        'summary': {
            'high':   sum(1 for r in flat if r['severity'] == 'high' and r['count']),
            'medium': sum(1 for r in flat if r['severity'] == 'medium' and r['count']),
            'low':    sum(1 for r in flat if r['severity'] == 'low' and r['count']),
        },
        'checks': checks,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Auditoría read-only de integridad de sports_db (no modifica datos).")
    parser.add_argument('--only', metavar='KEY',
                        help='Ejecutar solo un chequeo por su clave (ver --list).')
    parser.add_argument('--limit', type=int, default=10,
                        help='Filas de muestra por chequeo (default 10; 0 = ninguna).')
    parser.add_argument('--by-league', action='store_true',
                        help='Mostrar desglose por liga (top 15) donde aplique.')
    parser.add_argument('--json', action='store_true',
                        help='(obsoleto / no-op) el .json ya se escribe SIEMPRE en logs/.')
    parser.add_argument('--no-color', action='store_true', help='Salida sin color.')
    parser.add_argument('--list', action='store_true',
                        help='Listar las claves de chequeo disponibles y salir.')
    args = parser.parse_args()

    # --list: solo enumerar claves y terminar (no toca la BD).
    if args.list:
        print("Chequeos disponibles:")
        for fam_title, checks in CHECK_FAMILIES:
            print(f"\n  {fam_title}")
            for c in checks:
                print(f"    {c['key']:<22} [{c['severity']:<6}] {c['label']}")
        return 0

    # Selección de familias/chequeos a correr.
    if args.only:
        if args.only not in ALL_CHECKS:
            print(f"Clave desconocida: {args.only} (usá --list)", file=sys.stderr)
            return 3
        families = [('SELECCIÓN', [ALL_CHECKS[args.only]])]
        run_table_summary = False
    else:
        families = CHECK_FAMILIES
        run_table_summary = True

    # Importamos datos de conexión solo para etiquetar la salida (sin secretos).
    try:
        from config import DB_HOST, DB_NAME
        db_label = f"{DB_HOST}/{DB_NAME}"
    except Exception:
        db_label = "(config.py no disponible)"

    conn = open_readonly_connection()
    try:
        with conn.cursor() as cur:
            table_counts = run_table_counts(cur) if run_table_summary else []
            family_results = [
                (fam, run_checks(cur, checks, args.limit))
                for fam, checks in families
            ]
    finally:
        conn.close()

    print_report(table_counts, family_results, args, db_label)

    # Persistencia SIEMPRE en logs/ (mismo timestamp para ambos archivos):
    #   .log  → humano, para visualizar (ligas afectadas + acción sugerida).
    #   .json → machine-readable, para que OTRO script lea y actualice la data
    #           obsoleta (p. ej. re-extraer resultados de partidos con score=-1).
    stamp = datetime.now()
    logs_dir = os.path.join(ROOT, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    base = os.path.join(logs_dir, f"integridad_{stamp:%Y%m%d_%H%M%S}")

    log_path = base + '.log'
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(build_log_text(table_counts, family_results, db_label, stamp))

    json_path = base + '.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(build_json(table_counts, family_results, db_label, stamp),
                  f, ensure_ascii=False, indent=2, default=str)

    print(f"  Log  → {log_path}")
    print(f"  JSON → {json_path}\n")

    # Exit code: 2 si hay 'high', 1 si solo 'medium', 0 si todo OK.
    flat = [r for _, results in family_results for r in results]
    worst = worst_severity(flat)
    return 2 if worst == 'high' else (1 if worst == 'medium' else 0)


if __name__ == '__main__':
    sys.exit(main())
