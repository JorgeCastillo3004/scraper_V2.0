import json
from fastapi import APIRouter
from api.config import CONFIG_PATH

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
def get_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@router.patch("")
def update_config(payload: dict):
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    cfg.update(payload)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)
    return cfg
