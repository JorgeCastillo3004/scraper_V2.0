# RUNBOOK — Panel de control del scraper

**Punto de entrada único para levantar y operar el panel (local).** Lee esto primero; solo
abre la doc de detalle (abajo) si vas a modificar código de una pestaña concreta.

> ⚠️ Para el **live que corre en el servidor** (permanente, bajo systemd) el runbook es
> otro: [`RUNBOOK_LIVE_SERVIDOR.md`](RUNBOOK_LIVE_SERVIDOR.md). Ambos escriben en la
> **misma BD remota**, así que antes de lanzar una sección pesada desde el panel conviene
> mirar qué está haciendo el live del servidor (regla de un solo escritor).

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

### 4.1 Higiene de recursos / drivers huérfanos (revisado 2026-06-22)

Esta máquina tiene **30 GiB de RAM** (no 7.6 GB; nota vieja de otra restauración).
Antes de "reducir consumo" SIEMPRE separar 3 familias de procesos:

1. **Firefox de ESCRITORIO del usuario** (snap `firefox` bajo `gnome-shell`, perfil del
   usuario). Suele ser el mayor consumidor (visto 1 pestaña en **7.6 GB**). **JAMÁS se toca.**
   Se reconoce: padre = `gnome-shell`, sin `--marionette`, perfil NO en `/tmp/rust_mozprofile`.
2. **Drivers del scraper VIVOS** — Firefox con `--marionette` + perfil `/tmp/rust_mozprofile…`,
   **con** un `geckodriver` padre vivo y su `start_driver.py`. El de LIVE se identifica por
   `tmp/live_driver.json` (`session_id`/`executor_url`). No se matan: reciclan por hot-swap.
3. **Drivers del scraper HUÉRFANOS** — Firefox `--marionette` + `/tmp/rust_mozprofile…` cuyo
   `geckodriver` ya murió → reparentado a `systemd --user` (PPID = el pid de `systemd --user`).
   Nadie puede manejarlo (su puerto `--remote-debugging-port` solo lo escucha él mismo). Es
   memoria muerta (visto ~865 MB, 9 h idle). **Se puede limpiar, pero con confirmación.**

Detección:
```bash
# Drivers marionette del scraper y su padre
ps -eo pid,ppid,rss,args | grep -E "rust_mozprofile" | grep -v grep
# ¿Tiene geckodriver vivo? (si NO aparece su puerto debug con dueño geckodriver → huérfano)
ps -eo pid,ppid,args | grep geckodriver | grep -v grep
ss -ltnp | grep <remote-debugging-port>
# ¿Reparentado a systemd? (PPID == pid de `systemd --user` ⇒ huérfano)
```
Limpieza segura de un huérfano (verificado 2026-06-22, liberó ~865 MB):
```bash
# SIGTERM DIRIGIDO al PID exacto. NUNCA pkill firefox/geckodriver (mataría el del usuario
# o el LIVE). Confirmar antes el cmdline: --headless + rust_mozprofile + PPID=systemd.
kill <PID_HUERFANO>
```

> ⚠️ Los "8 uvicorns zombies" que mencionaban notas viejas **ya no existen** tras reinicio.
> Lo que hoy corre además del panel es el stack **`control_de_ventas`** en **Docker**
> (`ventas_backend`→host `:8004`, `ventas_postgres/redis/minio`) + su frontend node en `:3003`.
> NO son del scraper ni son zombies: pertenecen a otro proyecto y están arriba a propósito.
> `app.main:8000` corre DENTRO de contenedor (`/proc/<pid>/cgroup` → `docker-…`) → no matar
> desde el host; usar `docker compose` de ese proyecto si se quiere bajar.

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

### Reciclado del driver por memoria (✅ IMPLEMENTADO 2026-06-03)
Problema (2026-06-02): en corridas largas (`update_matches` multi-liga, completo+apply)
el Firefox del driver crece hasta **~3 GB PSS en una sola pestaña**; con 7.6 GB de RAM
el sistema llegó a ~230 MB libres y el OOM-killer mató el Firefox → la corrida se cayó.

