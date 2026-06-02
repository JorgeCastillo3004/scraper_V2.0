# RUNBOOK — Panel de control del scraper

**Punto de entrada único para levantar y operar el panel.** Lee esto primero; solo
abre la doc de detalle (abajo) si vas a modificar código de una pestaña concreta.

Panel = `api/` (FastAPI, puerto **8009**) + `frontend/` (React+Vite, puerto **5174**).
Vite proxea `/api`, `/ws`, `/artifacts` → 8009. La API conecta a la BD **remota**
`96.30.195.40/sports_db` vía `config.py` (operación normal del scraper; solo lectura
de estado/control desde el panel — la escritura ocurre cuando lanzás una sección).

---

## 1. Levantar el servicio

```bash
cd /home/jorge/work/scraper_V2.0

# API (8009) — env_sports tiene fastapi + selenium + psycopg2
NO_RICH=1 PYTHONUNBUFFERED=1 \
  nohup env_sports/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8009 \
  > logs/_panel_api.log 2>&1 &

# Frontend (5174)
cd frontend && nohup npm run dev > ../logs/_panel_vite.log 2>&1 &
```

Abrir: **http://localhost:5174/** (también en LAN: `192.168.0.19:5174`).

## 2. Verificar

```bash
curl -s -o /dev/null -w "API %{http_code}\n"  http://localhost:8009/api/driver/status
curl -s -o /dev/null -w "Vite %{http_code}\n" http://localhost:5174/
curl -s http://localhost:5174/api/driver/status   # proxy → JSON real = OK
```
Ambos deben dar `200`. Logs: `logs/_panel_api.log`, `logs/_panel_vite.log`.

## 3. Bajar el servicio

```bash
pkill -f "uvicorn api.main"
pkill -f "vite"
```
⚠️ **NUNCA** `pkill firefox`/`geckodriver` — puede matar el navegador del usuario o
el driver del scraper. El driver se controla SOLO desde la pestaña Inconsistencias
(botón Iniciar/Matar → SIGTERM al PID de `tmp/driver_launcher.json`). Ver
[../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md).

## 4. El driver es independiente del panel

El driver Selenium NO se levanta con el panel. Tras un reinicio de la máquina queda
caído (`/api/driver/status` → `alive:false`). Se inicia **desde el frontend** (pestaña
Inconsistencias → "Iniciar driver"), que lanza `scripts/start_driver.py` detached con
login. `tmp/driver_session.json` puede apuntar a una sesión muerta tras reboot.

---

## 5. Pestañas y qué controla cada una (estado a 2026-06-02)

| Pestaña | Sección backend | Estado |
|---|---|---|
| Noticias | `news` | ✅ fecha última noticia + scheduler embebido cada N horas |
| Ligas | `leagues` | ✅ (pausa/stop no limpio — pendiente portar run_control) |
| Equipos | `teams` | ⚠️ `paralel_teams.py` no lee run_control (pausa/stop no limpio) |
| Partidos | `results`/`fixtures` | ✅ contrato run_control/run_status OK |
| Jugadores | `players` | ✅ contrato OK |
| Live | `live` | ✅ (usa `main2.py`; existe hot-swap `scripts/live_runner.py`) |
| Inconsistencias | `fix_results` + `update_matches` | ✅ corrección por liga + completado de partidos pasados |

**Inconsistencias** es la pestaña con más trabajo reciente.

### Mapa botón → script (pantalla Inconsistencias)
Verificado contra `frontend/src/pages/Inconsistencias.jsx`, `api/client.js`,
`api/routers/*` y `api/services/process_manager.build_command`:

