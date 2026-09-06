from fastapi import APIRouter

from api.services import history as svc

router = APIRouter(prefix="/api", tags=["history"])


# ── Visor de db_history ───────────────────────────────────────────────────────

@router.get("/db_history")
def db_history_list():
    """Lista de snapshots (idx + timestamp + totales) para el navegador ◀ ▶."""
    return {"snapshots": svc.list_snapshots()}


@router.get("/db_history/{idx}")
def db_history_comparison(idx: int):
    """Texto de la comparación snapshot[idx] vs el anterior — tal cual la salida del script."""
    return svc.comparison_text(idx)


@router.post("/db_history/snapshot")
def db_history_snapshot():
    """Toma un snapshot NUEVO (consulta el remoto, solo SELECT — autorizado)."""
    return svc.take_snapshot()


# ── Estado por liga desde los logs ──────────────────────────────────────────────

@router.get("/leagues_status")
def leagues_status():
    """Última ejecución + cobertura por liga, leído de logs/update_matches_*.log."""
    return {"leagues": svc.leagues_status_from_logs()}
