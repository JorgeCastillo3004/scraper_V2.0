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
import os
import json
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

# ── Fixtures por fecha (no solo lo que está en vivo) ─────────────────────────
# La web de SofaScore ya no usa `api.sofascore.com` ni `scheduled-events/{fecha}` a
# nivel de deporte (404). Lo que llama de verdad, observado en su propio tráfico, es:
#   /sport/{slug}/scheduled-tournaments/{fecha}/page/{n}  → torneos con partidos ese día
#   /unique-tournament/{id}/scheduled-events/{fecha}      → los partidos de ese torneo
# Ambos responden igual en www. y en api.; se usa www., que es el que usa la web.

WWW_API = 'https://www.sofascore.com/api/v1'


def call_www(driver, path, timeout=90):
    try:
        driver.set_script_timeout(timeout)
    except Exception:
        pass
    return driver.execute_async_script("""
        const cb = arguments[arguments.length - 1];
        fetch(arguments[0], {headers: {'accept': 'application/json'}})
          .then(r => r.json()).then(j => cb(j)).catch(e => cb({__error: String(e)}));
    """, WWW_API + path)


def scheduled_tournaments(driver, sport_db_name, fecha, max_paginas=6):
    """Torneos con partidos en `fecha` (YYYY-MM-DD). Devuelve lista de dicts con
    id de uniqueTournament, nombre y país (category)."""
    slug = SPORT_SLUG.get(sport_db_name)
    if not slug:
        return []
    out, pagina = [], 1
    while pagina <= max_paginas:
        data = call_www(driver, f'/sport/{slug}/scheduled-tournaments/{fecha}/page/{pagina}')
        if not isinstance(data, dict) or data.get('__error') or 'scheduled' not in data:
            break
        for item in data['scheduled']:
            t = item.get('tournament') or {}
            uniq = t.get('uniqueTournament') or {}
            out.append({
                'unique_id': uniq.get('id'),
                'tournament_id': t.get('id'),
                'name': uniq.get('name') or t.get('name', ''),
                'country': (t.get('category') or {}).get('name', ''),
                'n_events': item.get('timezoneEventCount', 0),
            })
        if not data.get('hasNextPage'):
            break
        pagina += 1
    return out


def tournament_events(driver, unique_id, fecha, sport_db_name):
    """Partidos de un torneo en una fecha, ya normalizados."""
    data = call_www(driver, f'/unique-tournament/{unique_id}/scheduled-events/{fecha}')
    if not isinstance(data, dict) or data.get('__error') or 'events' not in data:
        return []
    return [normalize(ev, sport_db_name) for ev in data['events']]


def search_tournament(driver, texto):
    """Busca torneos por nombre (para mapear ligas que no aparecen en una fecha dada)."""
    data = call_www(driver, f'/search/all?q={texto}&page=0')
    if not isinstance(data, dict):
        return []
    out = []
    for res in data.get('results', []):
        if res.get('type') not in ('uniqueTournament', 'tournament'):
            continue
        e = res.get('entity') or {}
        cat = e.get('category') or {}
        out.append({'unique_id': e.get('id'), 'name': e.get('name', ''),
                    'country': cat.get('name', ''),
                    # CRÍTICO: el buscador devuelve torneos de CUALQUIER deporte. Sin
                    # este dato, 'World Cup' de básquet se emparejaba con el Mundial de
                    # fútbol — un error que escribiría marcadores en partidos ajenos.
                    'sport': ((cat.get('sport') or {}).get('name', ''))})
    return out

# ── Emparejamiento de equipos entre proveedores ──────────────────────────────
# FlashScore abrevia ('Atl. Nacional', 'Ind. Medellin', 'D. Concepcion', 'Dep. Cali')
# y SofaScore escribe el nombre completo ('Atlético Nacional', 'Independiente
# Medellín'...). Comparar por igualdad no sirve, y la HORA tampoco ayuda en los
# partidos futuros: la BD guarda un placeholder por liga (todos los partidos de una
# jornada con la misma hora) y solo tiene hora real los que el live ya tocó.
# Por eso se compara por TOKENS admitiendo prefijos: 'atl' contra 'atletico'.

def _sim_tokens(a, b):
    """Parecido entre dos nombres ya normalizados, de 0 a 1, tolerando abreviaturas."""
    ta, tb = a.split(), b.split()
    if not ta or not tb:
        return 0.0
    def mejor(tok, otros):
        m = 0.0
        for o in otros:
            if tok == o:
                m = max(m, 1.0)
            elif len(tok) >= 3 and o.startswith(tok):      # 'atl' ⊂ 'atletico'
                m = max(m, 0.85)
            elif len(o) >= 3 and tok.startswith(o):
                m = max(m, 0.85)
            elif len(tok) <= 2 and o.startswith(tok):      # 'd.' → 'deportes' (débil)
                m = max(m, 0.35)
            elif len(o) <= 2 and tok.startswith(o):        # el mismo caso al revés:
                m = max(m, 0.35)                           # sin esto la métrica era asimétrica
        return m
    ida = sum(mejor(t, tb) for t in ta) / len(ta)
    vuelta = sum(mejor(t, ta) for t in tb) / len(tb)
    return (ida + vuelta) / 2


