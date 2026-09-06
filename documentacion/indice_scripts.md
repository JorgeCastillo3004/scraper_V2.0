# Índice de scripts — scraper_V2.0

Inventario **completo** de todos los `.py` del proyecto (src/, scripts/, raíz), con su
función en una línea. Objetivo: evitar reinventar funciones/módulos ya existentes.
Convención: `_debug_*` = scratchpad descartable · `_test_*` = pruebas · resto = definitivo.

> Mantener este archivo al día cuando se agregue/renombre un script.

---

## `src/` — núcleo (milestones + core)

| Script | Tipo | Función |
|---|---|---|
| `milestone1.py` | core | M1 — extracción de **noticias** |
| `milestone2.py` | core | M2 — creación de **ligas** (`create_leagues`) |
| `milestone3.py` | core | M3 — creación de **equipos** (`get_teams_info_part2`, `create_team_in_db`) |
| `milestone4.py` | core | M4 — extracción **results/fixtures + estadísticas** (`get_result`, `get_match_info`, `get_statistics_game`, `wait_load_details`, `retry_match`) |
| `milestone6.py` | core | M6 — extracción de **jugadores** |
| `milestone7.py` | core | M7 — partidos **en vivo** |
| `milestone8.py` | core | M8 — utilidades de display / valores cambiantes |
| `common_functions.py` | core | utilidades comunes: `launch_navigator`, `login`, `dismiss_cookies`, `wait_update_page`, `load_json`, `generate_uuid` |
| `data_base.py` | core | acceso Postgres: `getdb`, `save_*`, `update_score`, `update_match_status`, `get_math_details_ids`, `get_dict_league_ready` |
| `live_function.py` | core | funciones del scraper LIVE |
| `mem_monitor.py` | util | medición de consumo de memoria del navegador |
| `telegram_notify.py` | util | notificaciones del scraper LIVE vía Telegram Bot API |
| `extract_football_match.py` | core | extracción de datos de un match de fútbol *(revisar si sigue en uso)* |

## Raíz — orquestadores + config + entrypoints

| Script | Tipo | Función |
|---|---|---|
| `crear_fixtures_ligas.py` | orquestador | crea fixtures faltantes + equipos + estadio + season (checkpoint, `--from-pin`) |
| `completado_de_ligas.py` | orquestador | crea SOLO las ligas pineadas faltantes en DB |
| `paralel_execution.py` | orquestador | ejecución paralela results/fixtures (N drivers) |
| `paralel_teams.py` | orquestador | creación paralela de equipos (`teams_creation`) |
| `paralel_players.py` | orquestador | extracción paralela de jugadores (M6) |
| `main2.py` | entrypoint | scraper LIVE con control pause/stop (`run_control_live.json`) |
| `config.py` | config | credenciales y configuración sensible (NO versionado) |
| `config_model.py` | config | plantilla de `config.py` |
| `main.py` / `main1.py` / `main_manual_adjust.py` | obsoleto | entrypoints antiguos (candidatos a archivar) |
| `test.py` | obsoleto | scratchpad (`read df`) |

## `scripts/` — orquestadores / mantenimiento de datos

