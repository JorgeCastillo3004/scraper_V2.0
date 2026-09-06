import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from api.routers import control, leagues, stats, app_config, inconsistencias, scheduler, driver, live_driver, history
from api.ws import logs as ws_logs
import api.services.process_manager as pm
import api.services.scheduler as sched
from api.config import PROJECT_ROOT


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Guardar el event loop para que el process_manager pueda usarlo desde threads
    pm._event_loop = asyncio.get_running_loop()
    # Arrancar el scheduler embebido de noticias (lee EXTRACT_NEWS de CONFIG.json).
    # ENGINE_OWNS_SCHEDULER=1 → lo corre el proceso `scraper-engine` (engine_runner.py)
    # y la API NO debe arrancarlo (evita que corra duplicado). Default (sin la var o
    # '0') = comportamiento histórico: el scheduler vive en la API.
    _engine_owns = os.environ.get('ENGINE_OWNS_SCHEDULER', '0') == '1'
    if not _engine_owns:
        sched.start_scheduler()
    yield
    # Cleanup al apagar: parar el scheduler y los procesos en ejecución.
    # EXCEPCIÓN: 'live' jamás se detiene desde acá (regla no negociable del
    # proyecto). El live tiene su propio driver y debe sobrevivir a reinicios de
    # la API; se controla explícitamente desde el panel, nunca por el lifecycle.
    if not _engine_owns:
        sched.stop_scheduler()
    for section in list(pm._states.keys()):
        if section == 'live':
            continue
        if pm._states[section].status == 'running':
            pm.stop_process(section)


app = FastAPI(
    title="scraper_V2.0 Control API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers REST
# OJO: driver y scheduler van ANTES de control. control expone rutas
# paramétricas /api/{section}/{start,stop,status,...} que, si se registran
# primero, capturan /api/driver/start etc. (section="driver"). Registrando los
# routers específicos antes, sus rutas concretas ganan el match.
app.include_router(driver.router)
app.include_router(live_driver.router)   # /api/live_driver/* — antes de control (igual que driver)
app.include_router(scheduler.router)
app.include_router(history.router)   # /api/db_history*, /api/leagues_status — antes de control
app.include_router(control.router)
app.include_router(leagues.router)
app.include_router(stats.router)
app.include_router(app_config.router)
app.include_router(inconsistencias.router)

# WebSocket
app.include_router(ws_logs.router)

# Servir capturas del scraper SIN caché del navegador: solo se muestra la última
# imagen guardada en disco; el navegador NO la cachea en memoria (evita que el
# panel, corriendo mucho tiempo, acumule miles de bitmaps decodificados).
class _NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        return resp

screenshots_path = os.path.join(PROJECT_ROOT, 'logs', 'screenshots')
os.makedirs(screenshots_path, exist_ok=True)
app.mount("/artifacts/screenshots", _NoCacheStatic(directory=screenshots_path), name="screenshots")

# Servir frontend en producción (si existe el build)
dist_path = os.path.join(PROJECT_ROOT, 'frontend', 'dist')
if os.path.isdir(dist_path):
    app.mount("/", StaticFiles(directory=dist_path, html=True), name="frontend")
