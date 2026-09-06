# Pendientes para completar el funcionamiento del scraper + panel

_Análisis 2026-06-13. Objetivo: control TOTAL desde el frontend, matches siempre
actualizados, completar lo faltante automáticamente, y programar qué scripts corren
con qué frecuencia. Este doc es el backlog de trabajo; marcar cada ítem al cerrarlo._

Punto de entrada de operación: `documentacion/RUNBOOK_PANEL.md`.
Panel = `api/` (FastAPI :8009) + `frontend/` (React/Vite :5174).

---

## 0. Estado actual (lo que YA funciona)

- **Panel** con 7 pestañas: Noticias, Ligas, Equipos, Partidos, Jugadores, Live, Inconsistencias.
- **Drivers gestionados por el panel** (independientes): corrección (`tmp/driver_session.json`)
  y live (`tmp/live_driver.json`), cada uno con Iniciar/Matar/estado + reciclado por memoria
  (hot-swap en live). Modo lightweight en live (menos RAM).
- **Live** (`main2.py`): monitorea N deportes, detecta "sin eventos" por texto único
  (incl. F1 "No race…"), espera el intervalo completo, **selección de deportes en caliente**,
  actualiza score/status de los partidos que ya existen, log de auditoría con causa de reciclaje,
  `[DB-WRITE]`/`[DB-SKIP]`, y registra ligas faltantes en `check_points/live_missing_leagues.json`.
- **Inconsistencias**:
  - `update_matches` (completar partidos pasados con score=-1 / backfill de stats) — con checkbox apply.
  - `fix_results` (`fix_null_team_ids`, crear teams faltantes / reparar score_entity) — con checkbox apply.
  - `live_missing` (ligas con partidos inexistentes detectadas por el Live) con estado pending/resolved/ignored.
  - **"Crear HOY"** por liga + **barrido multi-deporte** (`--from-pin --today`) que crean los
    partidos de hoy desde la summary (status+score reales: COMPLETED/LIVE/SCHEDULED). Auto-status
    (marca "resuelta" al terminar un apply).
- **Scheduler embebido** (`api/services/scheduler.py` + `check_points/CONFIG.json`):
  - **Noticias**: cada N horas (`EXTRACT_NEWS`).
  - **Fix team_ids**: diario a una hora (`FIX_TEAM_IDS`: ENABLED/AT_HOUR/APPLY/EXCLUDE).

---

## 1. Control TOTAL desde el frontend

Hoy varias secciones se controlan, pero falta uniformar Iniciar/Pausar/Reanudar/Detener
y el estado en vivo para TODAS.

| # | Pendiente | Dónde | Detalle / reuso | Prioridad |
|---|---|---|---|---|
| 1.1 | Botones **Iniciar/Pausar/Reanudar/Detener** de `update_matches` | `Inconsistencias.jsx` | El backend ya lee `run_control_update_matches.json`; falta cablear los botones (reusar `SectionControls`/`useProcess`). | Alta |
| 1.2 | **run_control (pausa/stop limpio)** en `paralel_teams.py`, `run_news.py`, `run_leagues.py` | esos scripts | Hoy solo `paralel_execution`, `paralel_players`, `main2`, `update_pending_matches` leen run_control. Portar el patrón `_check_control()`. | Media |
| 1.3 | Estado unificado por sección (running/paused/stopped + PID + progreso) visible en todas las pestañas | frontend | Ya existe `get_status`; faltan tarjetas consistentes. | Media |
| 1.4 | Que el **driver de cada sección** se vea y controle desde su pestaña (como Live/Inconsistencias) | frontend + `driver_manager` | Generalizar `DriverBar` (ya compartido). | Baja |

---

## 2. Matches actualizados (live + pasados)

| # | Pendiente | Dónde | Detalle | Prioridad |
|---|---|---|---|---|
| 2.1 | Asegurar que el **Live** corra de forma continua y supervisada (auto-restart si cae, watchdog) | `main2.py` / panel | Ya hay retry interno; falta un watchdog desde el panel que lo reinicie si el proceso muere. | Alta |
| 2.2 | Que el Live **capture** (no solo actualice): si ve un partido en vivo de liga pineada que NO está en la BD, dispara su creación (hoy solo lo registra en `live_missing`). | `main2.py` + crear_today | Integrar la creación `--today` como auto-trigger por liga pineada faltante (ya analizado: "verificación inicial"). | Alta |
| 2.3 | Cablear botones de control de `update_matches` (ver 1.1) para completar pasados (score=-1) y backfill de stats desde la UI cómodamente | Inconsistencias | — | Alta |
| 2.4 | Revisar `get_live_match`: solo cuenta ligas **pinned** (`data-pinned=true`); confirmar que eso es lo querido y documentarlo. | `milestone7.py` | Decisión de Jorge: sí, solo pineadas. Documentado. | Cerrado/doc |

---

## 3. Completar registros faltantes

| # | Pendiente | Dónde | Detalle | Prioridad |
|---|---|---|---|---|
| 3.1 | **Barrido automático** de pineadas (verificación inicial) integrado al ciclo, no solo botón manual | panel/scheduler | Programar el `--from-pin --today` (ver §4). | Alta |
| 3.2 | **4 ligas ausentes** de `leagues_info.json` (sin URL de results) que el live detecta como faltantes | `leagues_info.json` | Agregar URLs; sin eso no se pueden crear. | Media |
| 3.3 | **Ligas NUEVAS** (no existen en la BD) detectadas por el live | `completado_de_ligas.py` | Flujo de alta de liga + season + teams. Hoy el panel solo avisa "nueva, requiere alta manual". | Media |
| 3.4 | Opción `--league-id` en `fix_null_team_ids.py` para cubrir TODAS las ligas (hoy solo las que matchean por nombre) | `fix_null_team_ids.py` | GAP de IDs ya reconciliado (`validate_id_leagues_info.py`). | Media |
| 3.5 | Gap detección barrido: `detect_pending_leagues` usa la **vista ALL** del deporte; la creación usa la **summary** por liga. Pueden ver sets distintos → algún faltante no se flaguea. | crear_fixtures | Evaluar detectar desde la summary por liga o ampliar la ALL. | Baja |

