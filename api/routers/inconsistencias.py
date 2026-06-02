from fastapi import APIRouter

from api.services.database import get_inconsistencias_summary

router = APIRouter(prefix="/api/inconsistencias", tags=["inconsistencias"])


@router.get("")
def inconsistencias():
    """
    Resumen de inconsistencias en la BD.

    Devuelve:
      - summary: dict {clave: total}
      - items:   lista con label/severity/count por categoría
      - by_league: dict {clave: [{sport, country, league, count}, ...]} (top 15 c/u)
    """
    return get_inconsistencias_summary()
