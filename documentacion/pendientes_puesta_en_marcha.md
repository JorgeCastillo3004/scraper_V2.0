# Pendientes — Puesta en marcha (scraper permanente + panel en servidor)

> **Objetivo final:** dejar el scraper corriendo **permanentemente** en el servidor 1
> (`104.156.244.145` / `ssh scraper_server`) con el **panel** para solo **ver y
> configurar frecuencias**. Live siempre vivo, Noticias por horario, Inconsistencias
> auto-reparándose. **Todo se valida en LOCAL primero; nada al servidor sin OK explícito.**
>
> Diseño base: [`especificacion_ejecucion_permanente.md`](especificacion_ejecucion_permanente.md)
> (Paso 1 en código, sin probar; pasos 2–6 pendientes).
>
> **Estado:** creado 2026-07-11. Se ataca **uno a uno**, en orden.

---

## Leyenda
`[ ]` pendiente · `[~]` en curso · `[x]` hecho · `[?]` bloqueado por decisión de Jorge

---

## P0 — Arreglar el completado de partidos (CORRECTNESS) 🔴 prioridad máxima
El completado manual matcheó **0 de 97** partidos (6 ligas) en la última corrida.
Automatizar una reparación que devuelve 0 no repara nada. **Prerrequisito de todo lo demás.**

### 🎯 CAUSA RAÍZ (diagnosticada 2026-07-11)
FlashScore **renombró la clase del horario**: `event__time` ya no existe (ahora es
`event__stageTime` + clases `wcl-*` con hash). En `src/milestone4.py:111`:
```python
match_date = row.find_element(By.CLASS_NAME, 'event__time').text   # ← 0 elementos → NoSuchElementException
```
es la **primera** línea de `get_result()` y **no está protegida**. Lanza excepción en
CADA fila. `scan_results_page` (fix_live_matches.py:374-377) la envuelve en
`except Exception: continue` → traga el error → la fila se descarta → **0 encontrados
en TODOS los deportes/ligas** (por eso es un 0 limpio y global, no un desajuste de
nombres). Verificado: nombres/scores/link-regex OK; solo la fecha rompe.
Efecto secundario: `get_last_visible_date` (fix_live_matches.py:202) también lee
`event__time` → devuelve None (log `fecha más antigua=None`).

Diagnóstico reproducido con `scripts/_debug_cobertura*.py` / `_debug_getresult.py` /
`_debug_time.py` (adjuntados al driver vivo, sin perturbarlo).

### Fix APLICADO y VERIFICADO (2026-07-11) ✅
- [x] `src/milestone4.py:111` — fecha con fallback guardado `event__time` →
      `event__stageTime` → `''` (try/except `NoSuchElementException`).
- [x] `get_last_visible_date` (fix_live_matches.py:202) — se arregla **solo**: llama a
      `get_result` internamente, así que el mismo fix corrige el `None` de la fecha.
- [x] Blast radius revisado: `get_result` la usan también `crear_fixtures_ligas.py`
      (fixtures), `milestone4` `_old` y `milestone2`; el fallback las mejora sin romper
      el caso con `event__time` presente. **`event__stageTime` no existía en el repo** →
      hay lecturas directas de `event__time` en `milestone2:171` y
      `extract_football_match.py:70` que podrían estar rotas igual (ver P0b).
- [x] Verificado NPB dry-run: **0/28 → 28/28**. Cobertura completa al primer click
      (antes clickeaba a 501 sin lograrlo); fecha parsea (`2026-06-28`, antes `None`);
      28 partidos con score real + 9 stats c/u, marcarían `status=COMPLETED`.
- **Descartado:** no era sesión (driver vivo), ni nombres, ni selectores de fila
      (`div.event__match` carga bien), ni `has_tip` (405/406 filas lo tienen).

### P0b — [PENDIENTE] Otras lecturas directas de `event__time` (riesgo relacionado)
El renombrado `event__time`→`event__stageTime` puede afectar otros paths:
- [ ] `src/milestone2.py:171` (`date = ...event__time...`) — verificar si rompe.
- [ ] `src/extract_football_match.py:70` — idem.
- [ ] `crear_fixtures_ligas.py:708-729` — ya usa `try` + lee campos directo; revisar
      que la heurística "sin prefijo DD.MM." siga válida con la clase nueva.

### P0c — ✅ HECHO (2026-09-06) — Completado real aplicado
- [x] Inventario read-only (`scripts/_debug_inventario_pendientes.py`, reusa las consultas
      de `fix_live_matches`): **875 a cerrar** (851 SCHEDULED con fecha pasada + **24
      colgados en LIVE**) en 16 ligas, + 429 sin estadísticas.
