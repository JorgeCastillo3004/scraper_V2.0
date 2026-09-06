"""
Registro de ligas con partidos inexistentes detectados por el LIVE
------------------------------------------------------------------
Cuando `milestone7.live_games` ve un partido en vivo cuyo `match_id` NO está en
la BD (`[DB-SKIP]`), en vez de descartarlo lo registra acá. Otro flujo (la
sección Inconsistencias del panel / un script de extracción) toma estas ligas y
las completa.

Formato (`check_points/live_missing_leagues.json`), DEDUPLICADO por liga:

    {
      "updated_at": "ISO",
      "leagues": {
        "<SPORT>|<COUNTRY>|<LEAGUE>": {
          "sport": "FOOTBALL", "country": "ARGENTINA", "league": "Liga Profesional",
          "count": 7,                       # detecciones acumuladas
          "first_seen": "ISO", "last_seen": "ISO",
          "status": "pending",              # pending | resolved | ignored
          "sample_matches": ["Home~Away", ...]   # hasta _SAMPLE_CAP
        }
      }
    }

Diseño:
  - Read-modify-write atómico en CADA registro: preserva los cambios de estado
    que haga el panel (no cachea en memoria para no pisarlos).
  - NUNCA borra entradas ni baja el `status` (si reaparece una liga 'resolved',
    suma count + last_seen pero respeta el status que puso el usuario).
"""

import json
import os
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(_ROOT, 'check_points', 'live_missing_leagues.json')

_SAMPLE_CAP = 10


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
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    tmp = REGISTRY_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REGISTRY_PATH)


def _key(sport: str, country: str, league: str) -> str:
    return f'{sport}|{country}|{league}'


def record_missing_league(sport, country, league, match_name=None, source='live'):
    """Registra (o actualiza) una liga con partido inexistente detectado por live.

    Robusto: cualquier excepción se traga para NO romper el ciclo del live."""
    try:
        sport = (sport or '').strip()
        country = (country or '').strip()
        league = (league or '').strip()
        if not (country or league):
            return
        now = datetime.now().isoformat()
        data = _load()
        leagues = data['leagues']
        k = _key(sport, country, league)
        entry = leagues.get(k)
        if entry is None:
            entry = {
                'sport': sport, 'country': country, 'league': league,
                'count': 0, 'first_seen': now, 'last_seen': now,
                'status': 'pending', 'sample_matches': [],
                'missing_date': None, 'source': source,
            }
            leagues[k] = entry
        entry['count'] = int(entry.get('count', 0)) + 1
        entry['last_seen'] = now
        entry['missing_date'] = datetime.utcnow().date().isoformat()  # día UTC del faltante
        entry['source'] = source
        if match_name:
            samples = entry.setdefault('sample_matches', [])
            if match_name not in samples and len(samples) < _SAMPLE_CAP:
                samples.append(match_name)
        _save_atomic(data)
    except Exception:
        pass
