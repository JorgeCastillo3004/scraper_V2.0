# Inventario para el RAG — scraper_V2.0 (project 5)

> **Tarea 8 (orquestador) — 2026-06-15. SIN escrituras al RAG.** Mapeo de todo lo
> desarrollado a entidades del RAG (Documents · Modules · Functions · Screens · Requirements),
> para guiar la ingesta (tareas 9–11). Fuente de verdad = código + `documentacion/` (git);
> esto es el plano de qué se va a indexar.
> Convención: se excluyen scratchpads `_debug_*` / `_test_*` y obsoletos (no se indexan).

## Resumen de cobertura
- **Documents:** ~33 (28 en `documentacion/` + 5 en `docs/`) + specs de agentes + esquema BD.
- **Modules:** ~80 (src core, orquestadores raíz, scripts mantenimiento/consulta/driver, api, frontend).
- **Functions clave:** ~40 (las más reusadas; el resto se infiere del módulo).
- **Screens:** 8 (pestañas del panel).
- **Requirements (R{n}):** 10 sprints/pendientes vivos.

---

## 1. DOCUMENTS (doc_type)

### architecture / overview
- `documentacion/INDICE.md` — entrada del sistema de docs (arquitectura general + flujo de datos).
- `documentacion/organizacion_proyecto.md` — plan/checklist de organización (§1-8).
- `documentacion/metodologia_desarrollo.md` — flujo de desarrollo + principios no negociables.
- `documentacion/indicaciones_para_desarrollo.md` — guía de desarrollo/testing (driver compartido, checkpoints, recovery).
- `agents/new_agents/00_README.md` + `agents/new_agents/01..08_*.md` — **sistema de 8 agentes**.
- `agents/new_agents_instructions.md` — spec maestro de los agentes.
- `documentacion/AGENTES_Y_ASIGNACIONES.md` — agentes operativos/runtime (track aparte).
- `documentacion/MCP_RAG_SISTEMA.md` — **diseño MCP↔RAG (Variante B, embeddings locales)**.
- `documentacion/INVENTARIO_RAG.md` — este documento.

### scraper_flow
- `documentacion/noticias.md` (M1) · `creacion_ligas.md` (M2) · `creacion_equipos.md` (M3) · `creacion_partidos.md` (M4) · `partidos_en_vivo.md` (M7).
- `documentacion/indice_scripts.md` — **índice completo de los ~88 scripts** (referencia anti-reinvención).
- `documentacion/sesion_fixtures_y_scripts.md` · `sesion_2026-06-03_parallel_design.md` · `especificacion_parallel_panel.md`.

### api_spec
- `documentacion/RUNBOOK_PANEL.md` — **operar el panel** (API 8009 + Vite 5174, mapa botón→script).
- `documentacion/api.md` — endpoints REST + WebSocket.
- `documentacion/frontend.md` — arquitectura React/Vite, pestañas, componentes.
- `documentacion/especificacion_panel_resumen_y_dbhistory.md` — RESUMEN + db_history (implementado).
- `documentacion/sesion_inconsistencias_fix_frontend.md` — corrección por liga desde UI.

### schema
- `postgress_init/console_8.sql` — **esquema de `sports_db`** (tablas, constraints, índices).
- Tablas núcleo: `sport, country, league, league_season, team, league_team_entity, player, team_player_entity, match, match_detail, score(_entity), news, stadium, running_leagues`.
- `documentacion/mejoras_performance.md` — validaciones de integridad + cierre score=-1.

### other / infra / runbooks
- `documentacion/desarrollo_local.md` · `INSTALACION.md` (raíz) — setup local / restauración.
- `docs/DRIVER_RULES.md` — **reglas absolutas del driver** · `docs/FIX_STATS_PAST_RUNBOOK.md`.
- `documentacion/AGENTE_MEMORIA.md` · `ESTRATEGIAS_DRIVERS_RECURSOS.md` — RAM/drivers (a revisar).
- `documentacion/PENDIENTES_FUNCIONAMIENTO.md` — backlog priorizado.
- `CLAUDE.md` (raíz) — reglas no-negociables del proyecto.

---

## 2. MODULES (agrupados; screen_id donde aplique)

