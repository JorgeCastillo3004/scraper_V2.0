# Documentación — scraper_V2.0

Pipeline de recolección de datos deportivos desde FlashScore.com con Selenium + PostgreSQL.

---
Siempre debes leer el indice, aca te indicara que documentacion revisar, antes de revisar codigo, solo 
debes revisar codigo cuando se proceda a modificar o verficar en forma detallada, solo revisa lo necesario para conseguir una mejor respuesta.

## Módulos del scraper

| Archivo | Módulo fuente | Función principal |
|---|---|---|
| [noticias.md](noticias.md) | `src/milestone1.py` | `main_extract_news` |
| [creacion_ligas.md](creacion_ligas.md) | `src/milestone2.py` | `create_leagues` |
| [creacion_equipos.md](creacion_equipos.md) | `src/milestone3.py` | `teams_creation` |
| [creacion_partidos.md](creacion_partidos.md) | `src/milestone4.py` | `results_fixtures_extraction` / `extraction_by_dict` |
| [partidos_en_vivo.md](partidos_en_vivo.md) | `src/milestone7.py` | `live_games` |

## Frontend y API

| Archivo | Descripción |
|---|---|
| [RUNBOOK_PANEL.md](RUNBOOK_PANEL.md) | **EMPEZAR AQUÍ para operar el panel.** Levantar/bajar/verificar el servicio (API 8009 + Vite 5174), qué controla cada pestaña, estado actual y pendientes vivos. Conciso: leer solo esto salvo que modifiques una pestaña |
| [frontend.md](frontend.md) | Arquitectura React + Vite, pestañas, componentes (detalle) |
| [api.md](api.md) | Endpoints REST + WebSocket, comandos por sección |
| [PENDIENTES_FUNCIONAMIENTO.md](PENDIENTES_FUNCIONAMIENTO.md) | **Backlog para completar el sistema:** control total desde el frontend, matches actualizados, completar faltantes, scheduler genérico por frecuencia, estabilidad. Roadmap priorizado (2026-06-13) |
| [especificacion_ejecucion_permanente.md](especificacion_ejecucion_permanente.md) | **SPEC a implementar (2026-06-26):** ejecución permanente en servidor con **2 servicios systemd** (`scraper-engine` siempre corriendo = Live + scheduler + Driver 2 on-demand; `scraper-panel` = API/front solo ver/configurar). Driver 1 Live liviano permanente + Driver 2 completo on-demand serializado (news+inconsistencias). Reconcilia las brechas 5.1–5.6 de `nuevos_requerimientos/`; reusa `scheduler.py`, `driver_manager.py`, `live_missing_leagues.json`. Plan incremental local-first |
| [AGENTE_MEMORIA.md](AGENTE_MEMORIA.md) | **Spec a revisar (2026-06-13):** agente para detectar y reducir el consumo de RAM. Diagnóstico medido por PSS (driver de corrección ocioso = 3.45 GB, uvicorns zombies, contentproc acumulados), causas raíz y plan de reducción sin romper reglas del driver |
| [ESTRATEGIAS_DRIVERS_RECURSOS.md](ESTRATEGIAS_DRIVERS_RECURSOS.md) | **Diseño a revisar (2026-06-13):** por qué queda un driver ocioso (corrección sin idle-stop ni lightweight), cómo se crean/cierran los drivers hoy, y estrategias para minimizar RAM, crear/cerrar bien y no abrir drivers de más. Complementa AGENTE_MEMORIA.md |
| [AGENTES_Y_ASIGNACIONES.md](AGENTES_Y_ASIGNACIONES.md) | **BORRADOR a completar (2026-06-14):** registro de los agentes/automatizaciones del proyecto y su asignación (responsabilidad, disparador, estado, doc/tarea). Pre-cargado con el agente de memoria; el resto a definir juntos |
| [OPTIMIZACION_LIVE.md](OPTIMIZACION_LIVE.md) | **BORRADOR a revisar (2026-06-16):** optimización del LIVE — Fase A (asegurar fixtures del día en DB, reusa `crear_fixtures --today`) + Fase B (ventanas de navegación por deporte) + reglas de seguridad (fail-open, seguir LIVE fuera de ventana) + driver dormido en horas muertas |
| [MCP_RAG_SISTEMA.md](MCP_RAG_SISTEMA.md) | **DISEÑO a revisar (2026-06-15):** sistema MCP↔RAG (Variante B, embeddings locales) — cómo Claude Code se conecta al `rag_system` vía servidor MCP, dónde se usan los embeddings, flujos de lectura/sync |
| [INVENTARIO_RAG.md](INVENTARIO_RAG.md) | **2026-06-15:** mapeo de todo lo desarrollado a entidades del RAG (Documents/Modules/Functions/Screens/Requirements) para guiar la ingesta (project 5) |
| [creacion_APP.md](creacion_APP.md) | Propuesta original de la app de control |