| Botón (UI) | Handler JSX | Endpoint | **Script ejecutado** |
|---|---|---|---|
| Refrescar | `load()` | `GET /api/inconsistencias` | — (solo SELECT, `database._INCONS_QUERIES`) |
| ▶ Iniciar driver | `onStartDriver` | `POST /api/driver/start` | **`scripts/start_driver.py`** (Firefox+login, guarda `tmp/driver_session.json`) |
| ■ Matar driver | `onStopDriver` | `POST /api/driver/stop` | SIGTERM al launcher → `start_driver` hace `driver.quit()` (nunca pkill) |
| ▶ Simular/Ejecutar — tarjeta `score=-1` | `onRunPending` | `POST /api/update_matches/start` | **`scripts/update_pending_matches.py`** `--mode completo\|rapido [--apply]` |
| ▶ Simular/Ejecutar — tarjeta `no_statistics` | `onRunNostats` | `POST /api/update_matches/start` | **`scripts/update_pending_matches.py`** `--solo-sin-stats [--apply]` |
| ■ Detener (update) | `updProc.stop` | `POST /api/update_matches/stop` | mata `update_pending_matches.py` |
| ▶ Iniciar corrección (dry-run) — `fk_roto_team`/`detail_no_score` | `onRunFix` | `POST /api/fix_results/start` | **`scripts/fix_null_team_ids.py`** `--league …` |
| ■ Detener (fix) | `fixProc.stop` | `POST /api/fix_results/stop` | mata `fix_null_team_ids.py` |

El driver es **uno solo y compartido**: lo lanza "Iniciar driver" (`start_driver.py`)
y tanto `update_pending_matches.py` como `fix_null_team_ids.py` se reenganchan a él
con `driver_session.get_driver()` (lee `tmp/driver_session.json`, NO abre browser nuevo).

### Reciclado del driver por memoria (PENDIENTE — diseño acordado)
Problema observado 2026-06-02: en corridas largas (`update_matches` multi-liga, modo
completo+apply) el Firefox del driver crece hasta **~3 GB PSS en una sola pestaña**;
con 7.6 GB de RAM el sistema llegó a **~230 MB libres** y el OOM-killer mató el Firefox
→ la corrida se cayó a media tanda (launcher quedó `<defunct>`).

Diseño (a implementar): la detección y el reciclado viven **DENTRO del script de
extracción** (`update_pending_matches.py`, y opcionalmente `fix_null_team_ids.py`),
NO como watchdog externo del panel. En el checkpoint entre partidos/ligas
(`_check_control()`): medir la memoria del árbol del driver → si supera el umbral →
detener+relanzar el driver (= limpia los GB) → `get_driver()` de nuevo → re-navegar al
`results_url` de la liga actual → continuar en el mismo punto. Helper reusable previsto
en `scripts/driver_session.py` (`memoria_driver_mb()` + `relaunch_driver()`). Medición:
PSS del árbol del scraper SOLO (descendientes del launcher + Firefox `--marionette`),
NUNCA el Firefox del usuario. Decisión abierta: cortar entre ligas (simple) vs a mitad
de liga (re-navegar + re-escanear). Umbral propuesto ~2.0 GB PSS, configurable.

---

## 6. Doc de detalle (abrir solo si hace falta)

| Tema | Archivo |
|---|---|
| Arquitectura React/Vite, componentes | [frontend.md](frontend.md) |
| Endpoints REST + WebSocket | [api.md](api.md) |
| Trabajo de la sesión del frontend (Noticias, Inconsistencias, completado de partidos, reconciliación de IDs) | [sesion_inconsistencias_fix_frontend.md](sesion_inconsistencias_fix_frontend.md) |
| Plan §7 (integración) y §8 (visión funcional) | [organizacion_proyecto.md](organizacion_proyecto.md) |
| Reglas del driver | [../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md) |

---

## 7. Pendientes vivos (resumen — detalle en la sesión §3-§4 y plan §7)

- Cablear botones Iniciar/Pausar/Reanudar/Detener de `update_matches` en
  `Inconsistencias.jsx` (backend ya lee `run_control_update_matches.json`).
- Opción A `--league-id` en `fix_null_team_ids.py` para habilitar TODAS las ligas
  (hoy solo mapean las que coinciden por nombre). GAP de IDs ya reconciliado con
  `scripts/validate_id_leagues_info.py` (13 ligas corregidas); faltan 4 ligas
  ausentes del JSON (falta URL de results).
- `paralel_teams.py` / `run_news.py` / `run_leagues.py`: portar run_control para
  pausa/stop limpio.
- `frontend/dist` desactualizado → `npm run build` para servir en prod desde la API.