### src/ — núcleo (scraper)
| Module | Rol |
|---|---|
| `src/milestone1.py` | M1 noticias |
| `src/milestone2.py` | M2 ligas (`create_leagues`) |
| `src/milestone3.py` | M3 equipos (`teams_creation`, `create_team_in_db`) |
| `src/milestone4.py` | M4 results/fixtures + stats (`get_result`, `get_match_info`, `get_statistics_game`, `retry_match`) |
| `src/milestone6.py` | M6 jugadores |
| `src/milestone7.py` | M7 live (`live_games`) |
| `src/milestone8.py` | M8 display / valores cambiantes |
| `src/common_functions.py` | utilidades (`launch_navigator`, `login`, `dismiss_cookies`, `wait_update_page`) |
| `src/data_base.py` | acceso Postgres (`getdb`, `save_*`, `update_score`, `update_match_status`, `get_math_details_ids`) |
| `src/live_function.py` | funciones del LIVE |
| `src/mem_monitor.py` | medición RAM navegador |
| `src/telegram_notify.py` | notificaciones LIVE (Telegram) |

### raíz — orquestadores / entrypoints
| Module | Rol |
|---|---|
| `crear_fixtures_ligas.py` | crea fixtures faltantes + equipos + estadio + season |
| `completado_de_ligas.py` | crea ligas pineadas faltantes |
| `paralel_execution.py` | ejecución paralela results/fixtures (N drivers) |
| `paralel_teams.py` | creación paralela de equipos |
| `paralel_players.py` | extracción paralela de jugadores |
| `main2.py` | entrypoint scraper LIVE (pause/stop) |

### scripts/ — mantenimiento de datos
`update_pending_matches.py`, `fix_live_matches.py`, `fix_null_team_ids.py`,
`fix_inconsistent_matches.py`, `fix_missing_teams.py`, `auto_repair_matches.py`,
`check_match_status.py`, `validate_id_leagues_info.py`, `migrate_leagues_info.py`,
`check_teams_match_db.py`, `rebuild_leagues_season.py`, `sync_checkpoints.py`.

### scripts/ — consulta / verificación DB (read-only)
`db_history.py`, `db_status.py`, `db_delta.py`, `verificar_integridad_db.py`,
`pin_leagues_match_count.py`, `show_matches_db.py`, `show_running_leagues.py`,
`check_league_id_team_id.py`, `compare_rounds_db.py`, `validacion.py`.

### scripts/ — driver / procesos / infra
`start_driver.py`, `driver_session.py`, `connect_driver.py`, `connect_server.py`,
`inspect_processes.py`, `stop_process.py`, `update_server.py`, `update_repo.py`,
`get_last_changes.py`, `live_runner.py`, `run_fix_live.py`, `run_leagues.py`,
`run_news.py`, `run_create_leagues.py`.

### api/ — backend FastAPI (8009) → screen: panel
| Module | Rol |
|---|---|
| `api/main.py` | app FastAPI + montaje routers |
| `api/routers/control.py` | control de secciones (run_control/run_status) |
| `api/routers/driver.py` · `live_driver.py` | control driver corrección / live |
| `api/routers/inconsistencias.py` | datos + fix por liga |
| `api/routers/leagues.py` · `stats.py` · `history.py` · `scheduler.py` · `app_config.py` | secciones panel |
| `api/services/process_manager.py` | spawn/stop de scripts (build_command) |
| `api/services/driver_manager.py` · `driver_registry.py` | ciclo de vida de drivers (registry.json) |
| `api/services/database.py` · `history.py` · `live_missing.py` · `scheduler.py` | servicios |
| `api/ws/logs.py` | WebSocket de logs |

### frontend/ — React+Vite (5174)
| Module | Rol |
|---|---|
| `frontend/src/App.jsx` · `main.jsx` | shell + routing |
| `frontend/src/api/client.js` | cliente API |
| `frontend/src/pages/*.jsx` | una por pestaña (ver Screens §4) |
| `frontend/src/components/DriverBar.jsx` | barra de driver compartida |
| `frontend/src/components/DbHistoryPanel.jsx` | visor db_history |
| `frontend/src/components/{LeagueSelector,SectionControls,StatusBadge,Terminal,WorkerScreenshots}.jsx` | componentes reutilizables |
| `frontend/src/hooks/{useProcess,useWebSocket}.js` | hooks |

---

## 3. FUNCTIONS clave (las más reusadas)

