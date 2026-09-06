# Inconsistencias — flujo "team_id inexistente" — estado y pendientes

> Generado: 2026-06-12 · Foco: automatizar la corrección de partidos con
> `team_id` inexistente (`fix_null_team_ids.py`) para que corra **1×/día a hora fija**.

---

## 1. Decisiones de arquitectura (acordadas)

| # | Decisión | Implicación |
|---|---|---|
| 1 | **`live` usa su propio driver y NUNCA se detiene** | El job de inconsistencias **no toca** `live` ni su driver (`tmp/live_driver.json`). Sin colisión. |
| 2 | El job usa el **driver de corrección/inconsistencias** (`tmp/driver_session.json`), que **sí puede compartirse** con otras secciones del panel | Como sólo corre 1×/día a una hora específica, el riesgo de solape es bajo. Igual conviene un guard de no-solape. |
| 3 | Pendiente de definir: **snapshot vs dinámico** (ver §5) | Es la única decisión que falta para implementar. |

Confirmado en código (`api/services/driver_manager.py`):
- **corrección** (Inconsistencias / `fix_results`) → `tmp/driver_session.json`, headless por `FIX_HEADLESS`
- **live** (Live Scores) → `tmp/live_driver.json`, headless por `LIVE_HEADLESS`

---

## 2. Verificación: el motor YA existe

| Componente | Estado | Detalle |
|---|---|---|
| Inconsistencia detectada | ✅ | Cards `fk_roto_team` + `detail_no_score` (`get_inconsistencias_summary`) |
| Script de corrección | ✅ | `scripts/fix_null_team_ids.py` — cierra `match_detail.team_id IS NULL` navegando FlashScore, crea teams faltantes y repara `score_entity` |
| CLI desatendible | ✅ | `--apply` (default dry-run), `--headless`, `--league SPORT/KEY` (repetible), `--match-id`, `--session-file`. Sin `input()`/confirm interactivo |
| Reuso de driver | ✅ | `_reuse_driver_session()` / `get_or_launch_driver(reuse=True)`; si no hay vivo, auto-lanza `launch_detached_driver(headless=True)` |
| Respeta reglas del proyecto | ✅ | Sólo INSERT/UPDATE; `driver.quit()` sólo con `--quit-at-end` explícito |
| Wiring en el panel | ✅ | `process_manager` sección `fix_results` → botón "Corregir teams inexistentes" en `Inconsistencias.jsx` |
| **Ejecución periódica** | ❌ | El scheduler embebido (`api/services/scheduler.py`) está cableado **sólo para noticias** |

**Conclusión:** el motor está 100% listo. Falta sólo la **capa de automatización**.

---

## 3. Datos reales (API viva `:8009`, `fresh=1`, 2026-06-12)

| Categoría | Total | Mapeables (corregibles) | Script |
|---|---|---|---|
| `fk_roto_team` (team_id NULL) | **689** | 15/15 top — todas mapeables | `fix_null_team_ids` |
| `detail_no_score` (COMPLETED sin score_entity) | **12** | 2/2 mapeables | `fix_null_team_ids` |
| **Total a atacar** | **~701 partidos** | — | — |

Top ligas afectadas (`fk_roto_team`):

| Cantidad | Deporte | País / Confederación | Liga |
|---|---|---|---|
| 160 | Football | WORLD | World Cup |
| 134 | American Football | CANADA | CFL |
| 58 | Football | SOUTH AMERICA | World Cup |
| 58 | Football | ASIA | World Cup |
| 58 | Football | AUSTRALIA & OCEANIA | World Cup |
| 58 | Football | EUROPE | World Cup |
| 58 | Football | NORTH & CENTRAL AM | World Cup |
| 36 | Football | AFRICA | World Cup |
| 18 | Football | CHINA | Super League |
| 10 | Basketball | EUROPE | Champions League |
| 7 | Football | COSTA RICA | Primera Division |

`detail_no_score`: CHILE / Liga de Primera (8) · CANADA / CFL (4).

---

## 3-bis. Pasos VERIFICADOS para "agregar equipos faltantes"

Flujo exacto de `fix_null_team_ids.py` (función `fix_null_team_ids`), por liga y por
partido afectado:

1. **Agrupar** los partidos detectados por `league_id`.
2. **Driver**: reusar el de corrección (`tmp/driver_session.json`); si no hay, lanzar
   (headless según `--headless`/`FIX_HEADLESS`). `keep_alive=True` → **nunca** `quit()`.