Solución: la detección+reciclado viven **DENTRO del script** (`update_pending_matches.py`),
NO como watchdog del panel. Implementación:
- **Umbral:** `MEM_LIMIT_MB` = **2048 MB** (env `DRIVER_MEM_LIMIT_MB` lo sobreescribe).
- **Dónde mide:** entre partidos (junto a `_check_control()`), vía `_maybe_recycle()`.
- **Métrica:** `driver_session.driver_tree_pss_mb()` — PSS del árbol del driver del scraper
  SOLO (launcher + geckodriver + Firefox `--marionette` + content procs); **NUNCA** el
  Firefox del usuario (árbol aparte). Si no puede medir → 0 → no recicla.
- **Reciclado:** `driver_session.relaunch_driver()` reusa `api/services/driver_manager`
  (`stop()` SIGTERM al launcher → `start_driver` hace `quit()` y libera los GB; `start()`
  lanza uno nuevo con login; espera la sesión y devuelve `get_driver()` reconectado).
- **Continúa en el mismo punto (corte a mitad de liga):** `found` ya está en memoria y
  `process_match` navega solo a la página de cada partido restante, así que NO hace falta
  re-escanear ni re-navegar a results.
- **Visibilidad:** header imprime "Reciclado … ACTIVO (umbral N MB)"; cada reciclado loguea
  `[RECICLAJE] …`; el RESUMEN final imprime `Reciclajes drv : N`.
- Gemelo `fix_null_team_ids.py` NO tiene el reciclado aún (mismo patrón si se quiere).
- Para probar: lanzar una corrida `update_matches` larga desde el panel y mirar el log.

### Detener una corrida — atomicidad por partido (✅ 2026-06-03)
El botón "■ Detener" de `update_matches` hace `process_manager.stop_process` →
**SIGTERM** (terminate), 3 s de gracia, luego **SIGKILL**. El script no tiene handler
de SIGTERM, así que muere donde esté. Para que eso NO deje partidos a medias:
- **Cada partido se escribe en UNA sola transacción** (`_apply_match_atomic` en
  `update_pending_matches.py`): los 2 `score_entity` + `status=COMPLETED` + `match.statistic`
  van con **un único `commit()`** al final (antes eran 3-4 commits sueltos vía
  `data_base.update_score/update_match_status/_write_statistic`).
- Si el proceso muere antes del commit (Detener/SIGKILL, OOM, crash, reciclado), Postgres
  hace **ROLLBACK** → el partido queda en su estado original → la próxima corrida lo
  reprocesa. **Nunca** quedan estados parciales (p.ej. score real con `status=SCHEDULED` =
  huérfano, que era justo la causa de los SCHEDULED-con-resultado).
- Costo: al detener a mitad de partido, **ese** partido se descarta (se rehace luego); no
  se "termina" el partido en curso. Si se quisiera que lo TERMINE antes de salir, falta el
  stop cooperativo (escribir `run_control='stop'`, que el script ya chequea entre partidos
  en `_check_control()`) — pendiente/opcional.

---

## 6. Doc de detalle (abrir solo si hace falta)

| Tema | Archivo |
|---|---|
| Arquitectura React/Vite, componentes | [frontend.md](frontend.md) |
| Endpoints REST + WebSocket | [api.md](api.md) |
| Trabajo de la sesión del frontend (Noticias, Inconsistencias, completado de partidos, reconciliación de IDs) | [sesion_inconsistencias_fix_frontend.md](sesion_inconsistencias_fix_frontend.md) |
| **Tenis — creación de partidos: diagnóstico, fixes (foto/DOB/dobles/points), `--load-images`, pruebas** | [tenis_creacion_y_fixes.md](tenis_creacion_y_fixes.md) |
| Plan §7 (integración) y §8 (visión funcional) | [organizacion_proyecto.md](organizacion_proyecto.md) |
| Reglas del driver | [../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md) |
| **Servidores y acceso SSH/DB** (`ssh scraper_server`, DB `wohhu@96.30.195.40`) | [servidores_y_acceso.md](servidores_y_acceso.md) |

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