- [x] Dry-run NPB: **224/224** encontrados (el fix `event__stageTime` confirmado en volumen).
- [x] `--mode rapido --apply` sobre las 16 ligas: **858 de 875 escritos, 0 errores**.
      Pendientes a cerrar: **875 → 17**; partidos colgados en `status=LIVE`: **24 → 0**.
- [x] **CANADA_CFL resuelto**: 38/38 (antes 0/5). Era el mismo bug del DOM, no nombres/URL.
- [ ] **Quedan 17** (`FOOTBALL/WORLD_World Cup`, todos del 2026-07-02, 0/17 encontrados):
      son eliminatorias de selecciones (Iceland~Italy, Ivory Coast~Senegal, Jordan~Iran…)
      que en la BD cuelgan de `WORLD/World Cup` pero en FlashScore viven bajo su
      **confederación** (EUROPE/AFRICA/ASIA `World Cup`), así que la URL de la liga no los
      lista. Hay que corregir la clasificación o apuntar a la URL correcta.
- **Efecto colateral esperado:** el backfill de estadísticas pasó de 429 a **1.287**
      (los cerrados en modo rápido entran ahí: tienen score y status, les falta `statistic`).

## P1 — [DECISIÓN] Alcance de la auto-reparación de Inconsistencias `[?]`
Definir qué universo cubre "detecta inconsistencia → actúa":
- [ ] **(a)** Solo `live_missing_leagues.json` (ligas que el Live marca; 13 `pending` hoy)
      → es lo que `LIVE_MISSING_REPAIR` ya contempla.
- [ ] **(b)** Además todo el set del panel: `score=-1` global, `no_statistics` (323),
      `fk_roto_team`, `detail_no_2`, `detail_no_score`.
- [ ] Confirmar interpretación de *"a excepción live"* = la automatización no toca la
      sección Live en sí (solo lee su archivo de incidencias).
- **Bloquea:** P4 (activación real de la auto-reparación).

## P2 — [DECISIÓN] Dónde probar el engine en local `[?]`
La prueba está bloqueada porque `config.py` → remoto `96.30.195.40`.
- [ ] **(a, recomendado)** Levantar espejo local `sports_container` + apuntar `config.py`
      a BD local (`scripts/clonar_bd_local.sh`), probar sin riesgo.
- [ ] **(b)** Probar contra remoto CON autorización explícita de Jorge.
- **Bloquea:** P3.

## P3 — Probar el engine en local (ejecución permanente)
Depende de P2. El engine (`scripts/engine_runner.py`) está escrito, nunca ejecutado.
- [ ] Correr `ENGINE_OWNS_SCHEDULER=1 env_sports/bin/python -m scripts.engine_runner`.
- [ ] Verificar supervisión del **Live** (watchdog §5.1: si el loop muere, lo relanza).
- [ ] Verificar que **Noticias** dispara por horario (`EXTRACT_NEWS`).
- [ ] Verificar `LIVE_MISSING_REPAIR` en **dry-run** (`APPLY:false`) lee `pending` y
      simula la reparación.
- [ ] Verificar `tmp/engine_status.json` (heartbeat) y que el panel deja de correr el
      scheduler cuando el engine es dueño.
- [ ] **Driver 2 on-demand:** abre por demanda, cierra por ociosidad, no deja RAM colgada.
- [ ] **Cola serializada:** Noticias e Inconsistencias no corren a la vez en Driver 2.

## P4 — Activar auto-reparación con APPLY
Depende de P0 + P1 + P3.
- [ ] `CONFIG.json` → `LIVE_MISSING_REPAIR.ENABLED: true` (hoy `false`), tras validar en dry-run.
- [ ] Observar una ronda real: `pending` → `resolved` en `live_missing_leagues.json`.

## P5 — Panel como plano de control delgado (ver + configurar frecuencias)
- [ ] Confirmar que el frontend **expone y escribe** frecuencias a `CONFIG.json`
      (news `EVERY_HOURS`, live `interval`, inconsistencias `EVERY_MINUTES`, on/off, apply).
- [ ] API deja de correr el scheduler (`sched.start_scheduler()` fuera del lifespan).
- [ ] UI muestra `engine_status.json` (heartbeat, tarea/driver activo, last/next run).
- [ ] "Ejecutar ahora" escribe señal que el engine consume (run_now/run_league ackeados).