3. Por liga: navegar a `results_url` (de `leagues_info`), `dismiss_cookies`.
4. **Scan cache persistente**: mapear cada `match_id` afectado → link a su página de
   partido (sólo escanea lo no cacheado; carga hasta la fecha más vieja).
5. Por partido afectado, navegar a su página y aplicar los pasos según flags:
   - **PASO 1 — `needs_team_fix` (team_id NULL):**
     - `get_team_links_from_match` → URLs de home y away.
     - `ensure_team_created(team_url, …)` por cada equipo:
       - *cache hit* por `team_url` → reusa `team_id` sin navegar; o
       - navega a la página del equipo → `get_teams_info_part2` (extrae datos) →
         mapea `team_country` → `country_id` → **`create_team_in_db`** (milestone3,
         INSERT/UPSERT del team) → crea **stadium** si la página lo expone →
         **sincroniza el JSON de la liga** (`upsert_team_in_league_json`) → actualiza
         cache de URL.
     - **`update_match_detail_team`** → UPDATE `match_detail` con `home/away team_id`.
     - Guards: si faltan links, no se resuelven los 2 teams, o son el mismo →
       `save_problem(...)` (queda registrado, no rompe la corrida).
   - **PASO 2 — `needs_score_fix` (COMPLETED sin score):** `fix_score_entities` →
     INSERT en `score_entity`.
   - **PASO 3 — `needs_stats_fix`:** `fix_match_statistic` → UPDATE `match.statistic`.
6. **Resumen** final: ligas procesadas, matches detectados/reparados, scores y stats
   agregados, errores.

> Sólo INSERT/UPDATE (crea teams/stadiums, completa match_detail/score/stats).
> Nunca DELETE. El `driver.quit()` sólo ocurre con `--quit-at-end` (no se usa aquí).

---

## 4. Estado de implementación (✅ hecho en esta sesión / ⏳ pendiente)

Decisión tomada: **modo DINÁMICO** (atacar cada día todas las ligas mapeables con
el problema). Driver: el de **corrección** (compartible), live intocable.

| # | Ítem | Estado | Detalle |
|---|---|---|---|
| 1 | Generalizar el scheduler a `fix_results` (disparo diario) | ✅ hecho | `scheduler.py`: `_fix_tick`/`_run_fix` disparan `pm.start_process('fix_results', …)` |
| 2 | Bloque de config persistente | ✅ hecho | `FIX_TEAM_IDS` en `CONFIG.json`: `ENABLED`, `AT_HOUR`, `APPLY`, `EXCLUDE` |
| 3 | Ancla "hora del día" (1×/día) | ✅ hecho | `_fix_due` / `_next_fix_run` (no por intervalo) |
| 4 | Garantía de driver de corrección vivo | ✅ hecho | `_ensure_correction_driver` (driver_manager, headless `FIX_HEADLESS`) |
| 5 | Política `apply` persistida (sin confirm en headless) | ✅ hecho | `APPLY` en config (default `false` = dry-run) |
| 6 | Guard de no-solape | ✅ hecho | No dispara si `fix_results` ya está `running`; marca `last_run` antes de trabajar |
| 7 | Endpoint + UI | ✅ hecho | `GET /api/scheduler/inconsistencias`, `POST …/run`; panel `FixSchedulerPanel` en `Inconsistencias.jsx` |
| 8 | Persistencia de `last_run` | ✅ hecho | `logs/scheduler_fix_state.json` |
| 9 | Resolución dinámica de ligas | ✅ hecho | `_resolve_fix_leagues` (categorías `fk_roto_team`+`detail_no_score`, sólo mapeables) |
| 10 | Reporte/auditoría del run | ⏳ parcial | Queda en logs `fix_results_*.log` + `db_history`; falta resumen/notificación dedicada |
| 11 | Cobertura sólo "top 15" del resumen | ⏳ nota | `by_league` cachea top-15 por categoría; la cola larga (~22 partidos hoy) no entra. Mejorable con query completa |

---

## 5. Verificación contra la BD viva (2026-06-13)

```
_resolve_fix_leagues({})  → 16 ligas dinámicas:
  FOOTBALL/WORLD_World Cup, AM._FOOTBALL/CANADA_CFL,
  FOOTBALL/{SOUTH AMERICA,ASIA,AUSTRALIA & OCEANIA,EUROPE,
            NORTH & CENTRAL AMERICA,AFRICA}_World Cup,
  FOOTBALL/CHINA_Super League, BASKETBALL/EUROPE_Champions League,
  FOOTBALL/COSTA RICA_Primera Division, BASKETBALL/{ARGENTINA_Liga A,BRAZIL_NBB},
  FOOTBALL/{USA_MLS,MEXICO_Liga MX,CHILE_Liga de Primera}
_fix_due(04:00, now=08:10)  → True      _next_fix_run → 2026-06-14T04:00:00
get_fix_status()            → enabled=false (aún sin activar)
Frontend `npm run build`    → OK (101 módulos)
```

