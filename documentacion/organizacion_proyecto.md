# Organización del proyecto — plan / checklist

Documento vivo para **organizar correctamente scraper_V2.0**. Acá listamos
TODOS los puntos a ir revisando. Se marca el avance con `[ ]` / `[x]`.

> Este archivo NO implementa nada todavía: es la hoja de ruta acordada.

---

## 0. Visión general del proyecto (2 etapas)

```
ETAPA 1 — EXTRACCIÓN (carga inicial / programada)
   news  →  ligas  →  equipos  →  partidos (results + fixtures)  →  jugadores
   (milestone1 → milestone2 → milestone3 → milestone4 → ...)

ETAPA 2 — LIVE + MANTENIMIENTO
   • seguimiento de partidos EN VIVO (score/estado) y CIERRE al terminar
   • corrección de partidos PASADOS no cerrados / nunca actualizados
   (milestone7 / live_function / live_runner ; fix_live_matches ; fix_* )
```

---

## 1. Documento maestro de instrucciones de organización
- [ ] Definir y escribir las **reglas de organización** del repo (este doc + enlaces).
- [ ] Convención de carpetas: `src/` (milestones + core), `scripts/` (utilidades),
      raíz (¿orquestadores?), `check_points/`, `logs/`, `documentacion/`, `docs/`.
- [ ] Convención de nombres: `_debug_*` = scratchpad descartable; definitivos con
      nombre **descriptivo de su función**.
- [ ] Dónde viven los orquestadores (hoy `crear_fixtures_ligas.py` y
      `completado_de_ligas.py` están en la RAÍZ; decidir si van a `scripts/`).

## 2. Índice COMPLETO de scripts (con breve explicación + renombrar)
> ✅ **HECHO (2026-06-02):** índice completo de los 93 scripts en
> **[indice_scripts.md](indice_scripts.md)** (src/ + scripts/ + raíz, agrupados por tipo,
> 1 línea c/u). Mantenerlo al día al agregar/renombrar scripts. La tabla de abajo es el
> borrador inicial (queda como referencia histórica).
- [x] Inventariar **todos** los scripts de `src/` y `scripts/` (y raíz).
- [x] Breve explicación (1 línea) de cada uno.
- [ ] **Renombrar** los que no sean descriptivos (definir mapa viejo→nuevo).
- [ ] Marcar cuáles son **definitivos** vs **debug/scratchpad** (`_debug_*`) vs
      **obsoletos** (candidatos a archivar).
- [ ] Volcar el índice final en `INDICE.md`.

  Inventario inicial (a completar/renombrar):
  | Script actual | Tipo | Función (breve) | Nombre descriptivo propuesto |
  |---|---|---|---|
  | `src/milestone1.py` | core | extracción de noticias | (ok) |
  | `src/milestone2.py` | core | creación de ligas (`create_leagues`) | (ok) |
  | `src/milestone3.py` | core | creación de equipos | (ok) |
  | `src/milestone4.py` | core | extracción results/fixtures (`extraction_by_dict`) | (ok) |
  | `src/milestone7.py` | core | partidos en vivo | (ok) |
  | `src/data_base.py` / `common_functions.py` | core | acceso DB / utilidades | (ok) |
  | `crear_fixtures_ligas.py` | orquestador | crea fixtures faltantes + equipos + estadio + season (checkpoint, `--from-pin`) | (revisar ubicación) |
  | `completado_de_ligas.py` | orquestador | crea solo ligas pineadas faltantes | (revisar ubicación) |
  | `scripts/pin_leagues_match_count.py` | util | cuenta partidos en DB por liga pineada | (ok) |
  | `scripts/show_matches_db.py` | util | lista partidos en DB por fecha/deporte/liga | (ok) |
  | `scripts/fix_null_team_ids.py` | mantenimiento | crea equipos faltantes desde el match | (ok) |
  | `scripts/fix_inconsistent_matches.py` | mantenimiento | completa match_detail incompleto | (ok) |
  | `scripts/fix_live_matches.py` | mantenimiento | cierra partidos que quedaron LIVE; provee detectores (`get_pending_live_matches`, `get_stats_backfill_matches`) y helpers (`load_until_date`, `scan_results_page`, `scan_with_coverage`) reusados por el panel y el notebook | (ok) |
  | `scripts/update_pending_matches.py` | mantenimiento | completa partidos pendientes (fecha<hoy: LIVE o score=-1) reusando el driver vivo; modos `rapido`/`completo` + backfill `--solo-sin-stats`; dry-run por defecto o `--apply`; pausa/stop cooperativo vía `run_control_update_matches.json`. Lo lanza el panel (sección `update_matches`, pestaña Inconsistencias) | (ok) |
  | `scripts/validate_id_leagues_info.py` | mantenimiento | compara `league_id`/`season_id`/`country_id` de `leagues_info.json` contra la DB (DB = verdad) y **corrige** el JSON con los IDs reales (confirma `[s/N]`). Solo valida entradas existentes; NO agrega ligas faltantes | (ok) |
  | `scripts/live_runner.py` | etapa 2 | runner de live | (ok) |
  | `scripts/_test_etapa{1,2,3}_*.py` | test | pruebas por etapa del flujo de completar partidos (cargar liga / detectar pendientes / "Show more" + scan); reusan driver vivo, solo lectura | test (no definitivo) |
  | `scripts/_debug_*.py` | debug | scratchpads (no definitivos) | archivar/ignorar |
  | … (completar el resto) | | | |