| Script | Tipo | Función |
|---|---|---|
| `update_pending_matches.py` | mantenimiento | completa partidos pendientes (fecha<hoy: LIVE o score=-1) reusando el driver vivo; modos `rapido`/`completo` + backfill `--solo-sin-stats`; dry-run o `--apply`; control pausa/stop (`run_control_update_matches.json`). Lo lanza el panel (sección `update_matches`) |
| `fix_live_matches.py` | mantenimiento | cierra partidos varados en LIVE; provee `get_pending_live_matches`, `get_stats_backfill_matches`, `load_until_date`, `scan_results_page`, `scan_with_coverage` (reusados por panel y notebook) |
| `fix_null_team_ids.py` | mantenimiento | cierra `match_detail` con team_id NULL. Flujo clásico navega FlashScore (crea equipos faltantes). **Modo `--db-only`** (2026-06-16): resuelve el team por nombre+deporte contra la DB sin navegar (causa b: el equipo ya existe), reusa `update_match_detail_team`. **`--prefer-most-used`**: desambigua selecciones duplicadas eligiendo la más usada en esa liga (ganador estricto). Solo INSERT/UPDATE |
| `_repair_orphan_cfl.py` | mantenimiento (puntual) | re-apunta (`UPDATE match.league_id/season_id`) partidos huérfanos de CFL (league_id/season_id fantasma) a la CFL real; salta duplicados name+date; dry-run/`--apply`. NUNCA DELETE |
| `label_old_season_matches.py` | mantenimiento | etiqueta partidos -1 de temporada VIEJA con `status='OLD_SEASON'` (verificado vs FlashScore); dry-run/`--apply`. Ver `documentacion/scores_negativos_y_temporadas.md` |
| `_chain_complete_current.sh` | orquestador | cadena de `update_pending_matches --apply` por liga (completa score-1 de temporadas ACTUALES); umbral reciclaje driver `DRIVER_MEM_LIMIT_MB` (default 3072) |
| `_chain_backfill_stats.sh` | orquestador | cadena de `update_pending_matches --solo-sin-stats --apply` por liga (lee `tmp/_backfill_leagues.txt`); backfill de `match.statistic` vacío en COMPLETED con score real; NO toca score/status; umbral driver 3072 |
| `fix_inconsistent_matches.py` | mantenimiento | completa partidos con `match_detail` incompleto (n<2) |
| `fix_missing_teams.py` | mantenimiento | registra equipos referenciados en `match.name` que faltan en `league_team` |
| `auto_repair_matches.py` | orquestador | reparación autónoma de todos los `match_detail` con team_id NULL |
| `check_match_status.py` | mantenimiento | diagnóstico y corrección del campo `status` en `match` |
| `validate_id_leagues_info.py` | mantenimiento | compara `league_id`/`season_id`/`country_id` de `leagues_info.json` vs DB (DB=verdad) y **corrige** el JSON (confirma `[s/N]`); NO agrega ligas ausentes |
| `migrate_leagues_info.py` | mantenimiento | agrega a cada liga teams/matches + bloques `teams_creation`/`extract_*` (idempotente) *(ruta hardcodeada antigua — revisar)* |
| `check_teams_match_db.py` | mantenimiento | actualiza `leagues_info.json` con conteos reales de equipos/partidos |
| `rebuild_leagues_season.py` | mantenimiento | reconstruye `check_points/leagues_season/{sport}/{league}.json` faltantes |
| `sync_checkpoints.py` | infra | sincroniza checkpoints de ligas entre local y servidor remoto |
| `_migrate_without_stats.py` | mantenimiento | marca matches como `without_statistics` parseando logs `fix_null_*.log` |

## `scripts/` — consulta / verificación DB (read-only salvo nota)

| Script | Tipo | Función |
|---|---|---|
| `db_history.py` | consulta | snapshot del estado de la DB + comparación con el anterior; incluye **status (SCHEDULED→COMPLETED)**, partidos con stats y pendientes score=-1, y COMPLETED por liga |
| `db_status.py` | consulta | estado actual: deportes, ligas, equipos, partidos |
| `db_delta.py` | consulta | estado actual + delta vs último snapshot |
| `verificar_integridad_db.py` | consulta | auditoría read-only de integridad de `sports_db` (múltiples chequeos) |
| `pin_leagues_match_count.py` | consulta | cuenta partidos en DB por liga pineada |
| `show_matches_db.py` | consulta | lista partidos en DB por fecha/deporte/liga (read-only) |
| `show_running_leagues.py` | consulta | muestra la tabla `running_leagues` |
| `check_league_id_team_id.py` | consulta | lista ligas y equipos de un deporte con sus IDs |
| `compare_rounds_db.py` | consulta | compara partidos en DB vs archivos `round.json` |
| `validacion.py` | consulta | valida partidos en curso (match, match_detail, team) |

## `scripts/` — driver / procesos / infra

| Script | Tipo | Función |
|---|---|---|
| `start_driver.py` | driver | abre el browser UNA vez, hace login y guarda la sesión (canónico) |
| `start_driver_no_login.py` | driver | igual sin login (workaround obsoleto — preferir `start_driver.py`) |
| `driver_session.py` | driver | `get_driver()`: reconecta al driver activo sin abrir browser nuevo |
| `connect_driver.py` | driver | utilidad para reconectarse a un driver Selenium activo |
| `connect_server.py` | infra | abre sesión SSH interactiva al servidor remoto |
| `inspect_processes.py` | infra | visualiza procesos zombie y drivers huérfanos |
| `stop_process.py` | infra | detiene procesos del scraper |
| `update_server.py` | infra | sincroniza código local → servidor remoto |
| `update_repo.py` | infra | git pull/sync del repo |
| `get_last_changes.py` | infra | muestra últimos cambios del repo git |
| `engine_runner.py` | orquestador | **MOTOR `scraper-engine` (2026-07-07):** corre `sched.start_scheduler()` (news+fix+live-missing) + supervisa `main2.py` por heartbeat + escribe `tmp/engine_status.json`. Reusa `scheduler`/`process_manager`. Correr con `ENGINE_OWNS_SCHEDULER=1`. Ver `especificacion_ejecucion_permanente.md`. SIN PROBAR (bloqueado: config→remoto) |
| `live_runner.py` | orquestador | runner del scraper LIVE (etapa 2) |
| `run_fix_live.py` | mantenimiento | cierra partidos varados en LIVE usando el driver del notebook |
| `run_leagues.py` | wrapper | CLI para lanzar creación de ligas desde la API |
| `run_news.py` | wrapper | CLI para lanzar extracción de noticias |
| `run_create_leagues.py` | wrapper | ejecuta `create_leagues()` para BOXING/GOLF/MOTOR SPORT |
| `test_server.py` | infra | servidor FastAPI de pruebas para milestone6 |
| `dev_playground.py` | scratchpad | desarrollo iterativo de `fix_null_team_ids.py` (driver vivo) |
| `temp.py` | obsoleto | scratchpad temporal |