---

## 6. Cómo ACTIVAR

1. En el panel → **Inconsistencias** → tarjeta "Programación diaria":
   marcar **Activar disparo diario**, fijar la **hora**, dejar **dry-run** la
   primera vez (o marcar *Escribir en BD* cuando estés conforme) → **Guardar**.
2. Botón **Simular/Ejecutar ahora** para probar sin esperar la hora.
3. (Opcional) `FIX_HEADLESS=true` en `config.py` para que el driver del job no
   abra Firefox visible.

### ⚠️ Caveat de activación (importante)

La API viva (`uvicorn` pid actual) tiene el **scraper `live` como hijo**, y su
hook de apagado (`api/main.py` lifespan) **detiene todas las secciones `running`,
incluido `live`**. Por la regla *"live jamás se detiene"*, **no se reinició la API**
en esta sesión. Las rutas nuevas (`/api/scheduler/inconsistencias`,
`/api/inconsistencias/live-missing`) y el nuevo lifespan se activan **al próximo
reinicio de la API**, que debe hacerse en un momento en que detener `live` sea
aceptable, o tras independizar `live` del ciclo de vida de la API. La lógica ya
quedó **validada offline** contra la BD (§5, §7).

---

## 7. Ligas con partidos inexistentes detectadas por el LIVE (implementado)

Objetivo: que cuando el scraper `live` vea un partido en vivo que **no está en la
BD** (hoy solo loguea `[DB-SKIP]` y lo descarta), **registre la liga** para que la
sección Inconsistencias la cargue, verifique y se pueda extraer.

### Decisiones (acordadas)
- Granularidad: **una entrada por liga** (dedup por `sport|country|league`).
- Inconsistencias: **listar + estado + acción** (marcar resuelta / ignorar / reabrir).
- Alcance: **registrar + UI ahora**; disparar la extracción se cablea en un paso posterior.
- Archivo: **`check_points/live_missing_leagues.json`** (registro persistente).

### Qué se implementó
| Capa | Archivo | Detalle |
|---|---|---|
| Live (registro) | `src/live_missing.py` | `record_missing_league(sport, country, league, match)` — dedup, escritura atómica, preserva el `status` que ponga el panel; nunca borra |
| Live (enganche) | `src/milestone7.py` | En el `[DB-SKIP]` (`live_games`) llama a `record_missing_league(...)` con los datos del partido |
| API (servicio) | `api/services/live_missing.py` | `get_live_missing()` enriquece con `in_leagues_info` (clave `{COUNTRY}_{LEAGUE}` o match por `league_name`); `set_status()` cambia estado |
| API (rutas) | `api/routers/inconsistencias.py` | `GET /api/inconsistencias/live-missing`, `POST …/live-missing/status` |
| Frontend | `Inconsistencias.jsx` + `client.js` | Sección **"Ligas con partidos inexistentes detectadas por el Live"**: tabla con deporte/país/liga, veces, última detección, **Registro** (✓ registrada / nueva), estado y acciones |

### Esquema de `check_points/live_missing_leagues.json`
```json
{
  "updated_at": "ISO",
  "leagues": {
    "FOOTBALL|ARGENTINA|Liga Profesional": {
      "sport": "...", "country": "...", "league": "...",
      "count": 7, "first_seen": "ISO", "last_seen": "ISO",
      "status": "pending",            // pending | resolved | ignored
      "sample_matches": ["Home~Away", ...]   // hasta 10
    }
  }
}
```

### Verificación end-to-end (2026-06-13)
```
record_missing_league x4 (1 liga real + dedup, 1 liga "nueva")
  → JSON dedup OK (count=3 / count=1, sample_matches deduplicadas)
get_live_missing() → counts {pending:2, in_leagues_info:1, new:1}
  ARGENTINA/Liga Profesional → in_leagues_info=True  (key ARGENTINA_Liga Profesional)
  NARNIA/Liga Fantasia       → in_leagues_info=False (liga nueva)
set_status(resolved) → persiste OK
py_compile + import router (3 rutas) + npm run build → OK
```

