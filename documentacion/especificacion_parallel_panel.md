# Especificación — Ejecución paralela multi-driver controlada desde el panel

> Estado: **APROBADO el diseño 2026-06-03 — pendiente de implementar (próxima sesión).**
> Objetivo: completar/actualizar partidos pasados (`update_pending_matches`) con
> **N drivers en paralelo**, cada uno con su subconjunto de ligas, **controlados de
> forma independiente desde el panel** (start / pause / resume / stop / cerrar driver
> por cada worker). Reusar lo ya existente; **no reinventar**.

Ver también: [RUNBOOK_PANEL.md](RUNBOOK_PANEL.md), [api.md](api.md),
[indicaciones_para_desarrollo.md](indicaciones_para_desarrollo.md),
[sesion_2026-06-03_parallel_design.md](sesion_2026-06-03_parallel_design.md),
`docs/DRIVER_RULES.md`.

---

## 1. Decisiones aprobadas por el usuario (2026-06-03)

| # | Decisión |
|---|---|
| 1 | **N = 2 workers por defecto**, configurable a más (parámetro). |
| 2 | **Login simultáneo de la misma cuenta: SIN problema** (la cuenta tolera sesiones múltiples). No hace falta escalonar el login. |
| 3 | **Sharding por DEPORTE + PAÍS + LIGA**: las ligas se reparten agrupando por deporte y país, de modo que los equipos compartidos (p. ej. una selección nacional en dos torneos) caigan en el **mismo worker** → evita doble inserción de teams (cache de `create_team_in_db` es por hilo/proceso). |
| 4 | **Visible por defecto**, configurable con **una sola palabra en `config.py`** para pasar a headless en el servidor (sin tocar código). |
| 5 | **Control desde el panel, INDEPENDIENTE por cada driver**: botones **Stop**, **Pause/Resume** y **Cerrar driver** separados para cada worker (no globales). |

---

## 2. Qué se REUSA (base ya construida)

| Pieza existente | Qué aporta | Archivo |
|---|---|---|
| **`paralel_execution.py`** | Orquestador N workers vía `ThreadPoolExecutor`; cada `worker()` lanza su **propio** driver (`launch_navigator`, retry hasta 8); reparto de ligas (`split_into_dicts`); status por worker (`write_status` → `logs/run_status_{section}.json` con `workers[].status/league/lines`); control cooperativo (`read_control`/`write_control`/`_check_control_cmd`); claim/release vía `running_leagues` para no colisionar. | raíz |
| **`update_pending_matches.py`** | Lógica de completar partidos pasados (score=-1 / LIVE / backfill stats), reciclaje por memoria, control cooperativo `_check_control`. | `scripts/` |
| **`driver_session.py`** | `driver_tree_pss_mb()` (mide PSS del árbol por PID), `relaunch_driver()`. | `scripts/` |
| **`live_runner.py`** | Patrón **"driver propio"** (`launch_owned_driver`) + medición por PID en archivo (`tmp/live_driver.json`). | `scripts/` |
| **API/Frontend del panel** | Pestaña Inconsistencias ya lee status por WebSocket y dispara secciones; `driver_manager`, `process_manager`. | `api/`, `frontend/` |

**Modelo actual de `paralel_execution.py` (punto de partida):**
- N hilos (`ThreadPoolExecutor(max_workers=N)`), cada hilo = 1 worker = 1 driver propio.
- `split_into_dicts(enabled, N)` reparte ligas **round-robin** (`i % N`).
- `worker()` hace `launch_navigator(headless=True)` y corre `extraction_by_dict`.
- Status: `logs/run_status_{section}.json`. Control: `logs/run_control_{section}.json` (**GLOBAL** por sección).

---

## 3. GAPs a implementar (diferencia entre lo que hay y lo aprobado)

### GAP 1 — Tarea = completar partidos (no extracción)
Sustituir/parametrizar el cuerpo del worker para que ejecute la lógica de
**`update_pending_matches`** sobre su shard (modos `rapido`/`completo`/`solo-sin-stats`,
dry-run/apply) en vez de `extraction_by_dict`. Reusar las funciones ya validadas
(`get_pending_live_matches`, `scan_with_coverage`, `get_statistic_map`, etc. en
`scripts/fix_live_matches.py`). **Refactor clave:** `update_pending_matches` hoy usa el
driver global `get_driver()` (archivo único `tmp/driver_session.json`); debe aceptar un
**driver inyectado** (el del worker) para poder correr N en paralelo.

### GAP 2 — Sharding por deporte + país + liga
Reemplazar el round-robin de `split_into_dicts` por un reparto que **agrupe por
(deporte, país)** y asigne grupos completos a workers, **balanceando por nº de partidos**
(población), no por nº de ligas. Garantías: (a) una liga → un solo worker; (b) equipos de
un mismo país/deporte → mismo worker (evita duplicados de team). Mostrar la tabla de
distribución (ya existe `_show_distribution`) antes de arrancar / en el panel.

### GAP 3 — Control INDEPENDIENTE por worker
Hoy el control es global por sección. Pasar a **un archivo de control por worker**:
- `logs/run_control_{section}_w{idx}.json` con `{command: none|pause|resume|stop|close_driver}`.
- Cada worker lee SOLO su archivo en su checkpoint (`_check_control` entre partidos/ligas).
- `pause` → espera; `resume` → continúa; `stop` → sale del worker **sin matar a los demás**;
  `close_driver` → ese worker hace `relaunch`/quit **de SU propio driver** (PID propio),
  los otros siguen.