## `scripts/` — pruebas (`_test_*`) y extracción puntual

| Script | Tipo | Función |
|---|---|---|
| `_test_etapa1_carga_liga.py` | test | etapa 1 — cargar la liga correcta (driver vivo, read-only) |
| `_test_etapa2_faltan_partidos.py` | test | etapa 2 — detectar partidos a actualizar (read-only) |
| `_test_etapa3_mostrar_mas.py` | test | etapa 3 — "Show more" hasta la fecha más antigua + scan |
| `test_boxing_extraction.py` | test | prueba extracción de boxing |
| `test_f1_extraction.py` | test | prueba extracción de F1 |
| `debug_f1.py` | debug | debug extracción F1 |
| `debug_golf_player_profile.py` | debug | debug perfil de jugador de golf |

## `scripts/` — debug / scratchpads (`_debug_*`, descartables)

| Script | Función |
|---|---|
| `_debug_match_search.py` | por qué un match no se encuentra en `scan_results_page` (nombre vs página) |
| `_debug_get_statistics_game.py` | prueba `milestone4.get_statistics_game` sobre un match |
| `_debug_stats.py` / `_debug_stats_internal.py` / `_debug_stats_selectors.py` | diagnóstico de extracción de estadísticas / selectores |
| `_debug_test_stats_fix.py` | prueba fix de `fix_match_statistic` |
| `_debug_repro_get_stats.py` | reproduce el flujo de stats de `fix_null_team_ids` |
| `_debug_diagnostic_scan.py` | diagnóstico del fallo 0/64 en scan |
| `_debug_scan_results.py` | debug puntual de `scan_results_page` |
| `_debug_inspect_row.py` | diagnóstico del filtro "Click for match detail!" |
| `_debug_match_info.py` | inspecciona la página de match actual (read-only) |
| `_debug_team_links.py` | diagnóstico de `get_team_links_from_match` (equipos duplicados) |
| `_debug_live.py` / `_debug_live_blocks.py` | debug de `live_function` contra el driver vivo |
| `_debug_no_match_fix.py` | valida `_no_match_visible()` (falso positivo en World Cup) |
| `_debug_wc_results.py` | ¿el driver ve matches en /world/world-cup/results/? |
| `_debug_seasons_check.py` | ¿las ligas tienen season en DB? (read-only) |
| `_debug_pin_check.py` / `_debug_pin_insert_dryrun.py` | confirmación/insert dry-run de ligas pineadas |
| `_debug_launch_and_fix_euroleague.py` | scratchpad euroleague |
| `_debug_null_team_baseline.py` | auditoría read-only de `match_detail.team_id` NULL: clasifica causa (a/b/c/d), season huérfana, FK |
| `_debug_cfl_dup_flashscore.py` | verifica en FlashScore si un par name+date con hora distinta es 1 o 2 partidos (caso CFL) |
| `_debug_4null_flashscore.py` | ¿los 4 NULL restantes (France/Great Britain) existen en FlashScore? |
| `_debug_brasil_seriea_scores.py` / `_debug_brasil_2025_archive.py` | confirma que los -1 viejos de Brasil están en el archivo `liga-2025`, no en la URL actual |
| `_debug_bolivia_seasons.py` | Bolivia: partidos DB no aparecen en results actuales (corte 02.06) |
| `_debug_verify_seasons_flashscore.py` | **clave**: por liga afectada lee `.heading__info` (season FlashScore) y la compara con `season_name` DB → vieja vs actual |
| `_debug_wc_football_vs_basket.py` | compara un matchup entre links de distintos deportes (detecta liga homónima cross-deporte) |
| `_debug_bolivia_21.py` | verifica si los partidos de una liga existen en results/fixtures de FlashScore (caso Bolivia) |