## Infraestructura

| Archivo | Descripción |
|---|---|
| [servidores_y_acceso.md](servidores_y_acceso.md) | **Los 2 servidores:** app/deploy `104.156.244.145` (SSH `scraper_server`, alias y key, qué corre allí) y DB `96.30.195.40` (solo Postgres, infra de José). Incluye la regla de **un solo escritor** sobre `sports_db` |
| [desarrollo_local.md](desarrollo_local.md) | Levantar DB Docker, API, frontend y geckodriver localmente |
| [mejoras_performance.md](mejoras_performance.md) | Validaciones de integridad en DB y cierre de partidos con score `-1,-1` |
| [indicaciones_para_desarrollo.md](indicaciones_para_desarrollo.md) | Guía general de desarrollo y testing: driver compartido, scratchpad → definitivo, logs, heartbeat, checkpoints, idempotencia, recovery |
| [metodologia_desarrollo.md](metodologia_desarrollo.md) | Diagrama del flujo de desarrollo (entender→diseñar/aprobar→implementar→probar incremental→verificar/documentar) + principios no negociables |
| [organizacion_proyecto.md](organizacion_proyecto.md) | **Plan/checklist** para organizar el proyecto: doc maestro, índice completo de scripts (+renombrar), diagrama por milestone, script de integridad de DB, arquitectura 2 etapas, pendientes |

## Sesiones / scripts de mantenimiento