## 3. Diagrama del proyecto por milestone
- [ ] **Verificar** que el diagrama por milestone esté en el repo, cada milestone debe tener su diagrama al iniciao del modulo, mostranso sus entradas y salidas.
      (hay imagen de arquitectura en `README.md` y diagrama en `INDICE.md`).
- [ ] Confirmar que **cubre cada milestone** (1,2,3,4,7,8) y las 2 etapas.
- [ ] Si falta, completarlo.

## 4. Script de verificación de integridad de la DB  ⟵ NUEVO
- [x] Crear un script (read-only) que valide **toda** la info en `sports_db`
      → **`scripts/verificar_integridad_db.py`** (conexión `set_session(readonly=True)`;
      reusa `_INCONS_QUERIES`/`_STATUS_LEGACY_VALUES`/`get_conn` de `api/services/database.py`).
      19 chequeos en 4 familias; flags `--only/--limit/--by-league/--json/--list/--no-color`;
      exit code 2=high, 1=medium, 0=ok (gancho para Telegram §8.3 / cron).
  - [x] cada `match` con **2 `match_detail`** (`detail_no_2`) y que sean 1 home + 1 visitor (`detail_home_visitor`)
  - [x] cada `match` con `season_id`, `country_id`, `league_id` **válidos** (`match_no_season/country/league`)
  - [x] cada `match_detail` con `team_id` válido (`fk_roto_team`) + su `score_entity` (`detail_no_score`)
  - [x] cada `league` con `sport_id` válido (`league_no_sport`) y al menos una `season` (`league_no_season`)
  - [~] equipos en `league_team` consistentes con la liga/temporada (FKs ya forzadas en DDL; chequeo extra pendiente si se requiere)
  - [x] detectar **duplicados** (sport/league/country/team/season/match) y huérfanos
  - [x] reporte resumido por tabla + lista de inconsistencias (sin tocar datos)
- [x] Nombre descriptivo → `verificar_integridad_db.py`.
- [ ] **PROBAR contra la BD**: BLOQUEADO — `config.py` apunta a IP **remota**
      (`96.30.195.40`), no local. Requiere o apuntar a DB local, o autorización
      explícita para correr la auditoría read-only contra remoto.

## 5. Validar la arquitectura de 2 etapas
- [ ] **Etapa 1 (extracción)**: confirmar flujo news→ligas→equipos→partidos y
      qué script orquesta cada paso (milestones + `crear_fixtures_ligas` / `completado_de_ligas`).
- [ ] **Etapa 2 (live + mantenimiento)**:
  - [ ] live: `live_function` / `live_runner` (seguimiento + cierre)
  - [ ] pasados no cerrados/no actualizados: `fix_live_matches` (+ `fix_*`)
- [ ] Documentar cómo se dispara cada etapa (cron/`main.py`/manual).

## 6. Pendientes técnicos conocidos (de la sesión actual)
- [ ] `EUROPE / Champions League`: **3 filas duplicadas** en `league` → consolidar.
- [ ] `BRAZIL / Serie A Betano`: 26 fixtures **sin estadio** (la página no exponía VENUE).
- [ ] Ligas que no estaban en `leagues_info` y quedaron pendientes →
      `check_points/fixtures_progress/_PENDIENTES_COMPLETAR_*.json` (completar con
      `completado_de_ligas.py`).
- [ ] `page_load_timeout` + reintento en los scripts con driver (evitar cuelgues).

## 7. Integración del panel de control (FastAPI + React)  ⟵ NUEVO
El panel `api/` (FastAPI) + `frontend/` (React+Vite) es la UI **vigente** del scraper
(reemplaza al dashboard Flet, ya movido a `old_versions/dashboard/`). Está
funcionalmente completo en código (7 pestañas: Noticias, Ligas, Equipos, Partidos,
Jugadores, Live, Inconsistencias) pero quedó **a medio integrar**. Pendientes:

- [ ] **Oficializar** FastAPI+React como única UI; confirmar borrado de
      `old_versions/dashboard/` (Flet) cuando el usuario lo decida.