## P6 — Viabilidad del servidor para Selenium/Firefox — ✅ RESUELTO (2026-07-11/12)
- [x] El server **sí** corre Firefox headless: deploy `live_v2` operativo con Firefox 121
      + geckodriver linux64 0.35.0 propio (el del sistema era ARM → `Exec format error`).
- [x] Recursos verificados: **11 GB RAM** (no 7,6), 140 GB libres. Live + Firefox ≈ 1,4 GB
      estable → queda margen para un segundo driver si hiciera falta.
- [x] Headless forzado por `LIVE_HEADLESS=1` en `run_live.sh` (+ fix `main2.py:77`).
- Detalle: [`RUNBOOK_LIVE_SERVIDOR.md`](RUNBOOK_LIVE_SERVIDOR.md) §8.

## P7 — [DECISIÓN] Un solo escritor (local vs servidor) `[?]` — ⚠️ YA ES REAL
Ya no es hipotético: **el live del servidor está escribiendo en la BD remota desde
2026-08-30**. Local y servidor apuntan a la misma `sports_db`.
- [x] `config.py` del servidor = misma BD remota (confirmado).
- [ ] Definir: cuando corra el live del servidor, ¿el live local se apaga? (hoy la regla
      de facto es: el servidor es el dueño del Live; local solo para Inconsistencias/news).
- [ ] Definir el protocolo antes de correr algo pesado en local (mirar qué hace el live
      del servidor primero).

## P8 — Despliegue a systemd en el servidor — `[~]` PARCIAL (2026-08-30)
Se adelantó la pieza del **Live** (con OK de Jorge) tras 38 días caído por un reboot; el
resto (engine + panel) sigue pendiente.
- [x] **Live**: `scraper-live.service` de **usuario** instalado, `enable --now`,
      `Restart=always`, arranque tras reboot vía `loginctl enable-linger scraper`.
      No se pudo usar unidad de sistema: `scraper` no tiene sudo sin password.
- [x] **Rotación de logs**: `scraper-logrotate.timer` (cada 6 h) + `rotate_logs.sh`.
      `geckodriver.log` crecía 46 MB/día sin límite (275 MB acumulados).
- [ ] Instalar `deploy/scraper-engine.service` + `deploy/scraper-panel.service`
      (adaptar a unidades **de usuario**: los `deploy/*.service` del repo asumen root).
- [ ] Acceso remoto al panel verificado.
- Runbook: [`RUNBOOK_LIVE_SERVIDOR.md`](RUNBOOK_LIVE_SERVIDOR.md).

---

## Verificaciones que hace Claude (no requieren decisión de Jorge)
- [ ] Frontend realmente escribe frecuencias a `CONFIG.json`.
- [ ] `EXTRACT_NEWS` efectivamente dispara (mirar `scheduler_news_state.json` + logs).
- [ ] Estado de las 13 ligas `pending` y que el Live alimenta bien `live_missing_leagues.json`.

---

## Estado actual del sistema (contexto, 2026-08-30)
- **Servidor:** live corriendo bajo systemd (9 deportes, interval 60), 0 errores de BD,
  rotación de logs activa. Ver [`RUNBOOK_LIVE_SERVIDOR.md`](RUNBOOK_LIVE_SERVIDOR.md).
- **Local:** panel apagado (API 8009 / Vite 5174 sin levantar). Venvs, geckodriver y
  conexión a la BD remota verificados. El espejo local `sports_container` **ya no existe**
  (re-crear con `scripts/clonar_bd_local.sh` si se necesita para P2).
- **BD:** 10.416 matches (8.429 COMPLETED / 1.901 SCHEDULED / 69 OLD_SEASON / 17 LIVE).
- 🔴 **Deuda del incidente:** 17 partidos colgados en `status=LIVE` con fecha vieja
  (18/19-jun, 18/20/21/22-jul) que el live no va a corregir solo — FlashScore ya no los
  muestra en vivo. Requieren pasada de Inconsistencias.
- 🔴 **Sin alertas:** nadie avisa si el live muere. Telegram previsto en `config.py` pero
  con token/chat vacíos.

## Estado anterior (contexto, 2026-07-11)
- Panel arriba: API `:8009`, front `:5174`. Live corriendo (9 deportes, ciclo permanente).
- `CONFIG.json`: `EXTRACT_NEWS` ✅on (24h), `FIX_TEAM_IDS` ✅on (16:00),
  `LIVE_MISSING_REPAIR` 🔴off.
- `live_missing_leagues.json`: 20 ligas (7 resolved, 13 pending).
- Scheduler corre DENTRO de la API (engine aún no es dueño).
