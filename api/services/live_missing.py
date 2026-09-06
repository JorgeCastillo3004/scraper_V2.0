"""
Servicio: ligas con partidos inexistentes detectados por el LIVE
----------------------------------------------------------------
Lee `check_points/live_missing_leagues.json` (lo escribe `src/live_missing.py`
desde el ciclo del live) y lo enriquece para la sección Inconsistencias del panel:

  - `in_leagues_info`: ¿la liga ya está registrada en leagues_info.json?
    (clave `{COUNTRY}_{LEAGUE}` o match por league_name dentro del deporte).
    Si está, es **extractable**: un script de ligas/teams puede completarla.
  - `match_key` / `sport_key`: la clave de leagues_info si se encontró.

También permite cambiar el `status` de una entrada (pending/resolved/ignored)
desde el panel. NUNCA borra datos (solo INSERT/UPDATE del JSON).
"""

import json
import os
from datetime import datetime

from api.config import LEAGUES_INFO_PATH, CHECK_DIR

REGISTRY_PATH = os.path.join(CHECK_DIR, 'live_missing_leagues.json')
_VALID_STATUS = ('pending', 'resolved', 'ignored')


def _load() -> dict:
    try:
        with open(REGISTRY_PATH, encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('leagues'), dict):
            return data
    except Exception:
        pass
    return {'updated_at': None, 'leagues': {}}


def _save_atomic(data: dict):
    data['updated_at'] = datetime.now().isoformat()
    os.makedirs(CHECK_DIR, exist_ok=True)
    tmp = REGISTRY_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY_PATH)


def _load_leagues_info() -> dict:
    try:
        with open(LEAGUES_INFO_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _resolve_in_leagues_info(li: dict, sport: str, country: str, league: str):
    """Devuelve (sport_key, league_key) de leagues_info si la liga detectada por
    el live coincide; None si no está registrada (liga realmente nueva)."""
    sport = (sport or '').upper()
    sport_block = li.get(sport)
    if not isinstance(sport_block, dict):
        return None
    # 1) Coincidencia exacta por clave {COUNTRY}_{LEAGUE}
    candidate = f'{country}_{league}'
    if candidate in sport_block:
        return (sport, candidate)
    # 2) Fallback: match por league_name (case-insensitive) dentro del deporte
    lname = (league or '').strip().lower()
    cname = (country or '').strip().lower()
    for key, info in sport_block.items():
        if not isinstance(info, dict):
            continue
        if (info.get('league_name', '').strip().lower() == lname
                and (cname in key.lower() or not cname)):
            return (sport, key)
    return None


def get_live_missing(fresh: bool = False) -> dict:
    """Lista de ligas detectadas por el live, enriquecida con su estado de
    registro en leagues_info. `fresh` es informativo (siempre lee del disco)."""
    data = _load()
    li = _load_leagues_info()
    items = []
    counts = {'pending': 0, 'resolved': 0, 'ignored': 0,
              'in_leagues_info': 0, 'new': 0}
    for key, e in data.get('leagues', {}).items():
        resolved = _resolve_in_leagues_info(
            li, e.get('sport'), e.get('country'), e.get('league'))
        in_li = resolved is not None
        status = e.get('status', 'pending')
        counts[status] = counts.get(status, 0) + 1
        counts['in_leagues_info' if in_li else 'new'] += 1
        items.append({
            'key':            key,
            'sport':          e.get('sport'),
            'country':        e.get('country'),
            'league':         e.get('league'),
            'count':          e.get('count', 0),
            'first_seen':     e.get('first_seen'),
            'last_seen':      e.get('last_seen'),
            'status':         status,
            'sample_matches': e.get('sample_matches', []),
            'in_leagues_info': in_li,
            'sport_key':      resolved[0] if resolved else None,
            'league_key':     resolved[1] if resolved else None,
        })
    # Orden: pendientes primero, luego por más detecciones.
    items.sort(key=lambda x: (x['status'] != 'pending', -x['count']))
    return {
        'updated_at': data.get('updated_at'),
        'total': len(items),
        'counts': counts,
        'items': items,
    }


def set_status(key: str, status: str) -> dict:
    if status not in _VALID_STATUS:
        return {'ok': False, 'error': f'status inválido: {status}'}
    data = _load()
    entry = data.get('leagues', {}).get(key)
    if entry is None:
        return {'ok': False, 'error': f'liga no encontrada: {key}'}
    entry['status'] = status
    _save_atomic(data)
    return {'ok': True, 'key': key, 'status': status}
