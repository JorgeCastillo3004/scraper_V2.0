"""
live_windows.py — Ventanas temporales de navegación por deporte (RL2)
--------------------------------------------------------------------
Calcula, por deporte, la franja horaria del día en la que hay partidos, para que
el LIVE navegue SOLO dentro de esa franja y se saltee los deportes sin partidos.

Reglas de seguridad (no-negociables, ver documentacion/OPTIMIZACION_LIVE.md §6):
  - **fail-open**: ante cualquier error / dato dudoso → `compute_sport_windows`
    devuelve None y `should_poll` devuelve True (pollear TODO; nunca perder un partido).
  - **el status manda**: si un deporte tiene ≥1 partido LIVE en DB, se polea aunque la
    ventana ya haya cerrado (hasta que pase a COMPLETED).

Fechas en **UTC** (decisión de Jorge): el scraper persiste match_date/start_time en UTC,
así que "HOY" se calcula con `datetime.utcnow()`. Se combinan match_date+start_time en un
timestamp completo para no romperse con partidos que cruzan la medianoche.

El módulo es READ-ONLY sobre la BD (solo SELECT).
"""

from datetime import datetime, timedelta

try:
    from data_base import getdb
except Exception:  # import flexible según desde dónde se ejecute
    from src.data_base import getdb


# Márgenes por deporte (nombre DB = sport.name, Title Case). Valores de
# OPTIMIZACion_LIVE.md §5; configurables luego. (pre_min, after_min) donde
# after_min = duración_típica + margen_post (cuánto sigue "abierta" tras el ÚLTIMO inicio).
_MARGINS = {
    'baseball':       (15, 4 * 60 + 90),   # ~3-4h + extra innings
    'basketball':     (15, 150 + 45),
    'football':       (15, 120 + 45),
    'am. football':   (15, 210 + 60),      # NFL
    'american football': (15, 210 + 60),
    'tennis':         (15, 5 * 60),        # muy variable -> generoso
    'ice hockey':     (15, 150 + 45),
    'handball':       (15, 120 + 45),
    'volleyball':     (15, 150 + 45),
}
_DEFAULT_MARGIN = (15, 4 * 60)             # genérico generoso (fail hacia pollear)


def today_utc():
    """Fecha de HOY en UTC (las fechas en DB están en UTC)."""
    return datetime.utcnow().date()


def _margin(sport_db_name):
    return _MARGINS.get((sport_db_name or '').strip().lower(), _DEFAULT_MARGIN)


def compute_sport_windows():
    """Devuelve {sport_db_name: {'open': dt, 'close': dt, 'has_live': bool, 'n': int}}
    en UTC, o **None** ante cualquier error (fail-open → el caller pollea todo).

    - ventana = [min(match_date+start_time) − pre , max(match_date+start_time) + after]
    - has_live: ≥1 partido en status LIVE para ese deporte (hoy o ayer; cubre overruns).
    """
    con = None
    try:
        today = today_utc()
        con = getdb()
        cur = con.cursor()
        # Partidos de HOY (UTC) por deporte: bordes de la ventana + conteo.
        cur.execute(
            """
            SELECT s.name,
                   MIN(m.match_date + m.start_time),
                   MAX(m.match_date + m.start_time),
                   bool_or(m.status = 'LIVE'),
                   COUNT(*)
              FROM match m
              JOIN league l ON l.league_id = m.league_id
              JOIN sport  s ON s.sport_id  = l.sport_id
             WHERE m.match_date = %s
             GROUP BY s.name
            """,
            (today,),
        )
        rows = cur.fetchall()
        # has_live amplio: ≥1 LIVE en las últimas 48h (cubre partidos que arrancaron ayer
        # y siguen en vivo cruzando la medianoche).
        cur.execute(
            """
            SELECT s.name, bool_or(m.status = 'LIVE')
              FROM match m
              JOIN league l ON l.league_id = m.league_id
              JOIN sport  s ON s.sport_id  = l.sport_id
             WHERE m.match_date >= %s
             GROUP BY s.name
            """,
            (today - timedelta(days=1),),
        )
        live_map = {r[0]: bool(r[1]) for r in cur.fetchall()}
        cur.close()

        windows = {}
        for name, first_dt, last_dt, has_live_today, n in rows:
            pre, after = _margin(name)
            windows[name] = {
                'open':  (first_dt - timedelta(minutes=pre)) if first_dt else None,
                'close': (last_dt + timedelta(minutes=after)) if last_dt else None,
                'has_live': bool(has_live_today) or live_map.get(name, False),
                'n': int(n),
            }
        # Deportes sin fixtures hoy pero con un partido LIVE (overrun de ayer): mantener vivos.
        for name, hl in live_map.items():
            if hl and name not in windows:
                windows[name] = {'open': None, 'close': None, 'has_live': True, 'n': 0}
        return windows
    except Exception as e:
        print('[VENTANA] error calculando ventanas: %s: %s -> fail-open (pollear todo)'
              % (type(e).__name__, e))
        return None
    finally:
        try:
            if con is not None:
                con.close()
        except Exception:
            pass


def should_poll(sport_db_name, windows, now=None):
    """¿Hay que navegar este deporte AHORA? Aplica fail-open + 'el status manda'.

    True si: windows es None (falló el cálculo) | el deporte no está / 0 fixtures
    (ambiguo) | tiene un partido LIVE | now ∈ [open, close]. False solo cuando hay
    fixtures, NO hay LIVE y now está fuera de la ventana.
    """
    if windows is None:
        return True                      # fail-open
    now = now or datetime.utcnow()
    w = windows.get(sport_db_name)
    if not w:
        return True                      # deporte ausente / 0 fixtures hoy -> ambiguo -> pollear
    if w.get('has_live'):
        return True                      # el status manda
    if w.get('n', 0) == 0:
        return True
    o, c = w.get('open'), w.get('close')
    if o is None or c is None:
        return True                      # sin horario fiable -> pollear
    return o <= now <= c


def window_label(sport_db_name, windows):
    """Texto corto para log: 'hasta ~HH:MM UTC' (o '' si no aplica)."""
    if not windows:
        return ''
    w = windows.get(sport_db_name)
    if w and w.get('close'):
        return 'hasta ~%s UTC' % w['close'].strftime('%H:%M')
    return ''
