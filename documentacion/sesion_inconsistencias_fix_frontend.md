# Sesión — Panel: log de integridad, Noticias (fecha + scheduler) y corrección de Inconsistencias por liga

Fecha: 2026-06-02. Trabajo sobre el panel de control (`api/` FastAPI + `frontend/` React)
apuntando al **remoto** `96.30.195.40/sports_db` (autorizado por el usuario, modo
visualización / dry-run). Ver también [organizacion_proyecto.md](organizacion_proyecto.md)
§4, §7 y §8, y [INDICE.md](INDICE.md).

---

## 0. Cómo levantar el servicio (para retomar)

```bash
cd /home/jorge/work/scraper_V2.0

# API (puerto 8009) — usa env_sports (tiene selenium + psycopg2 + fastapi)
NO_RICH=1 PYTHONUNBUFFERED=1 \
  nohup env_sports/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8009 \
  > logs/_panel_api.log 2>&1 &

# Frontend (puerto 5174) — proxea /api, /ws, /artifacts → 8009
cd frontend && nohup npm run dev > ../logs/_panel_vite.log 2>&1 &
```

Abrir: **http://localhost:5174/**. Bajar: `pkill -f "uvicorn api.main"; pkill -f "vite --host"`.
`config.py` apunta al remoto (regla: nunca cambiar a remoto sin permiso; acá ya autorizado).

---

## 1. Script de integridad — log accionable (`scripts/verificar_integridad_db.py`)
- Además de imprimir en pantalla, **siempre** escribe en `logs/`:
  - `integridad_<ts>.log` (humano: lista **ligas afectadas** + acción sugerida por chequeo).
  - `integridad_<ts>.json` (machine-readable: `affected_leagues` [sport/country/league/count]
    + `action` por chequeo) → contrato para que **otro script lea y actualice la data obsoleta**.
- `by_league` se recolecta siempre (antes solo con `--by-league`; ahora la pantalla lo
  muestra con `--by-league`, pero los archivos lo incluyen siempre).
- Las `by_league_sql` reusadas de `api/services/database.py` ahora devuelven también `league_id`.

## 2. Noticias — fecha de última noticia + scheduler embebido
- **Fecha última noticia**: `get_news_stats()` (read-only `COUNT(*)`+`MAX(published)`) →
  `GET /api/stats/news`. Mostrado bajo el título de la pestaña Noticias (verificado: 1088
  noticias, última 2026-03-25).
- **Todos los deportes por defecto**: si `CONFIG.json` no tiene selección guardada, se
  marcan todos.
- **Scheduler embebido** (`api/services/scheduler.py`): hilo que ejecuta la extracción de
  noticias **cada N horas** (lee `EXTRACT_NEWS` de `CONFIG.json` en cada tick; persiste
  `last_run` en `logs/scheduler_news_state.json`; no solapa; default = todos los deportes).
  Dispara reusando `process_manager.start_process('news', ...)` (escribe en remoto).
  Endpoint `GET /api/scheduler/news`. UI: toggle "Extracción automática" + "cada N horas"
  + estado (próxima/última). Arranca/para en el `lifespan` de `api/main.py`.

## 3. Inconsistencias — corregir resultados por liga DESDE LA UI (sin consola)
Objetivo: seleccionar liga(s) con problemas y lanzar la corrección controlada, viendo la
extracción. **Para esta etapa: solo dry-run (no escribe).**

- **Script usado**: `scripts/fix_null_team_ids.py` (`--league SPORT/KEY`, repetible, reusa
  driver vivo). Corrige la liga completa: `needs_team_fix` (fk_roto_team),
  `needs_score_fix` (score=-1), `needs_stats_fix` (detail_no_score). Navega results y
  actualiza fixtures antiguos.
- **Sección `fix_results`** en `process_manager.build_command`: arma
  `python3 scripts/fix_null_team_ids.py --league ... --league ...` **sin `--apply`** (dry-run).
  Agregada a `SECTIONS` en `api/config.py`. Stream a WebSocket `/ws/fix_results/logs`.
