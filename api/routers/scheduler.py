from fastapi import APIRouter
from api.services import scheduler as sched

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/news")
def news_scheduler_status():
    """Estado del scheduler de noticias: enabled, every_hours, last_run, next_run."""
    return sched.get_status()


@router.get("/inconsistencias")
def fix_scheduler_status():
    """Estado del trigger diario de corrección de team_id inexistente:
    enabled, at_hour, apply, last_run, next_run, last_error, running."""
    return sched.get_fix_status()


@router.post("/inconsistencias/run")
def fix_scheduler_run_now():
    """Dispara la corrección AHORA (manual, sin esperar la hora programada)."""
    return sched.run_fix_now()


@router.get("/pending-complete")
def pending_complete_status():
    """Estado de la auto-completación de partidos en score=-1 (residuo del live):
    enabled, every_minutes, apply, last_run, next_run, last_error, running."""
    return sched.get_pending_complete_status()


@router.post("/pending-complete/run")
def pending_complete_run_now():
    """Dispara la auto-completación AHORA (manual, sin esperar EVERY_MINUTES)."""
    return sched.run_pending_complete_now()
