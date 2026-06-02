from fastapi import APIRouter
from api.services import driver_manager as dm

router = APIRouter(prefix="/api/driver", tags=["driver"])


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
