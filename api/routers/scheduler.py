from fastapi import APIRouter
from api.services import scheduler as sched

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/news")
def news_scheduler_status():
    """Estado del scheduler de noticias: enabled, every_hours, last_run, next_run."""
    return sched.get_status()