| Archivo | Descripción |
|---|---|
| [indice_scripts.md](indice_scripts.md) | **Índice COMPLETO de los 93 scripts** del proyecto (src/ + scripts/ + raíz), agrupados por tipo, 1 línea c/u. Referencia para no reinventar funciones/módulos. Mantener al día |
| [scores_negativos_y_temporadas.md](scores_negativos_y_temporadas.md) | **RUNBOOK recurrente (2026-06-16):** limpieza de partidos pasados con `score_entity.points=-1`. Metodología (verificar temporada por `.heading__info` de FlashScore, NO por `season_id`) + clasificación (vieja→etiquetar+0-0 / actual→completar / fantasma→borrar / cross-deporte→borrar) + scripts (`label_old_season_matches`, `update_pending_matches`, `_chain_complete_current`, `crear_fixtures_ligas`, debug). Causa raíz: lookup sin filtro de deporte (`red_box_warning`). Corrida 225→0 |
| [sesion_fixtures_y_scripts.md](sesion_fixtures_y_scripts.md) | Sesión 2026-05-30: creación de fixtures faltantes (`crear_fixtures_ligas.py`) + índice de scripts desarrollados y fixes de fondo (naming de deporte, sufijo de fase, `league_id` viejo en JSON, estadio en bloque nuevo) |
| [sesion_organizacion_integridad.md](sesion_organizacion_integridad.md) | Sesión 2026-06-01: Flet archivado a `old_versions/`, plan ampliado (§7 panel, §8 visión), y **`scripts/verificar_integridad_db.py`** (auditoría read-only, 19 chequeos). PENDIENTE: probarlo (config.py apunta a remoto) |
| [sesion_inconsistencias_fix_frontend.md](sesion_inconsistencias_fix_frontend.md) | Sesión 2026-06-02: log accionable del script de integridad (.log/.json), Noticias (fecha última noticia + scheduler embebido cada N horas), y **corrección de Inconsistencias por liga desde la UI** (sección `fix_results` dry-run + control de driver `/api/driver/*`). Cómo levantar el servicio. GAP league_id (opción A pendiente). **PRÓXIMA: levantar servicio + seguir pruebas de completado de partidos pasados desde el frontend** |
| [sesion_2026-06-03_parallel_design.md](sesion_2026-06-03_parallel_design.md) | Sesión 2026-06-03: verificación del **reciclaje del driver por memoria** (umbral 2048 MB, ~7 reciclajes/77 partidos en `update_pending_matches.py`) y **diseño aprobado de ejecución paralela multi-driver controlada desde el panel** (N=2 configurable, sharding por deporte+país+liga, visible→config, control independiente por worker). **PRÓXIMA: implementar la spec** |
| [sesion_2026-07-06_driver_snap_y_fechas.md](sesion_2026-07-06_driver_snap_y_fechas.md) | Sesión 2026-06-29→07-06: **CAUSA RAÍZ del driver que no se lanza desde el frontend** = snap Firefox rev 8568 con content-snap `gpu-2404` stale (`geckodriver status 3`, fix `snap disconnect/connect firefox:gpu-2404`, intermitente). Bug de `driver_manager.status()` (alive falso, no verifica Firefox vivo). Gap de supervisión de LIVE sin engine (murió 07-03). **Fix de `score=-1` Bolivia (8)** = partidos POSPUESTOS → `UPDATE match_date` a fechas de agosto (no faltaba resultado, sobraba fecha vieja). CFL (1) = jugado, falta scrape de result. Cambio de DOM FlashScore `event__time`→**`event__stageTime`**. Parada limpia del scraper + análisis de RAM (los grandes = Firefox de escritorio, no el scraper) |
| [sesion_2026-09-06_memoria_live_y_sesion.md](sesion_2026-09-06_memoria_live_y_sesion.md) | Sesión 2026-09-06: **CAUSA RAÍZ de la fuga de memoria del live del servidor** = `_maybe_recycle_live` salía en `if _OWN_DRIVER: return` → el reciclaje solo corría con driver del panel y en el server (sin panel) **nunca reciclaba** (Firefox a 7,9 GB en 6 días, 1,9 GB libres). Fix: `tree_pss_mb(pid)`, medición por PID propio, `_hotswap_own_driver` (verifica el nuevo antes de cerrar el viejo), `_close_own_driver`, umbral **3000 MB**. Además **abrir el navegador ya logueado**: la sesión de FlashScore NO está en cookies sino en `localStorage` `lsid_*` → `ensure_login`/`apply_fs_session` (`tmp/fs_session.json`): 13,3 s de login → **1,5 s**. Desplegado y verificado en el servidor |
| [proveedor_respaldo_evaluacion.md](proveedor_respaldo_evaluacion.md) | **SC4/SC5 del roadmap** — evaluación verificada (2026-09-06) de las fuentes de respaldo para el Live: **ESPN** (9/9 deportes, gratis, sin key, 88% de cruce de nombres, pero sin NPB/KBO/LMB/LIDOM), **API-Sports** (una API por deporte, 100 req/día gratis, falta verificar béisbol asiático), **SofaScore** (mejor cobertura pero solo desde navegador → no es independiente del primario) y los descartados football-data.org / SportMonks / TheSportsDB. Recomendación, coste y plan B |
| [especificacion_parallel_panel.md](especificacion_parallel_panel.md) | **ESPEC a implementar** — N drivers en paralelo (reusa `paralel_execution.py`) corriendo `update_pending_matches` por shard, con start/pause/stop/cerrar-driver **independientes por worker** desde el panel. Decisiones aprobadas, GAPs vs lo existente, plan incremental, restricción de RAM (7.6 GB → N=2 techo) |
| [especificacion_panel_resumen_y_dbhistory.md](especificacion_panel_resumen_y_dbhistory.md) | **IMPLEMENTADO (2026-06-04)** — (1) RESUMEN de `update_pending_matches` partido en *Resumen de sesión* (por liga) + *Totalización* (global); (2) `api/services/history.py` + `api/routers/history.py` + `frontend/.../DbHistoryPanel.jsx`: tabla **estado por liga desde logs** (última ejecución + `encontrados X/Y`) y **visor de `db_history`** ◀▶ al fondo de Inconsistencias, auto-snapshot al terminar extracción. Además: **fix de `load_until_date`** (botón `Show more matches` con selector nuevo `//button[.//span[...]]`, conteo `div.event__match`, corte por fecha mínima/estancamiento) |