---

## 4. Programación (scheduler) de qué scripts corren y con qué frecuencia

Hoy el scheduler embebido solo cubre **noticias** (cada N h) y **fix team_ids** (diario a hora).
Falta **generalizarlo** para programar cualquier script/sección con su frecuencia, todo desde el frontend.

| # | Pendiente | Detalle | Prioridad |
|---|---|---|---|
| 4.1 | **Scheduler genérico por sección/tarea**: tabla en CONFIG.json `{tarea: {enabled, modo(cada N h / diario a hora / cron), apply, params}}` + loop en `scheduler.py` que dispare cada una. | Reusar `_fix_due`/`_next_fix_run`. | Alta |
| 4.2 | Programar **`update_matches`** (completar pasados / backfill) con su frecuencia. | — | Alta |
| 4.3 | Programar **barrido `--from-pin --today`** (crear faltantes de hoy de las pineadas) cada N min/horas. | — | Alta |
| 4.4 | Programar **arranque/supervisión del Live** (que esté siempre corriendo). | watchdog | Alta |
| 4.5 | **UI de programación** unificada: una pestaña/panel "Programación" con todas las tareas, su frecuencia, último run, próximo run, on/off, apply. | Reusar `FixSchedulerPanel` como base. | Alta |
| 4.6 | Persistencia y resiliencia: last_run/next_run por tarea, sobrevive reinicios de API (ya hay patrón en `scheduler_*_state.json`). | — | Media |

---

## 5. Estabilidad y operación (transversal)

| # | Pendiente | Detalle | Prioridad |
|---|---|---|---|
| 5.1 | **Driver de corrección se cae seguido** (la sesión de Firefox muere aunque el launcher siga vivo). Investigar causa (concurrencia marionette / Firefox snap / OOM) y mitigar. | Hoy se relanza solo vía panel, pero conviene estabilizarlo. | Alta |
| 5.2 | **Status del driver real** (no solo launcher vivo): el panel marca "alive" por el launcher pid, no por si la sesión responde. Agregar un ping de sesión. | Evita el falso "activo". | Media |
| 5.3 | **`frontend/dist` desactualizado** → `npm run build` para servir en prod desde la API. | — | Baja |
| 5.4 | **Ejecución paralela multi-driver** (plan aprobado, sin implementar): N drivers por shard con control por worker desde el panel. | Ver `especificacion_parallel_panel.md`. Máquina actual 30 GB RAM → N>2 posible. | Media |
| 5.5 | Limpieza de huérfanos automatizada (geckodrivers ppid=systemd) tras caídas. | — | Baja |

---

## 6. Roadmap sugerido (orden)

1. **Control de `update_matches` desde la UI** (1.1 / 2.3) — completa lo que ya existe.
2. **Scheduler genérico + UI de Programación** (§4) — habilita "qué corre y con qué frecuencia".
3. **Auto-trigger de creación de faltantes** (2.2 / 3.1) — el live deja de solo registrar y crea.
4. **Watchdog del Live** (2.1 / 4.4) — corre siempre.
5. **Estabilidad del driver de corrección** (5.1 / 5.2).
6. Completar gaps de datos (3.2 / 3.3 / 3.4) y los de control fino (1.2 / 1.3).
7. Multi-driver paralelo (5.4) cuando haga falta escala.

---

## Noticias — estado y pendiente (2026-06-20)

Sistema endurecido esta sesión (ver `noticias.md` §Robustez): dedup idempotente `(title,
news_content)`, early-skip, corte unificado `_compute_floor_date`, reciclaje de driver FASE 1+2,
frontera diferida `pending_last_date`. Total `news` = 1487 (242 duplicados borrados, respaldo en
`logs/_deleted_news_dupes_backup*.json`). Verificado 6 deportes, 0 crashes. Scheduler 1×/día
habilitado; próxima corrida agendada ~mañana 00:04 (con el código corregido).

- **PENDIENTE — backfill dirigido de abril-mayo:** el watermark (`last_date`) avanza hacia lo nuevo;
  los deportes que ya pasaron abril (FOOTBALL/TENNIS) no lo llenan solos. Para completar: resetear su
  `last_date` en `check_points/last_saved_news.json` a ~25-mar y re-correr (ya seguro por la dedup).
  Decisión de Jorge. Solo GOLF se llenó hasta marzo (abril = 52 noticias).

---

## 7. Referencias

- Operación: `RUNBOOK_PANEL.md` · Pendientes históricos: RUNBOOK §7.
- Scheduler: `api/services/scheduler.py`, `check_points/CONFIG.json`.
- Crear faltantes de hoy: `crear_fixtures_ligas.py --today` / `--from-pin --today`.
- Live: `main2.py`, `src/milestone7.py`, `src/milestone8.py`.
- Noticias: `noticias.md` (§Robustez), `scripts/run_news.py`, `src/milestone1.py`, `src/data_base.py`.
- Multi-driver: `especificacion_parallel_panel.md`.
