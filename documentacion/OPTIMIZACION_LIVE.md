# Optimización del script LIVE — diseño

> **Estado: BORRADOR a revisar (2026-06-16).** Consolidación de las mejoras discutidas con
> Jorge para optimizar `main2.py` (scraper LIVE). Pendiente de revisión de detalles.
> Reúsa lo existente; no reinventa. Fuente de verdad = este doc (git) → se ingesta al RAG
> como `document` + `requirements` cuando esté el embedder local (Variante B / Tarea #7).

> **Estado de implementación (2026-06-16):**
> - ✅ **RL2 ventanas por deporte** — `src/live_windows.py` (nuevo) + integrado en
>   `milestone7.live_games`; validado read-only contra `sports_db` (Baseball se saltea fuera de
>   franja; Football con LIVE se polea). Fechas en **UTC** (`current_date = utcnow()`).
> - ✅ **RL1 productor** — ya existía (`src/live_missing.py`); + campos `missing_date` (UTC) y `source`.
> - ⏳ **Consumidor automático** (Inconsistencias auto-extrae) — plan listo (clonar tick de
>   `api/services/scheduler.py`), **default OFF**; pendiente de implementar.
> - 🔶 **RL4 driver dormido** — **NO implementado**: toca stop/start del driver dedicado →
>   requiere OK explícito de Jorge (regla de drivers) y es Fase 2.
> - ⚠️ Cambios staged en archivos: **toman efecto al reiniciar el Live**; probar local-first antes de prod.

---

## 1. Objetivo

Que el LIVE (1) **nunca pierda un partido** por no estar en la DB, y (2) **no navegue de más**:
que busque solo en los **períodos en que hay partidos** para cada deporte, reduciendo
navegación, solicitudes y RAM, sin degradar la calidad de actualización en vivo.

## 2. Problema actual

- **`[DB-SKIP]`:** el LIVE solo *actualiza* partidos existentes; si un partido en vivo no está
  en la DB (ej. MLB, World Championship) lo saltea → score real no se guarda.
- **Driver 24/7:** el LIVE usa su **driver dedicado** (Firefox propio). Medido: se mantiene en
  **~3.8 GB PSS de piso** (picos ~5.2 GB) **todo el día**, incluso en horas sin partidos
  (3–5 am). RAM ocupada sin trabajo útil.
- **Polleo plano:** cada ciclo recorre los 5 deportes fijos (`AM._FOOTBALL BASEBALL BASKETBALL
  FOOTBALL TENNIS`) haya o no partidos → navegación y content procs innecesarios.

## 3. Diseño general — LIVE dirigido por DB + scheduler

El LIVE evoluciona de "pollear todo cada ciclo" a dos fases:

- **Fase A — Prep (diaria/periódica):** asegurar que los fixtures del día estén en la DB.
- **Fase B — Loop en vivo:** navegar **solo** los deportes con ventana abierta o con partido
  LIVE; opcionalmente **dormir el driver** en huecos largos.

Fase B depende de Fase A: las ventanas se calculan desde la DB; si la DB está incompleta, las
ventanas mienten.

---

## 4. Fase A — Asegurar eventos del día en la DB (Idea 1)

**Qué:** antes de (y durante) la operación del LIVE, garantizar que todos los partidos de HOY
de las ligas activas existen en la DB. Si faltan, crearlos; si la liga no está registrada,
marcarla para completar.

> **Refinamiento (Jorge):** en esta fase el LIVE **NO crea registros**. Solo **detecta y
> registra las ligas con partidos faltantes** en el **archivo JSON** que consume la sección
> **Inconsistencias**; es esa sección la que luego procede a crearlos. (Patrón productor/consumidor.)

**Reúsa lo existente:**
- `crear_fixtures_ligas.py --today --from-pin` — detecta ligas pineadas con partidos de HOY
  faltantes y los crea desde la página SUMMARY (status+score reales: COMPLETED/LIVE/SCHEDULED).
- Sección **Inconsistencias / `update_matches`** — completa los que existen pero les falta
  score/stats. **Flujo automático (productor/consumidor):** el LIVE *detecta* y *registra* la
  liga problemática en el JSON; la sección **Inconsistencias / `update_matches`** lo **lee
  constantemente** y **dispara la extracción sola**, sin intervención manual.

**Detalles (no-negociables del diseño):**
1. **Cadencia:** correr el "asegurar" al **arranque del LIVE** y **re-chequear durante el día**
   (partidos agregados tarde, reprogramados, postergados). No una sola vez.
2. **Zona horaria:** definir "HOY" de forma canónica (fechas FlashScore vs `start_time` en DB
   con offset). Un partido 23:00 puede caer en otro día según TZ — fijar TZ de referencia o
   derivar el día por región de la liga.
3. **Ligas NO registradas** (sin URL en `leagues_info`): `crear_fixtures` no las crea (caso
   "INCOMPLETO"). **Fallback:** loguear/marcar la liga faltante para registrarla (no silenciar).
   = "actualizar el registro de ligas con partidos faltantes".
4. **Idempotencia:** confirmada (`crear_fixtures` detecta DUP); validarla en el flujo automático.
5. **Driver:** el "asegurar" navega → corre sobre un driver (el de **corrección**, separado del
   de LIVE) y cuando el LIVE no esté en mitad de un ciclo. (El LIVE conserva su driver dedicado.)

---

## 5. Fase B — Ventanas temporales de navegación por deporte (Idea 2)

**Qué:** navegar un deporte **solo** dentro de su franja de partidos del día. Fuera de esa
franja, **no se navega ese deporte**.

**Granularidad:** **por deporte** (decidido). Cada deporte tiene su(s) ventana(s) propia(s) y se
activa solo en las franjas correspondientes a ese deporte — esa es la idea esencial.

**Cómo se calcula la ventana (por deporte, recalculada a diario desde la DB):**
```
ventana(deporte) = [ min(start_time de hoy) − margen_pre ,
                     max(start_time de hoy) + duración_típica + margen_post ]                     
```
- **Márgenes antes del inicio y después del fin** (decidido). Generosos y **por deporte**, según
  duración variable:
  | Deporte | Duración típica | margen_post sugerido |
  |---|---|---|
  | Béisbol (MLB/NPB/LMB) | ~3–4 h (+ extra innings) | +90 min |
  | Básquet | ~2.5 h (+ prórroga) | +45 min |
  | Fútbol | ~2 h | +45 min |
  | NFL / Am. football | ~3.5 h | +60 min |
  | Tenis | **muy variable** (hasta 5 h) | +120 min |
  - `margen_pre` sugerido: 10–15 min para todos.
- **Recalcular las ventanas a diario** desde los fixtures del día (los horarios cambian; nunca
  hardcodear).
- **Deportes "todo el día"** (tenis/golf/motor): la ventana puede ser casi 24 h → poco ahorro;
  el beneficio es mayor en deportes con franjas claras.

---

## 6. Reglas de SEGURIDAD (NO-NEGOCIABLES)

Garantizan que **optimizar nunca cueste un partido perdido**.

### a) fail-open — "ante la duda, polleá de más, no de menos"
Si el cálculo de ventanas **falla o es dudoso**, NO confiar en las ventanas → **volver al
comportamiento actual: pollear TODOS los deportes cada ciclo.** Disparadores:
- el cálculo de ventanas tira error;
- la DB tiene **0 fixtures** de un deporte hoy (¿no hay, o falló el "asegurar"? → ambiguo → pollear);
- liga/deporte no reconocido; anomalía de zona horaria/reloj.

**Caso "0 matches en DB":** disparar primero el paso de **asegurar** (Fase A); si faltan
registros, la sección **Inconsistencias** los completa; luego se **re-verifica** antes de
confiar en las ventanas.

Razón: el costo de un **falso "saltear"** (perder un partido en vivo → score viejo) es peor que
una navegación de más. Se inclina a **navegar de más, jamás de menos**.

### b) Seguir polleando partidos LIVE fuera de ventana — "el status manda"
La ventana es heurística; un partido puede pasarse (extra innings, prórroga, demoras). La verdad
es el `status` en DB. Regla:

> Un deporte se polea si **(está dentro de su ventana)** **O** **(tiene ≥1 partido en status LIVE
> en DB)** — hasta que ese partido pase a COMPLETED.

Solo se deja de revisar/extraer cuando el partido **termina (COMPLETED)** **y** además pasó el
**margen de fin** (ventana de seguridad).

(Es el mismo principio que "si el partido no finalizó, permanece activo".)

---

## 7. Driver dormido en horas muertas (optimización de RAM)

El LIVE usa su **driver dedicado**. Hoy ese Firefox vive 24/7 (~3.8 GB) aunque no haya partidos.

**Idea:** en **huecos largos sin partidos** (ej. madrugada), el LIVE **cierra su driver dedicado**
(libera ~3.8 GB) y queda en **idle puro** (solo mira el reloj). **Un poco antes** de la próxima
ventana, **relanza el driver dedicado** (`start_driver --label live` + login) y reanuda.

- **Es la respuesta real a "limitar la RAM":** en vez de capar a 2 GB (que mientras hay partidos
  causa "parpadeo" — ver `MCP_RAG_SISTEMA`/medición: piso ~3.8 GB con 5 deportes), se tiene el
  working set alto **solo** durante partidos y se cae a **~0** del LIVE en horas muertas. El
  promedio diario de RAM baja mucho sin degradar el período activo.
- **Costo de despertar:** relanzar Firefox + login = decenas de segundos → solo dormir ante
  huecos largos. **Umbral sugerido:** próximo partido a **> 30–60 min** Y nada en vivo. Entre dos
  partidos cercanos (p.ej. < 30 min) NO se duerme.
- **Seguridad:** antes de dormir, confirmar **0 partidos LIVE** en DB; **despertar con
  anticipación** (pre-margen) para que el login esté listo al primer partido.
- **Reúsa:** `relaunch_live_driver` (el hot-swap que main2 ya usa para reciclar por memoria);
  "dormir" = misma maquinaria, disparada por el **scheduler** (no por memoria), con estado
  "quedarse abajo" en el medio.
- **Alcance:** recomendado como **Fase 2** (después de que las ventanas funcionen). *(A confirmar
  por Jorge.)*

---

## 8. Detalles adicionales a tener en cuenta

- **Cadencia variable por deporte:** básquet cambia rápido (pollear más seguido); béisbol más
  lento. El intervalo no tiene que ser 60 s fijo para todos.
- **Cierre de partido + stats:** al pasar a COMPLETED, dejar de pollearlo, asegurar score final y
  disparar backfill de estadísticas (`update_pending --solo-sin-stats`).
- **Fin del día:** cuando todos los partidos de hoy están COMPLETED y fuera de ventana, el LIVE
  entra en idle hasta el "asegurar" de mañana (encaja con el driver dormido).
- **Observabilidad (panel, pestaña Live):** mostrar las ventanas calculadas y qué deportes están
  activos/dormidos; toggles por deporte; estado del driver (vivo/dormido).
- **Logging sin caps silenciosos:** loguear *por qué* se saltea un deporte ("fuera de ventana
  hasta HH:MM") y cada transición dormir/despertar — auditable.
- **Sinergia con la medición de RAM (Tarea #13):** con menos deportes navegados por ciclo + driver
  dormido, el piso del driver baja; recién ahí un cap de RAM más bajo (~2.5–3 GB) sería viable sin
  parpadeo. (Capar a 2 GB con la config actual NO es viable — medido.)

---

## 9. Requirements para el RAG (al ingestar)

| R | Título | Fase | Prioridad |
|---|---|---|---|
| RL1 | Fase A: asegurar fixtures del día en DB (reusa `crear_fixtures --today/--from-pin`) + fallback de ligas no registradas | 1 | alta |
| RL2 | Fase B: ventanas de navegación **por deporte** (cálculo diario desde DB, márgenes pre/post por deporte) | 1 | alta |
| RL3 | Reglas de seguridad: **fail-open** + **seguir LIVE fuera de ventana** | 1 | alta (no-negociable) |
| RL4 | **Driver dormido** en horas muertas (apagar/relanzar driver dedicado del LIVE por scheduler) | 2 | media |
| RL5 | Cadencia variable por deporte + cierre de partido (stats backfill) | 2 | media |
| RL6 | Observabilidad en panel (ventanas, estado driver, toggles por deporte) | 2 | baja |

---

## 10. Decisiones abiertas / a revisar (Jorge)

1. **Driver dormido:** ¿Fase 1 junto con ventanas, o Fase 2 (recomendado)?
2. **Zona horaria canónica** para "HOY" (¿una global, o por región de liga?).
3. **Cadencia del "asegurar"** durante el día (cada cuánto re-chequear fixtures faltantes).
4. **Umbral de hueco** para dormir el driver (sugerido > 30–60 min sin partido y nada LIVE).
5. Márgenes por deporte (los de §5 son sugeridos; ajustar con datos reales).

## Referencias
- `documentacion/RUNBOOK_PANEL.md` (§ Live, reciclado por memoria) · `partidos_en_vivo.md`.
- `main2.py` (`_maybe_recycle_live`, `relaunch_live_driver`, `DRIVER_MEM_LIMIT_MB`).
- `crear_fixtures_ligas.py` (`--today`, `--from-pin`) · `update_pending_matches.py`.
- `MCP_RAG_SISTEMA.md` · medición Tarea #13 (`logs/_live_driver_mem.csv`).