- El status pasa a reportar por worker: `pid`, `driver_pid`, `mem_mb`, `status`, liga actual,
  progreso (X/Y partidos del shard), nº reciclajes.

### GAP 4 — Reciclaje por memoria, por worker
Integrar el reciclaje de `update_pending_matches` (`_maybe_recycle`, umbral
`DRIVER_MEM_LIMIT_MB`) **por worker**, midiendo SOLO el árbol de **su** driver
(`driver_tree_pss_mb` filtra por PID → cada worker registra su `driver_pid` en
`tmp/parallel/driver_<idx>.json`). **Guardia global de RAM** en el orquestador: con 7.6 GB
y Firefox del usuario + panel vivos, **no permitir que dos workers relancen a la vez**
(serializar reciclajes); si `available` < umbral, escalonar. Umbral por worker más bajo que
en single (sugerido ~1300–1500 MB porque ahora compiten).

### GAP 5 — Visible/headless por `config.py`
`worker()` hoy fuerza `headless=True`. Cambiar a leer de `config.py` una sola variable
(p. ej. `PARALLEL_HEADLESS = False` por defecto → visible; en servidor poner `True`).
Reusar el patrón de `FIX_HEADLESS` ya existente. Documentar en `config_model.py`.

### GAP 6 — Integración al panel (control independiente por driver)
- **Backend (`api/`):** sección `parallel_update` en `process_manager`/`config.py`; router
  con endpoints **por worker**: `POST /api/parallel/{idx}/{pause|resume|stop|close_driver}`,
  `GET /api/parallel/status` (lee `run_status_{section}.json` + memoria por worker),
  `POST /api/parallel/start` (params: N, modo, dry-run/apply, sharding). Stream de logs por
  worker a WebSocket `/ws/parallel/{idx}/logs`.
  ⚠️ Registrar este router **antes** del catch-all de `control` (mismo bug ya resuelto con
  driver/scheduler — ver sesión 2026-06-02).
- **Frontend:** pestaña (o sub-vista en Inconsistencias) con **un panel por worker** en
  columnas (reusar la idea de `_build_layout`): título, liga actual, progreso X/Y, mem MB,
  nº reciclajes, terminal en vivo, y **botones Pause/Resume · Stop · Cerrar driver
  independientes** por worker. Un control global opcional ("pausar todos") es secundario.

### GAP 7 — Persistencia / reanudación / aislamiento
- Un session-file por worker: `tmp/parallel/driver_<idx>.json` (session_id, executor_url,
  launcher_pid, driver_pid). **Profile dir y puerto de geckodriver propios** por driver
  (`launch_navigator` ya asigna puerto; verificar profile aislado).
- Logs por worker: `logs/parallel/worker_<idx>_<ts>.log` + log agregado del orquestador.
- Checkpoint de shard (ligas/partidos completados) para reanudar si un worker muere.
- **Regla sagrada:** un worker SOLO toca su propio driver/PID. **Nunca `pkill firefox`**
  (Firefox del usuario vivo). `close_driver`/reciclaje = SIGTERM al launcher propio +
  `quit()` del browser propio. Ver `docs/DRIVER_RULES.md`.

---

## 4. Restricción de hardware (dimensionar N)

Servidor de desarrollo: **7.6 GB RAM total**. Con la corrida single, un Firefox llegó a
**~3 GB** y disparó el OOM-killer. En paralelo: cada Firefox puede crecer a 2–3 GB →
**N=2 es el techo realista visible** en esta máquina (con reciclaje agresivo). En el
servidor de producción (headless + más RAM) se podrá subir N. Por eso N es configurable y
hay guardia global de RAM (GAP 4).

---

## 5. Plan de implementación (próxima sesión, incremental)

1. **Refactor** `update_pending_matches` → aceptar driver inyectado + control/log por worker
   (sin romper el uso single actual).
2. **Sharding** por deporte+país+liga balanceado por población (GAP 3 reparto).
3. **Orquestador**: adaptar `paralel_execution.py` (o nuevo `parallel_update_runner.py`) para
   correr la tarea de completar partidos con drivers propios + control por worker + reciclaje
   por worker + guardia global de RAM. Probar primero **N=1 dry-run**, luego **N=2 dry-run**.
4. **Backend panel**: endpoints por worker + status + WS.
5. **Frontend panel**: panel por worker con botones independientes.
6. **Prueba apply** con N=2 visible en local; medir RAM y reciclajes; documentar.

Cada paso: probar incremental antes de seguir (ver `metodologia_desarrollo.md`).

---

## 6. Puntos abiertos (a confirmar al implementar)

- Hilos (`ThreadPoolExecutor`, modelo actual) vs procesos separados. Hilos bastan (I/O-bound,
  driver propio por hilo, GIL no estorba) y simplifican el status compartido; evaluar si
  `close_driver`/reciclaje individual es más limpio con procesos. **Decisión preliminar: hilos.**
- Umbral exacto de reciclaje por worker y de la guardia global de RAM (medir en N=2).
- Si el sharding deja workers muy desbalanceados (un país con muchísimos partidos), permitir
  partir esa liga igualmente — pero entonces cuidar duplicados de team (mismo país en 2 workers).
