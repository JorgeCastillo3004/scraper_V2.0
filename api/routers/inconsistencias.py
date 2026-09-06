from fastapi import APIRouter
from pydantic import BaseModel

from api.services.database import get_inconsistencias_summary
from api.services import live_missing as lm

router = APIRouter(prefix="/api/inconsistencias", tags=["inconsistencias"])


@router.get("")
def inconsistencias(fresh: bool = False):
    """
    Resumen de inconsistencias en la BD.

    `fresh=1` saltea el caché de 60 s y consulta la BD (botón Refrescar manual).

    Devuelve:
      - summary: dict {clave: total}
      - items:   lista con label/severity/count por categoría
      - by_league: dict {clave: [{sport, country, league, count}, ...]} (top 15 c/u)
    """
    return get_inconsistencias_summary(fresh=fresh)


# ── Ligas con partidos inexistentes detectadas por el LIVE ────────────────────

class LiveMissingStatus(BaseModel):
    key: str
    status: str   # pending | resolved | ignored


@router.get("/live-missing")
def live_missing(fresh: bool = False):
    """Ligas que el scraper live vio en vivo pero NO estaban en la BD.

    Cada item incluye `in_leagues_info` (si ya está registrada y es extractable),
    contador, primera/última detección, muestras de partidos y estado."""
    return lm.get_live_missing(fresh=fresh)


@router.post("/live-missing/status")
def live_missing_set_status(payload: LiveMissingStatus):
    """Cambia el estado de una liga detectada: pending / resolved / ignored."""
    return lm.set_status(payload.key, payload.status)
