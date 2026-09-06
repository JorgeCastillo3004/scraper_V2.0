# Sesión 2026-06-03 — Verificación de reciclaje + diseño de ejecución paralela multi-driver

Trabajo sobre el panel (`api/` + `frontend/`) apuntando al **remoto**
`96.30.195.40/sports_db` (modo visualización autorizado). Ver
[INDICE.md](INDICE.md), [RUNBOOK_PANEL.md](RUNBOOK_PANEL.md) y
[especificacion_parallel_panel.md](especificacion_parallel_panel.md).

---

## 1. Panel levantado
- API `uvicorn api.main:app` puerto **8009**; frontend Vite puerto **5174** →
  http://localhost:5174/. Verificado: `GET /api/stats/news` = 1088 noticias.
- Comandos de levantar/bajar: ver [RUNBOOK_PANEL.md](RUNBOOK_PANEL.md) §0.

## 2. Verificación del reciclaje del driver (corrida activa observada)
Había una corrida **viva** lanzada desde el panel:
`scripts/update_pending_matches.py --mode completo --apply` sobre 10 ligas mezcladas
(FOOTBALL ENGLAND/TURKEY/BRAZIL/CHILE/COLOMBIA/UAE/PERU/URUGUAY + BASKETBALL World Cup +
AM._FOOTBALL/USA NFL), población **581 partidos**. Log: `logs/update_matches_20260603_230347.log`.

**Reciclaje confirmado, implementado en `update_pending_matches.py`:**
- **Por MEMORIA, no por tiempo.** Chequeo entre cada partido (`_maybe_recycle` dentro de
  `_check_control`). Umbral **2048 MB** (`MEM_LIMIT_MB`, env `DRIVER_MEM_LIMIT_MB`,
  `update_pending_matches.py:54`). Mide PSS del árbol del driver por PID
  (`driver_session.driver_tree_pss_mb`) → SOLO el del scraper, no el Firefox del usuario.
- Al disparar: `relaunch_driver()` (detiene + relanza con login) y continúa en el mismo punto.
- **Frecuencia medida:** ~1 reciclaje cada ~5 min; **7 reciclajes en 77 partidos / ~34 min**.
  Cadencia variable (tras 18, 32, 42, 43, 49, 57, 77 partidos) porque depende de cuánto infla
  cada partido: los de basketball con stats inflan rápido; un solo partido pesado llevó el árbol
  de 2120→2928 MB de golpe. Tras cada reciclaje la memoria vuelve a ~900 MB. Funciona bien.
- **No había bug de "deporte equivocado":** el comando mezcla ligas de varios deportes a
  propósito (incluye BASKETBALL World Cup), por eso aparecían partidos de basket antes que
  Premier League. La corrida terminó/murió durante la sesión.

## 3. Diseño aprobado — ejecución paralela multi-driver desde el panel
El usuario pidió **N drivers en paralelo, cada uno con sus ligas**, controlados desde el panel.
Se revisó lo ya existente (regla: reusar, no reinventar) y se encontró la base:
- **`paralel_execution.py`** (raíz): N workers `ThreadPoolExecutor`, driver propio por worker,
  `split_into_dicts`, status por worker (`run_status_{section}.json`), control cooperativo y
  claim/release vía `running_leagues`. Hoy corre `extraction_by_dict` y el control es **global**.
- `live_runner.py` (patrón "driver propio"), `driver_session.py` (`driver_tree_pss_mb`,
  `relaunch_driver`).

**Decisiones del usuario:** (1) N=2 por defecto, configurable; (2) login simultáneo sin problema;
(3) sharding por **deporte+país+liga** (equipos compartidos → mismo worker); (4) **visible** por
defecto, una palabra en `config.py` para headless en servidor; (5) control **independiente por
worker** (Stop / Pause-Resume / **Cerrar driver** separados por cada driver).

→ Especificación completa con GAPs y plan: **[especificacion_parallel_panel.md](especificacion_parallel_panel.md)**.
**Se implementa en la próxima sesión.**

## 3b. Sesión 2026-06-04 (cont.) — Diagnóstico de "No encontrados" + 2 mejoras de panel aprobadas

**Diagnóstico (sin cambios de código, a pedido del usuario):**
- Botón **"Refrescar"** de Inconsistencias **funciona** (`fresh=1` saltea el caché de 60 s en
  `get_inconsistencias_summary`). Si el conteo no baja es porque los partidos siguen pendientes
  en la BD, no por el botón.
- `[FALTA]`/`No encontrados`: la URL de results (`leagues_info.json`) apunta a la **temporada
  actual** (ej. `/peru/liga-1/results/` = 2026); partidos de temporadas cerradas (nov 2025) no
  están en esa página (viven en `/archive/`). Confirmado por el usuario: "la página realmente no
  los contiene". Secundario: `load_until_date` oscila por la virtualización del DOM de FlashScore
  (cuenta solo filas renderizadas) y no detecta estancamiento. **Se decidió NO cambiar por ahora.**
