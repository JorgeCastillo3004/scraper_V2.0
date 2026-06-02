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
| [creacion_APP.md](creacion_APP.md) | Propuesta original de la app de control |

## Infraestructura

| Archivo | Descripción |
|---|---|
| [desarrollo_local.md](desarrollo_local.md) | Levantar DB Docker, API, frontend y geckodriver localmente |
| [mejoras_performance.md](mejoras_performance.md) | Validaciones de integridad en DB y cierre de partidos con score `-1,-1` |
| [indicaciones_para_desarrollo.md](indicaciones_para_desarrollo.md) | Guía general de desarrollo y testing: driver compartido, scratchpad → definitivo, logs, heartbeat, checkpoints, idempotencia, recovery |
| [metodologia_desarrollo.md](metodologia_desarrollo.md) | Diagrama del flujo de desarrollo (entender→diseñar/aprobar→implementar→probar incremental→verificar/documentar) + principios no negociables |
| [organizacion_proyecto.md](organizacion_proyecto.md) | **Plan/checklist** para organizar el proyecto: doc maestro, índice completo de scripts (+renombrar), diagrama por milestone, script de integridad de DB, arquitectura 2 etapas, pendientes |

## Sesiones / scripts de mantenimiento

| Archivo | Descripción |
|---|---|
| [indice_scripts.md](indice_scripts.md) | **Índice COMPLETO de los 93 scripts** del proyecto (src/ + scripts/ + raíz), agrupados por tipo, 1 línea c/u. Referencia para no reinventar funciones/módulos. Mantener al día |
| [sesion_fixtures_y_scripts.md](sesion_fixtures_y_scripts.md) | Sesión 2026-05-30: creación de fixtures faltantes (`crear_fixtures_ligas.py`) + índice de scripts desarrollados y fixes de fondo (naming de deporte, sufijo de fase, `league_id` viejo en JSON, estadio en bloque nuevo) |
| [sesion_organizacion_integridad.md](sesion_organizacion_integridad.md) | Sesión 2026-06-01: Flet archivado a `old_versions/`, plan ampliado (§7 panel, §8 visión), y **`scripts/verificar_integridad_db.py`** (auditoría read-only, 19 chequeos). PENDIENTE: probarlo (config.py apunta a remoto) |
| [sesion_inconsistencias_fix_frontend.md](sesion_inconsistencias_fix_frontend.md) | Sesión 2026-06-02: log accionable del script de integridad (.log/.json), Noticias (fecha última noticia + scheduler embebido cada N horas), y **corrección de Inconsistencias por liga desde la UI** (sección `fix_results` dry-run + control de driver `/api/driver/*`). Cómo levantar el servicio. GAP league_id (opción A pendiente). **PRÓXIMA: levantar servicio + seguir pruebas de completado de partidos pasados desde el frontend** |

## Runbooks operativos

| Archivo | Descripción |
|---|---|
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
