from fastapi import APIRouter
from api.services.database import get_global_stats, get_live_matches, get_news_stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def global_stats():
    """Conteos globales por deporte: ligas, equipos, partidos, jugadores."""
    return get_global_stats()


@router.get("/news")
def news_stats():
    """Total de noticias y fecha de la última noticia extraída (MAX(published))."""
    return get_news_stats()


@router.get("/live")
def live_matches():
    """Partidos con status LIVE o COMPLETED del día de hoy."""
    return get_live_matches()