def similar_match(home_a, away_a, home_b, away_b):
    """Parecido entre dos enfrentamientos (0 a 1). Exige que ambos lados peguen."""
    sh = _sim_tokens(norm_name(home_a), norm_name(home_b))
    sa = _sim_tokens(norm_name(away_a), norm_name(away_b))
    return min(sh, sa) * 0.5 + ((sh + sa) / 2) * 0.5      # penaliza que un lado falle


def best_match(name_bd, eventos, umbral=0.62, margen=0.08):
    """Elige el evento de SofaScore que corresponde a `name_bd` ('Local~Visitante').

    Devuelve (evento, score, via) o (None, score, motivo). Solo acepta si supera el
    umbral Y saca al segundo mejor una diferencia mínima: si dos candidatos están
    igual de cerca, es mejor no emparejar que emparejar mal (un partido mal asignado
    escribe el marcador en el sitio equivocado)."""
    partes = str(name_bd).split('~')
    if len(partes) != 2:
        return None, 0.0, 'nombre mal formado'
    puntuados = sorted(
        ((similar_match(partes[0], partes[1], e['home'], e['away']), e) for e in eventos),
        key=lambda x: -x[0])
    if not puntuados:
        return None, 0.0, 'sin candidatos'
    mejor_score, mejor_ev = puntuados[0]
    segundo = puntuados[1][0] if len(puntuados) > 1 else 0.0
    if mejor_score < umbral:
        return None, mejor_score, 'por debajo del umbral'
    if mejor_score - segundo < margen:
        return None, mejor_score, f'ambiguo (2º={segundo:.2f})'
    return mejor_ev, mejor_score, 'similitud'

# ── Mapa de equipos (la verdad, por encima de la similitud) ──────────────────
# La similitud acierta, pero en producción no basta: un empate de puntuación
# escribiría el marcador en el partido equivocado. Por eso las correspondencias
# verificadas se congelan en check_points/sofascore_teams_map.json y mandan sobre
# cualquier heurística. La similitud queda solo para lo que aún no está mapeado.

_TEAMS_MAP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'check_points', 'sofascore_teams_map.json')
_TEAMS_CACHE = {}


def load_teams_map(path=_TEAMS_MAP_PATH):
    """Carga (y cachea) el mapa de equipos. Devuelve {} si no existe todavía."""
    if not _TEAMS_CACHE:
        try:
            with open(path, encoding='utf-8') as f:
                _TEAMS_CACHE.update(json.load(f))
        except Exception:
            _TEAMS_CACHE['__vacio__'] = True
    return {k: v for k, v in _TEAMS_CACHE.items() if k != '__vacio__'}


_OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'check_points', 'sofascore_overrides.json')
_OVERRIDES_CACHE = {}


def load_overrides(path=_OVERRIDES_PATH):
    """Correcciones manuales del mapeo. Mandan sobre lo generado automáticamente:
    son la vía para fijar una correspondencia sin depender de una heurística."""
    if not _OVERRIDES_CACHE:
        try:
            with open(path, encoding='utf-8') as f:
                _OVERRIDES_CACHE.update(json.load(f))
        except Exception:
            _OVERRIDES_CACHE['_vacio'] = True
    return _OVERRIDES_CACHE


def team_to_db(nombre_ss, sport, liga_clave, mapa=None):
    """Nombre de equipo de SofaScore -> nombre en la BD, si está mapeado.
    Devuelve (nombre_bd, mapeado?). Si no hay entrada, devuelve el original.
    Primero se miran las correcciones manuales; luego el mapa generado."""
    manual = ((load_overrides().get('teams', {}) or {})
              .get(sport, {}).get(liga_clave, {}) or {}).get(nombre_ss)
    if manual:
        return manual, True
    mapa = mapa if mapa is not None else load_teams_map()
    entrada = (mapa.get(sport, {}).get(liga_clave, {}) or {}).get(nombre_ss)
    if isinstance(entrada, dict) and entrada.get('bd'):
        return entrada['bd'], True
    if isinstance(entrada, str):
        return entrada, True
    return nombre_ss, False


def match_name_db(ev, sport, liga_clave, mapa=None):
    """El 'Local~Visitante' que tendría este evento con los nombres de la BD."""
    mapa = mapa if mapa is not None else load_teams_map()
    h, ok_h = team_to_db(ev['home'], sport, liga_clave, mapa)
    a, ok_a = team_to_db(ev['away'], sport, liga_clave, mapa)
    return f'{h}~{a}', (ok_h and ok_a)