- **Control de driver dedicado** (`api/services/driver_manager.py` + router
  `/api/driver/{status,start,stop}`):
  - "Iniciar" → lanza `scripts/start_driver.py` detached (Firefox **visible** en
    `DISPLAY=:1`, con login; headless según `FIX_HEADLESS` de `config.py`).
  - "Matar" → **SIGTERM SOLO** al PID guardado en `tmp/driver_launcher.json` → start_driver
    hace `driver.quit()` de su propio browser + borra session. **NUNCA `pkill firefox`**
    (hay Firefox del usuario vivo — regla sagrada).
  - Status: vivo si el launcher corre y existe `tmp/driver_session.json`.
- **`/api/inconsistencias` enriquecido**: cada fila `by_league` trae `league_id` (DB) +
  `sport_key`/`league_key`/`mappable` (mapeo por league_id contra leagues_info,
  `get_league_key_index()` en database.py).
- **Frontend `Inconsistencias.jsx`**: barra de driver (iniciar/matar/estado), checkboxes
  por liga (solo **mapeables** habilitadas; no-mapeables deshabilitadas con motivo), botón
  "Iniciar corrección (dry-run)" (requiere driver activo + ≥1 liga) y Terminal en vivo.
- **Config**: `FIX_HEADLESS` agregado a `config.py` y `config_model.py`.
- **⚠️ Bug resuelto**: registrar routers `driver`/`scheduler` ANTES de `control` en
  `api/main.py` (control tiene catch-all `/api/{section}/start|stop|status` que los tapaba).

### 🔴 GAP pendiente — mapeo league_id (opción A, acordada, SIN implementar)
Los `league_id` de la DB donde están las inconsistencias **no coinciden** con los de
`leagues_info.json` (causa: **filas de liga duplicadas**, chequeo `dup_league`). Ej:
Premier League rota bajo `039e0410…` pero leagues_info tiene `e0117823…`. Como
`fix_null_team_ids` filtra matches por el id de leagues_info (línea ~1054), por nombre
detectaría 0. Solo **6/15** ligas mapean.

**Opción A (acordada):** agregar a `fix_null_team_ids.py` un `--league-id <ID_DB>` que
desacople el id de **detección** (DB, donde están los partidos malos) de la **URL de
results** (resuelta de leagues_info por nombre). Usuario: "es más confiable desde la base
de datos". Antes de implementar, opcional correr el chequeo read-only `dup_league` del
script de integridad para dimensionar duplicados.

---

## 4. PRÓXIMA SESIÓN
1. **Levantar el servicio** (sección 0).
2. **Seguir las pruebas del completado de partidos pasados desde el frontend**
   (pestaña Inconsistencias): iniciar driver, seleccionar liga(s) mapeable(s),
   lanzar dry-run y verificar la extracción en el Terminal.
3. **Implementar opción A** (`--league-id`) para habilitar TODAS las ligas (no solo las 6
   mapeables).
4. Luego: agregar toggle **"Aplicar"** (cambia dry-run → `--apply`, escribe en remoto;
   ya autorizado por el usuario).

---

## Sesión 2026-06-02 (cont.) — Completar partidos + reconciliación de IDs

### Flujo "completar partidos pendientes" (validado en notebook → integrado al panel)
- **`scripts/update_pending_matches.py`** (NUEVO): completa partidos pasados con `score=-1`
  o `LIVE` reusando el driver vivo (sin `quit()`). Modos `rapido` (score+detalles) /
  `completo` (+estadísticas) + backfill `--solo-sin-stats` (COMPLETED con resultado y sin
  `statistic`). Dry-run por defecto, `--apply` escribe. Logging de **cobertura X/Y**.
- Helpers promovidos a **`scripts/fix_live_matches.py`** (misma función que valida el
  notebook): `get_pending_live_matches`, `get_stats_backfill_matches`, `scan_with_coverage`,
  `sin_stats`, `get_statistic_map`.
- Fixes de extracción:
  - `scan_results_page` usa `textContent` (no `.text`) → no pierde filas no renderizadas.
  - `load_until_date` agrega delay final tras el último "Show more".
  - `get_statistics_game` (milestone4): espera a que cargue el TEXTO de stats; si no aparece,
    **primero refresca la página** y reintenta; último recurso = reload de URL vía `retry_match`.
- Panel (pestaña **Inconsistencias**): sección `update_matches`. Tarjeta **score=-1** →
  panel con checkbox "Extraer estadísticas también" + "Escribir en BD" (dry-run/apply).
  Tarjeta NUEVA **`no_statistics`** ("Partidos sin estadísticas (con resultado)") → backfill.