- **Emparejado/scan (fix_live_matches.py):** `scan_results_page`, `scan_with_coverage`, `load_until_date`, `get_last_visible_date`, `_no_match_visible`, `_norm_team`, `parse_flashscore_date`, `get_pending_live_matches`, `get_stats_backfill_matches`.
- **Extracción (milestone4.py):** `get_result`, `get_match_info`, `get_statistics_game`, `wait_load_details`, `retry_match`.
- **Persistencia (data_base.py):** `getdb`, `save_math_info`, `save_team_info`, `save_league_info`, `update_score`, `update_match_status`, `get_math_details_ids`, `get_dict_league_ready`, `claim_league`, `release_league`, `cleanup_stale_leagues`.
- **update_pending_matches.py:** `_apply_match_atomic`, `_check_control`, `_maybe_recycle`, `process_match`.
- **Driver:** `driver_session.get_driver`, `start_driver` (login + session-file).
- **Común:** `common_functions.login`, `launch_navigator`, `wait_update_page`, `dismiss_cookies`.
- **crear_fixtures_ligas.py:** `process_league`, `process_league_summary`, `scan_summary_today`.

---

## 4. SCREENS (pestañas del panel; route en frontend)

| Screen | route/página | sección backend |
|---|---|---|
| Noticias | `pages/Noticias.jsx` | `news` |
| Ligas | `pages/Ligas.jsx` | `leagues` |
| Equipos | `pages/Equipos.jsx` | `teams` |
| Partidos | `pages/Partidos.jsx` | `results`/`fixtures` |
| Jugadores | `pages/Jugadores.jsx` | `players` |
| Live | `pages/Live.jsx` | `live` (main2) |
| Inconsistencias | `pages/Inconsistencias.jsx` | `fix_results` + `update_matches` + driver |
| Drivers | `pages/Drivers.jsx` | `driver_registry` |

---

## 5. REQUIREMENTS (R{n} — sprints / pendientes vivos)

> Estado propuesto: `pending` salvo nota. Cargar vía workflow obligatorio de `rag_inicio.md`.

| R | Título | Prioridad | Estado | Doc/Origen |
|---|---|---|---|---|
| R1 | Crear los **152 partidos PASADOS** faltantes (pipeline de results / opción `--results`) | alta | pending | análisis 2026-06-15 (Tarea #5) |
| R2 | Crear **fixtures de MLB** (Live hace [DB-SKIP] de partidos MLB) | media | pending | logs live 2026-06-15 |
| R3 | **Ejecución paralela multi-driver** desde el panel (N por shard) | alta | pending | `especificacion_parallel_panel.md` |
| R4 | **Agente de memoria** (reducir RAM, auto-stop driver ocioso) | media | a revisar | `AGENTE_MEMORIA.md` |
| R5 | **Sistema de 8 agentes** (materializar como subagentes invocables) | alta | en progreso | `agents/new_agents/` |
| R6 | **MCP↔RAG (Variante B)**: embedder local + servidor MCP | alta | en progreso | `MCP_RAG_SISTEMA.md` |
| R7 | Completar **4 ligas ausentes** de `leagues_info.json` (falta URL results) | media | pending | INDICE / sesión inconsistencias |
| R8 | Portar **run_control** a `paralel_teams`/`run_news`/`run_leagues` (pausa/stop limpio) | baja | pending | RUNBOOK §5 |
| R9 | Opción **`--league-id`** en `fix_null_team_ids.py` (habilitar todas las ligas) | baja | pending | RUNBOOK §7 |
| R10 | **`npm run build`** de frontend para servir `dist` en prod desde la API | baja | pending | RUNBOOK §7 |

---

## 6. Notas para la ingesta (tareas 9–11)
- Excluir de modules: `_debug_*`, `_test_*`, y obsoletos (`main.py`, `main1.py`, `main_manual_adjust.py`, `test.py`, `temp.py`, `start_driver_no_login.py`).
- `config.py` NO se versiona ni se sube contenido sensible al RAG (solo referencia a `config_model.py`).
- Cada `document`/`module`/`function`/`screen`/`requirement` dispara su **embedding local** al crearse (Variante B). Verificar `embedding_ready=true` en la Tarea 12.
- Orden sugerido de ingesta: Documents → Screens → Modules → Functions → Requirements.
