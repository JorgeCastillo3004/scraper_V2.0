import json
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.services import process_manager as pm
from api.config import PROJECT_ROOT, SECTIONS

router = APIRouter(prefix="/api", tags=["control"])


class LeagueSelection(BaseModel):
    sport: str
    key: str


class StartParams(BaseModel):
    workers:  int = 2
    sports:   list[str] = []
    leagues:  list[LeagueSelection] = []
    days:     int = 31    # solo para news
    interval: int = 60    # solo para live (segundos entre ciclos)
    # update_matches (completar partidos pendientes)
    mode:           str  = 'completo'   # 'rapido' | 'completo'
    solo_sin_stats: bool = False        # backfill: solo COMPLETED sin statistic
    apply:          bool = False        # escribir en DB (default dry-run)


@router.post("/{section}/start")
def start(section: str, params: StartParams):
    if section not in SECTIONS:
        raise HTTPException(404, f"Sección no encontrada: {section}")
    result = pm.start_process(section, params.model_dump())
    if not result['ok']:
        raise HTTPException(409, result['error'])
    return result


@router.post("/{section}/stop")
def stop(section: str):
    if section not in SECTIONS:
        raise HTTPException(404)
    pm.stop_process(section)
    return {'ok': True}


@router.post("/{section}/pause")
def pause(section: str):
    if section not in SECTIONS:
        raise HTTPException(404)
    pm.pause_process(section)
    return {'ok': True}


@router.post("/{section}/resume")
def resume(section: str):
    if section not in SECTIONS:
        raise HTTPException(404)
    pm.resume_process(section)
    return {'ok': True}


@router.get("/{section}/status")
def status(section: str):
    if section not in SECTIONS:
        raise HTTPException(404)
    return pm.get_status(section)


@router.get("/status/all")
def status_all():
    return {s: pm.get_status(s) for s in SECTIONS}


@router.get("/live/screenshots")
def live_screenshots():
    latest_dir = os.path.join(PROJECT_ROOT, 'logs', 'screenshots', 'live', 'latest')
    if not os.path.isdir(latest_dir):
        return {'workers': []}

    meta_path = os.path.join(latest_dir, 'live_0.json')
    png_path  = os.path.join(latest_dir, 'live_0.png')
    if not os.path.isfile(meta_path) or not os.path.isfile(png_path):
        return {'workers': []}

    try:
        with open(meta_path, encoding='utf-8') as f:
            metadata = json.load(f)
    except Exception:
        return {'workers': []}

    return {'workers': [{
        'worker_id':   0,
        'label':       metadata.get('label', ''),
        'captured_at': metadata.get('captured_at'),
        'league':      metadata.get('label', '—'),
        'url':         metadata.get('url', ''),
        'image_url':   f"{metadata.get('image_url', '')}?t={int(os.path.getmtime(png_path))}",
    }]}


@router.get("/teams/screenshots")
def team_screenshots():
    latest_dir = os.path.join(PROJECT_ROOT, 'logs', 'screenshots', 'teams', 'latest')
    if not os.path.isdir(latest_dir):
        return {'workers': []}

    workers = []
    for name in sorted(os.listdir(latest_dir)):
        if not name.endswith('.json'):
            continue

        path = os.path.join(latest_dir, name)
        try:
            with open(path, encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception:
            continue

        image_path = os.path.join(latest_dir, f"worker_{metadata.get('worker_id')}.png")
        if not os.path.isfile(image_path):
            continue

        workers.append({
            'worker_id': metadata.get('worker_id'),
            'label': metadata.get('label', ''),
            'captured_at': metadata.get('captured_at'),
            'league': metadata.get('league', '—'),
            'url': metadata.get('url', ''),
            'image_url': f"{metadata.get('image_url', '')}?t={int(os.path.getmtime(image_path))}",
        })

    workers.sort(key=lambda item: item.get('worker_id', 0))
    return {'workers': workers}
