import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.config import LEAGUES_INFO_PATH
from api.services.database import get_all_league_stats, get_sports_from_db

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


def _load() -> dict:
    with open(LEAGUES_INFO_PATH) as f:
        return json.load(f)

def _save(data: dict):
    with open(LEAGUES_INFO_PATH, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


@router.get("")
def get_leagues(sport: str = None):
    """Todas las ligas con estadísticas de DB."""
    data = _load()
    all_stats = get_all_league_stats()
    result = []
    for sport_name, leagues in data.items():
        if sport and sport_name != sport.upper():
            continue
        if not isinstance(leagues, dict):
            continue
        for key, info in leagues.items():
            if not isinstance(info, dict):
                continue
            league_id = info.get('league_id', '')
            teams_creation = info.get('teams_creation', {})
            stats = all_stats.get(league_id, {'matches': 0, 'results': 0, 'fixtures': 0, 'teams': 0})
            result.append({
                'sport':             sport_name,
                'key':               key,
                'league_name':       info.get('league_name', key),
                'league_id':         league_id,
                'teams_expected':    info.get('teams', 0),
                'teams_db':          stats['teams'],
                'matches_db':        stats['matches'],
                'results_db':        stats['results'],
                'fixtures_db':       stats['fixtures'],
                'extract_results':   info.get('extract_results',  {}).get('extract', False),
                'extract_fixtures':  info.get('extract_fixtures', {}).get('extract', False),
                'teams_extract':     teams_creation.get('extract', False),
                'teams_status':      teams_creation.get('status', ''),
                'last_team_created': teams_creation.get('last_team_created', ''),
            })
    return result


class TogglePayload(BaseModel):
    field: str   # 'extract_results' | 'extract_fixtures' | 'teams_creation'
    value: bool


@router.patch("/{sport}/{key}")
def toggle_league(sport: str, key: str, payload: TogglePayload):
    """Habilita o deshabilita una liga para una sección específica."""
    valid_fields = {'extract_results', 'extract_fixtures', 'teams_creation'}
    if payload.field not in valid_fields:
        raise HTTPException(400, f"Campo inválido. Debe ser uno de: {valid_fields}")

    data = _load()
    sport_up = sport.upper()

    if sport_up not in data or key not in data[sport_up]:
        raise HTTPException(404, f"Liga no encontrada: {sport_up}/{key}")

    league = data[sport_up][key]
    if payload.field not in league:
        league[payload.field] = {}
    league[payload.field]['extract'] = payload.value

    _save(data)
    return {'ok': True, 'sport': sport_up, 'key': key,
            'field': payload.field, 'value': payload.value}


@router.get("/sports")
def get_sports():
    """Lista de deportes disponibles en DB, mapeados al nombre usado por checkpoints."""
    return get_sports_from_db()