- Campo donde se guardan las estadísticas: **`match.statistic`** (string `str(dict)`, ~1700
  chars, ~33 indicadores por partido en football).
- Verificado en RUSSIA Premier League: 143 COMPLETED con score real + stats, 0 pendientes.

### Botones de control (Iniciar/Pausar/Reanudar + Detener)
- **Backend LISTO**: `update_pending_matches.py` lee `run_control_update_matches.json`
  (`_check_control` entre partidos: `pause` espera, `stop` sale sin cerrar driver).
  `process_manager.stop_process` para `update_matches` hace **kill inmediato** (sin esperar
  30s); el driver (Firefox detached) queda disponible.
- **PENDIENTE**: cablear los botones en `Inconsistencias.jsx` (Iniciar↔Pausar↔Reanudar + Detener).

### Reconciliación de IDs `leagues_info.json` ↔ DB (GAP league_id resuelto)
- Causa de las ligas "No mapeable": el `league_id` del JSON no coincidía con el real de la DB
  (IDs huérfanos en el JSON; la creación de partidos resuelve el id real por país+nombre).
- **`scripts/validate_id_leagues_info.py`** (ya existía) compara `league_id`/`season_id`/
  `country_id` del JSON vs DB (DB=verdad) y corrige el JSON con confirmación.
- Aplicado: **13 ligas / 15 campos corregidos** → validación final **0 diferencias**.
  Backups en `check_points/leagues_info.json.bak_*`.
- **NO cubre ligas ausentes** del JSON. Quedan 4 por agregar (no están en `leagues_info`):
  Football/ARGENTINA/Torneo Betano, Hockey/{CZECH Extraliga, FINLAND Liiga, GERMANY DEL}.
  La DB da `league_id`/`country_id`/`season_id`, pero **falta la URL de results** (no está en
  DB) → para agregarlas hay que detectar/proveer la URL de FlashScore (y crear la sección
  HOCKEY en el JSON).

---

## Sesión 2026-06-02 (cont.) — OOM del driver + reciclado por memoria

**Evento:** corrida `update_matches` modo completo+apply sobre 9 ligas (ENGLAND, GERMANY,
TURKEY, FRANCE, BELGIUM, BRAZIL, ARGENTINA, COLOMBIA, VENEZUELA) infló el Firefox del
driver a **~3 GB PSS concentrado en UNA pestaña**. Con 7.6 GB de RAM el sistema bajó a
**~230 MB libres** → OOM-killer mató el Firefox del scraper → la corrida murió a media
tanda y el launcher quedó `<defunct>`. (Medido con `scripts/_debug_verify_clon.py`? no —
con recorrido `/proc` sumando PSS del árbol del driver; el Firefox del usuario, árbol
aparte pid 16307, NO se toca.)

**Mapa botón → script (pantalla Inconsistencias):** documentado en
[RUNBOOK_PANEL.md](RUNBOOK_PANEL.md) §5 (tabla completa). Resumen: `update_matches` →
`update_pending_matches.py`; `fix_results` → `fix_null_team_ids.py`; driver →
`start_driver.py`. Todos comparten UN driver vía `driver_session.get_driver()`.

**Feature acordada (a implementar) — reciclado del driver DENTRO del script:**
- La detección+reciclado NO es watchdog del panel; vive en el script de extracción
  (`update_pending_matches.py`, opcional `fix_null_team_ids.py`).
- En el checkpoint entre partidos/ligas (`_check_control()`): medir memoria del árbol del
  driver → si > umbral → detener+relanzar driver (libera los GB) → `get_driver()` →
  re-navegar al `results_url` de la liga actual → continuar en el mismo punto.
- Helper reusable en `scripts/driver_session.py`: `memoria_driver_mb()` + `relaunch_driver()`
  (este último reusa la mecánica de `driver_manager.start/stop` / `start_driver.py`).
- Métrica PSS, solo árbol del scraper. Umbral propuesto ~2.0 GB (configurable).
- **Decisión abierta:** cortar entre ligas (simple, "mismo punto"=liga siguiente) vs a
  mitad de liga (re-navegar + re-escanear results antes de seguir partidos restantes).