### Botón de extracción (cableado → `crear_fixtures_ligas.py`)
El script que implementa la lógica pedida **ya existía**: `crear_fixtures_ligas.py`
(verificado en detalle). Hace exactamente:
1. Va al link de **fixtures** de la liga (`leagues_info[...]['fixtures']`).
2. `expand_all_fixtures()` → click en **"mostrar más"** hasta cargar todos los partidos.
3. `scan_fixtures_page()` → detecta todos los matches.
4. Por cada match entra y: `ensure_team_created` (verifica si el team existe; si no,
   lo crea + `league_team` + stadium) y `create_match` (`save_math_info` +
   `save_details_math_info` + `save_score_info` → match con score_entity), con
   `check_match_duplicate` anti-duplicado.

Reusa `fix_null_team_ids` (driver, team links, ensure_team_created) y `milestone4`
(get_result, get_match_info). Default **DRY-RUN**; `--apply` escribe. NUNCA DELETE.

**Wiring del panel** (sección `extract_fixtures`, nueva):
- `build_command`: `crear_fixtures_ligas.py --sport SPORT --leagues "KEY" [--apply]
  [--no-reuse --session-file tmp/extract_fixtures_driver.json]`.
- Solo para ligas **registradas** (`in_leagues_info`); las "nuevas" requieren alta manual.
- Logs en vivo + botón Detener en el mismo panel (WebSocket `extract_fixtures`).

**Opciones de driver (requerimiento del usuario):**
- **Por defecto: el MISMO driver** de corrección (reusa `tmp/driver_session.json`).
- Checkbox **"Lanzar driver propio"** → `--no-reuse --session-file
  tmp/extract_fixtures_driver.json` (driver nuevo e independiente, si el de
  corrección está ocupado). Se añadieron `--no-reuse` y `--session-file` al script.
- Checkbox **"Escribir en BD"** (default dry-run).

---

## 8. Reinicio de API y verificación integral (2026-06-13)

### Reinicio de la API (live protegido)
- `api/main.py` lifespan ahora **excluye `live`** del apagado automático
  (regla *live jamás se detiene*). `live` no estaba corriendo al reiniciar.
- API reiniciada (uvicorn detached). Rutas nuevas activas y verificadas en vivo.

### Matriz de verificación
| Requerimiento | Estado | Evidencia |
|---|---|---|
| Corrección diaria team_id (modo dinámico) | ✅ | `_resolve_fix_leagues` → 16 ligas reales |
| Disparo 1×/día a hora fija (no intervalo) | ✅ | round-trip API: AT_HOUR 23:59 → `next_run` 23:59, no disparó |
| Usa driver de corrección, no toca live | ✅ | `_ensure_correction_driver` (driver_manager.correction) |
| No-solape + apply persistido (dry-run def.) | ✅ | guard `fix_results running`; `APPLY` en config |
| Endpoints scheduler + UI | ✅ | `GET /api/scheduler/inconsistencias` 200; `FixSchedulerPanel` |
| Persistencia `last_run` / config | ✅ | `scheduler_fix_state.json`; `FIX_TEAM_IDS` round-trip |
| Pasos "agregar equipos faltantes" | ✅ | §3-bis (code-verified) |
| Live registra ligas faltantes (DB-SKIP) | ✅ código / ⏳ live real | `milestone7` enganchado; e2e unit OK; falta un ciclo live real |
| Dedup por liga + JSON en check_points | ✅ | e2e: count/dedup/sample OK |
| Sección Inconsistencias: cargar+estado+acción | ✅ | `GET …/live-missing` 200; `set_status` OK; `LiveMissingPanel` |
| Botón Extraer (ligas registradas) | ✅ cableado / ⏳ run real | `crear_fixtures_ligas.py` (fixtures→mostrar más→match→team+match+score); opción mismo driver (def.) / driver propio; build_command OK; sección `extract_fixtures` registrada |
| Sin DELETE (solo INSERT/UPDATE/JSON) | ✅ | revisado en todo el cambio |

### Cómo activar el job diario
Panel → Inconsistencias → "Programación diaria": **Activar**, fijar **hora**,
dejar **dry-run** la 1ª vez (luego marcar *Escribir en BD*), **Guardar**. Botón
**Simular/Ejecutar ahora** para probar sin esperar. (Default actual: desactivado.)

### Pendiente de validación real (no bloqueante)
- Un **ciclo live** que detecte un DB-SKIP → poblará `live_missing_leagues.json`.
- Un **run de extracción** real desde el botón Extraer.
- Estos requieren driver/login en vivo; el cableado quedó verificado por unidad.