- [ ] **🔴 `teams` no respeta pause/stop limpio**: `paralel_teams.py` NO lee
      `run_control_teams.json` ni escribe `run_status_teams.json` → portar el
      mecanismo de `paralel_execution.py` (la UI ya tiene los botones).
- [ ] **🟠 `news`/`leagues`**: `run_news.py` / `run_leagues.py` tampoco usan
      `run_control`/`run_status` → stop no es limpio (pasadas cortas, menor riesgo).
- [ ] **🟠 Recompilar `frontend/dist`** (`npm run build`): el build (23-abr) está
      más viejo que el fuente (24-may); la API sirve `dist/` en producción.
- [ ] **🟠 Unificar puertos en docs**: `api.md`/`frontend.md` dicen API 8000 /
      Vite 5173; el real (`vite.config.js`) es API **8009** / Vite **5174**.
- [ ] **🟡 README de arranque** del panel (levantar API + front juntos, puertos
      reales). Hoy está disperso en `frontend.md` con datos viejos.
- [ ] **🟡 Commitear `api/` + `frontend/`** (hoy untracked → riesgo de pérdida).
- [ ] **🟡 Live: decidir camino** que expone el panel: `main2.py` (actual) vs
      `scripts/live_runner.py` + `src/live_function.py` (hot-swap nuevo).
- [ ] **⚠️ Confirmar a qué DB apunta `config.py`** (fuera de git) ANTES de
      levantar la API: debe ser **local**. Regla: nunca remoto sin permiso.
- [ ] Contrato de control/estado funciona OK para `results`/`fixtures`/`players`/
      `live` (leen `run_control`, escriben `run_status`) — usar como referencia
      al portar a `teams`/`news`/`leagues`.

## 8. Ideas fundamentales / visión funcional (a definir)  ⟵ NUEVO
Objetivos de alto nivel acordados. **Detalles aún por definir** — esto fija el
norte, no la implementación. Varios cruzan con secciones previas (se enlazan).

### 8.1 Control total del scraper desde el frontend
- [ ] Controlar **extracción de noticias** desde la UI (ya hay pestaña Noticias;
      definir alcance fino).
- [ ] **Seleccionar qué ligas** extraer (results/fixtures/teams/players) desde la UI.
- [ ] **Extracción granular**: por deporte / país / liga / temporada / rango de
      fechas / sección — poder lanzar trozos puntuales sin correr todo el pipeline.
- [ ] Cruza con **§7** (cerrar contrato de control en `teams`/`news`/`leagues`).
- [ ] *Detalles concretos: PENDIENTES de definir.*

### 8.2 Validación exhaustiva de toda la data + alertas para completar
- [ ] Validar **toda** la BD (ver el script de integridad de **§4**) y, además de
      reportar, **emitir alertas accionables** de qué falta completar
      (ligas sin season, matches sin estadio, score=-1, FK rotas, detail≠2, etc.).
- [ ] Conectar el resultado con la pestaña **Inconsistencias** (ya existe el
      diagnóstico) → que indique el camino de corrección por categoría.
- [ ] Cruza con **§4** (integridad read-only) y con la pestaña Inconsistencias.

### 8.3 Alertas de fallos del scraper vía Telegram
- [ ] **Reusar `src/telegram_notify.py`** (`notify()` + `build_hourly_summary()`;
      gated por `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` en `config.py`).
      Hoy SOLO lo usa `scripts/live_runner.py` (resumen horario de LIVE).
- [ ] **Extender** a todo el pipeline: avisar fallos/cuelgues/excepciones de cada
      sección (news, leagues, teams, results, fixtures, players, live) y de los
      workers paralelos.
- [ ] Definir política: qué eventos alertan, anti-spam (agrupar), severidad.
- [ ] *Detalles concretos: PENDIENTES de definir.*

### 8.4 Integración total de herramientas y scripts
- [ ] Que **todo** lo desarrollado (milestones, orquestadores `crear_fixtures_ligas`
      / `completado_de_ligas`, fixes `fix_*`, utilidades `scripts/*`, live_runner,
      validación de integridad) quede **integrado y accesible** de forma coherente
      (idealmente desde el panel y/o un punto de entrada único documentado).
- [ ] Es el objetivo paraguas de **§1 (carpetas/orquestadores)** + **§2 (índice de
      scripts)** + **§7 (panel)** — esta línea los amarra en un solo sistema.

---

## Referencias
- Metodología: [metodologia_desarrollo.md](metodologia_desarrollo.md)
- Reglas driver: [../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md)
- Sesión fixtures + scripts: [sesion_fixtures_y_scripts.md](sesion_fixtures_y_scripts.md)
- Índice general: [INDICE.md](INDICE.md)