## Runbooks operativos

| Archivo | Descripción |
|---|---|
| [RUNBOOK_LIVE_SERVIDOR.md](RUNBOOK_LIVE_SERVIDOR.md) | **EMPEZAR AQUÍ para operar el live del servidor (2026-08-30).** `live_v2` en `104.156.244.145` bajo **systemd de usuario** (`scraper-live.service` + linger, arranca tras reboot; no hay sudo → nada de unidades de sistema). Comandos, cómo leer el log (`[OK]`/`[DB-SKIP]`/`[VENTANA]`), rotación de logs (geckodriver crece **46 MB/día**, truncar NUNCA borrar), diagnóstico, el incidente de 38 días caído por reboot sin systemd, y por qué Inconsistencias **no** se puede correr allí |
| [../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md) | Reglas absolutas del driver Selenium (no matar, no quit, reusar session_id) |
| [../docs/FIX_STATS_PAST_RUNBOOK.md](../docs/FIX_STATS_PAST_RUNBOOK.md) | Procedimiento para completar `match.statistic` vacíos en matches pasados, liga por liga, con `--only-stats-past` |

---

## Arquitectura general del sistema

```
main.py
  └─ ThreadPoolExecutor (2 hilos)
       ├─ main1.py  →  scraping programado (cron)
       │    └─ noticias → ligas → equipos → resultados → fixtures → jugadores
       └─ main2.py  →  scores en vivo (loop continuo)
            └─ live_games → update_lives_matchs
```

### Ejecución paralela (producción masiva)

```
paralel_execution.py N results
  └─ N workers (Firefox headless)
       └─ extraction_by_dict()  →  milestone4.py
            └─ claim/release en DB  →  evita colisiones entre workers
```

---

## Archivos de configuración clave

| Archivo | Propósito |
|---|---|
| `check_points/CONFIG.json` | Schedules cron y deportes activos por sección |
| `check_points/leagues_info.json` | Registro maestro de ligas (habilitar/deshabilitar con `extract_results.extract`) |
| `check_points/last_saved_news.json` | Checkpoint de fecha por deporte (noticias) |
| `config.py` | Credenciales DB y FlashScore (no está en git) |

---

## Flujo de datos

```
FlashScore.com
    │  Selenium + Firefox headless
    ▼
src/milestone*.py   (extracción y parseo HTML)
    ├──► check_points/*.json   (estado intermedio — permite resume)
    └──► data_base.py
              │  psycopg2
              ▼
         PostgreSQL
         ├── sport / country / league / league_season
         ├── team / league_team_entity
         ├── player / team_player_entity
         ├── match / match_details / score
         ├── news
         ├── stadium
         └── running_leagues  (coordinación multi-worker)
```
