from fastapi import APIRouter

from api.services import driver_manager as dm

router = APIRouter(prefix="/api/live_driver", tags=["live_driver"])


@router.get("/status")
def live_driver_status():
    """Estado del driver dedicado de Live (independiente del de corrección)."""
    return dm.live.status()


@router.post("/start")
def live_driver_start():
    """Lanza el driver de Live (start_driver.py → tmp/live_driver.json) si no hay uno vivo."""
    return dm.live.start()


@router.post("/stop")
def live_driver_stop():
    """Detiene SOLO el driver de Live (SIGTERM limpio, nunca pkill firefox)."""
    return dm.live.stop()