- Conteo del RESUMEN **verificado correcto** (no hay doble conteo): `faltan N` es por liga,
  `No encontrados` es total. En `update_matches_20260604_070613.log`: Bolivia 1 + Perú 2 = 3.

**2 mejoras de panel APROBADAS → ver [especificacion_panel_resumen_y_dbhistory.md](especificacion_panel_resumen_y_dbhistory.md):**
1. Partir el RESUMEN de `update_pending_matches` en *Resumen de sesión* (por liga) + *Totalización*.
2. Visor de `db_history` al fondo del panel: salida tal cual `show_comparison`, navegación ◀▶
   entre snapshots, auto-snapshot al terminar la extracción. Consulta al remoto **autorizada**
   (solo SELECT).

## 3c. Sesión 2026-06-04 (cont.) — IMPLEMENTADO

**Mejora 1 — Resumen partido en dos bloques** (`scripts/update_pending_matches.py`):
acumula `per_league` durante el loop e imprime **RESUMEN DE SESIÓN** (por liga:
`LIGA · POB · OK · FALT · estado — encontrados X / Y en DB`) + **TOTALIZACIÓN** (global,
con `Población total`). Resuelve la confusión "faltan N (liga) vs No encontrados (total)".

**Estado por liga desde logs + visor de db_history en el panel:**
- `api/services/history.py` (NUEVO): `leagues_status_from_logs()` escanea
  `logs/update_matches_*.log` (de más reciente a más antiguo, primera aparición = última
  ejecución) → por liga: última ejecución (del nombre del archivo), cobertura
  `encontrados X / Y en DB`, estado (OK/faltan N). Visor db_history: `list_snapshots()`,
  `comparison_text(idx)` (captura `show_comparison` del script → texto tal cual),
  `take_snapshot()` (consulta remoto — solo SELECT, autorizado).
- `api/routers/history.py` (NUEVO): `GET /api/leagues_status`, `GET /api/db_history`,
  `GET /api/db_history/{idx}`, `POST /api/db_history/snapshot`. Registrado en `main.py`
  **antes** de `control` (catch-all). Auto-snapshot en `process_manager._reader_thread`
  al terminar `update_matches` (hilo daemon).
- `frontend/src/components/DbHistoryPanel.jsx` (NUEVO): al fondo de Inconsistencias.
  Tabla "Estado por liga" + visor db_history con navegación **◀ ▶** + "Tomar snapshot".
  Cliente: `getLeaguesStatus`, `getDbHistoryList`, `getDbHistory`, `takeDbHistorySnapshot`.
- Verificado: 31 ligas en estado (ej. `USA_NFL | encontrados 0 / 9 en DB | faltan 9`),
  98 snapshots, texto idéntico al script.

**Fix de `load_until_date`** (`scripts/fix_live_matches.py`) — el "bucle extraño":
- Causa: FlashScore migró a clases ofuscadas `wcl-*`; el botón `event__more`/`<a>` ya no
  existe (xpath viejo ambiguo), y el conteo usaba hijos del contenedor (inflado, no
  monótono por virtualización del DOM).
- Selector nuevo del botón (verificado en vivo, **1 único, visible, clickeable**):
  `//button[.//span[normalize-space()='Show more matches']]`. NO usar clases `wcl-*` (hash).
- Conteo real con `div.event__match`; espera **activa** a que crezca; corte por **fecha
  mínima acumulada** (monótona) o por **botón ausente / 2 clicks sin crecer** (estancamiento).
- Probado en vivo (Brazil Serie A): `109 → 177 partidos`, fecha `2026-03-22 → 2026-01-28`,
  corte en 2 iteraciones (antes oscilaba 172↔118 por 30 clicks).
- Sondeo del selector: `scripts/_debug_show_more_btn.py` (cuenta candidatos + sube por
  ancestros del span → reveló `<button data-testid="wcl-buttonLink">`).

**Pendiente detectado (NO resuelto):** WARNING de Postgres al conectar —
`database "sports_db" has no actual collation version, but a version was recorded`.
Fix = `ALTER DATABASE sports_db REFRESH COLLATION VERSION;` en el **remoto** (requiere
autorización; no borra datos pero es ALTER sobre la DB).

## 4. PRÓXIMA SESIÓN
1. Implementar según [especificacion_parallel_panel.md](especificacion_parallel_panel.md) §5
   (refactor driver inyectado → sharding → orquestador → backend panel → frontend → prueba apply).
2. Recordar: N=2 techo realista en esta máquina (7.6 GB); guardia global de RAM.
3. (Heredado) pendientes previos: opción A `--league-id` para Inconsistencias; 4 ligas ausentes
   del JSON (Football/ARGENTINA Torneo Betano, Hockey CZECH/FINLAND/GERMANY) — ver
   [sesion_inconsistencias_fix_frontend.md](sesion_inconsistencias_fix_frontend.md).
