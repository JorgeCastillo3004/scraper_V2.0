import json
from fastapi import APIRouter
from api.services import driver_manager as dm
from api.services import driver_registry as dr
from api.config import CONFIG_PATH

router = APIRouter(prefix="/api/driver", tags=["driver"])


@router.get("/registry")
def driver_registry():
    """Registro CENTRAL de todos los drivers: id, rol, estado (ready/busy/closed),
    dueño (script que lo usa), pid y puerto. Reconciliado contra la realidad."""
    return dr.list_drivers()


@router.get("/status")
def driver_status():
    """Estado del driver dedicado del panel (vivo/muerto, headless, pid)."""
    return dm.status()


@router.post("/start")
def driver_start():
    """Lanza el driver dedicado (start_driver.py) si no hay uno vivo."""
    return dm.start()


@router.post("/stop")
def driver_stop():
    """Detiene SOLO el driver del panel (SIGTERM limpio, nunca pkill firefox)."""
    return dm.stop()


@router.get("/headless")
def get_headless():
    """Preferencia de headless del driver de CORRECCIÓN (CONFIG.json → FIX_DRIVER_HEADLESS).
    `effective` = el valor que se usará en el próximo (re)lanzamiento."""
    v = None
    try:
        with open(CONFIG_PATH) as f:
            v = json.load(f).get('FIX_DRIVER_HEADLESS', None)
    except Exception:
        pass
    return {"headless": v, "effective": dm._fix_headless()}


@router.post("/headless")
def set_headless(payload: dict):
    """Setea FIX_DRIVER_HEADLESS en CONFIG.json. Toma efecto al PRÓXIMO (re)lanzamiento
    del driver (no reinicia el driver actual)."""
    val = bool(payload.get("headless"))
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg['FIX_DRIVER_HEADLESS'] = val
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)
    return {"ok": True, "headless": val,
            "note": "Aplica al próximo (re)lanzamiento del driver de corrección."}
