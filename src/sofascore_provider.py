"""Proveedor de respaldo: SofaScore (solo LECTURA, solo sección LIVE).

Traduce lo que devuelve la API de SofaScore a la MISMA estructura que ya produce
`live_function.py` para FlashScore, de modo que la escritura siga pasando por
`get_match_id` / `update_score` / `update_match_status` y **la base de datos no
cambie en nada**.

Dos cosas que condicionan el diseño:

1. SofaScore responde **403 a cualquier cliente HTTP** (probado sin cabeceras, con
   User-Agent de navegador, con Origin/Referer, en api./www./.app). Solo contesta a un
   `fetch` hecho DENTRO de una página suya, así que todas las llamadas van por
   `driver.execute_async_script`.
2. Sus rutas cambian sin aviso: `scheduled-events/{fecha}` ya devuelve 404 y
   `events/live` sigue vivo. Por eso las rutas están aisladas aquí y en un solo sitio.

Este módulo NO escribe en la base de datos ni decide nada: solo lee y normaliza.
"""
import re
import time
from datetime import datetime, timezone

API = 'https://api.sofascore.com/api/v1'
HOME = 'https://www.sofascore.com'

# deporte en la BD (sport.name, Title Case) -> slug de SofaScore
SPORT_SLUG = {
    'Football': 'football',
    'Baseball': 'baseball',
    'Basketball': 'basketball',
    'Hockey': 'ice-hockey',
    'American Football': 'american-football',
    'Tennis': 'tennis',
}

# status.type de SofaScore -> valor de match.status en la BD.
# La BD usa SCHEDULED / LIVE / COMPLETED (+ OLD_SEASON, que el live no escribe).
STATUS_MAP = {
    'inprogress': 'LIVE',
    'finished':   'COMPLETED',
    'notstarted': 'SCHEDULED',
    'postponed':  'SCHEDULED',
    'canceled':   'SCHEDULED',
    'suspended':  'LIVE',
}


def ensure_context(driver, timeout=20):
    """Deja el navegador en sofascore.com, que es el origen desde el que la API
    responde. Si ya está, no navega (no perturba lo que estuviera haciendo)."""
    if 'sofascore' in (getattr(driver, 'current_url', '') or ''):
        return
    driver.get(HOME)
    fin = time.time() + timeout
    while time.time() < fin:
        if 'sofascore' in (driver.current_url or ''):
            time.sleep(2)      # margen para que cargue el contexto
            return
        time.sleep(0.5)


def call(driver, path, timeout=90):
    """GET a la API desde dentro de la página. Devuelve dict; {'__error': ...} si falla."""
    try:
        driver.set_script_timeout(timeout)
    except Exception:
        pass
    return driver.execute_async_script("""
        const cb = arguments[arguments.length - 1];
        fetch(arguments[0], {headers: {'accept': 'application/json'}})
          .then(r => r.json())
          .then(j => cb(j))
          .catch(e => cb({__error: String(e)}));
    """, API + path)


def live_events(driver, sport_db_name):
    """Eventos EN VIVO de un deporte, ya normalizados. Lista vacía si no hay o falla."""
    slug = SPORT_SLUG.get(sport_db_name)
    if not slug:
        return []
    data = call(driver, f'/sport/{slug}/events/live')
    if not isinstance(data, dict) or data.get('__error') or 'events' not in data:
        return []
    return [normalize(ev, sport_db_name) for ev in data['events']]


def normalize(ev, sport_db_name):
    """Un evento de SofaScore -> la forma que entiende el flujo del live.

    `country` y `league` salen tal cual de SofaScore: la traducción a los nombres de
    la BD la hace la capa de alias, no este módulo (aquí no se inventa nada)."""
    t     = ev.get('tournament') or {}
    cat   = t.get('category') or {}
    uniq  = t.get('uniqueTournament') or {}
    home  = (ev.get('homeTeam') or {}).get('name', '')
    away  = (ev.get('awayTeam') or {}).get('name', '')
    st    = ev.get('status') or {}
    ts    = ev.get('startTimestamp')
    dt    = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
    fecha = dt.date().isoformat() if dt else None
    hora  = dt.strftime('%H:%M') if dt else None      # UTC, como persiste el scraper
    return {
        'source':        'sofascore',
        'event_id':      ev.get('id'),
        'sport':         sport_db_name,
        'country_raw':   cat.get('name', ''),          # p.ej. 'Belgium'
        'league_raw':    t.get('name', ''),            # p.ej. 'Pro League'
        'league_unique': uniq.get('name', ''),         # alternativa de nombre
        'season':        (ev.get('season') or {}).get('name', ''),
        'home':          home,
        'away':          away,
        'match_name':    f'{home}~{away}',             # el formato de match.name en la BD
        'match_date':    fecha,                        # UTC, como persiste el scraper
        'start_time':    hora,                         # UTC 'HH:MM'
        'score_home':    (ev.get('homeScore') or {}).get('current'),
        'score_away':    (ev.get('awayScore') or {}).get('current'),
        'status':        STATUS_MAP.get(st.get('type'), 'SCHEDULED'),
        'status_raw':    st.get('description', ''),
    }


# ── Normalización de nombres (para cruzar con la BD) ─────────────────────────
_GENERICOS = {'fc', 'cf', 'sc', 'ac', 'cd', 'club', 'de', 'la', 'el', 'the', 'of', 'and'}


def norm_name(s):
    """Forma canónica para comparar nombres entre proveedores: sin acentos, sin
    puntuación, en minúsculas y sin las palabras de relleno que cada sitio pone a
    su manera. NO se usa para escribir, solo para emparejar."""
    try:
        from unidecode import unidecode
        s = unidecode(str(s))
    except Exception:
        s = str(s)
    s = re.sub(r'[^A-Za-z0-9 ]', ' ', s).lower()
    toks = [t for t in s.split() if t not in _GENERICOS]
    return ' '.join(toks) or s.strip()
