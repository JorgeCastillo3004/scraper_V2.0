# Especificación — Resumen por sesión + visor de db_history en el panel

> Estado: **APROBADO 2026-06-04 — pendiente de implementar.** Dos mejoras de panel
> independientes del multi-driver. Ver [INDICE.md](INDICE.md),
> [api.md](api.md), [frontend.md](frontend.md),
> [especificacion_parallel_panel.md](especificacion_parallel_panel.md).

---

## Mejora 1 — Separar "Resumen de sesión" (por liga) de "Totalización" (global)

**Motivo:** confusión real detectada — el log mostraba `[COBERTURA] faltan 2` (por liga,
Perú) justo antes de `No encontrados: 3` (total de todas las ligas), pareciendo
contradictorio. La cuenta era correcta (Bolivia 1 + Perú 2 = 3), pero no se distinguía el
scope. Ver corrida `logs/update_matches_20260604_070613.log`.

**Cambio en `scripts/update_pending_matches.py` (bloque RESUMEN, ~líneas 324-330):**
- Acumular un **desglose por liga** durante el loop (`by_league`): para cada liga, su
  población, encontrados, faltan, ok, errores.
- Imprimir dos secciones rotuladas:
  1. **`RESUMEN DE SESIÓN` (por liga):** una fila por liga → `liga | población | OK | faltan`.
     (Los `faltan N` quedan atribuidos explícitamente a su liga.)
  2. **`TOTALIZACIÓN` (global):** los totales actuales (Procesados OK, No encontrados,
     Omitidos, Errores, Reciclajes) — invariante: `OK + No encontrados + Omitidos + Errores
     = población total`.
- Alcance: **solo el texto del resumen** (lo que se ve en el terminal del panel). No son
  tarjetas nuevas en la UI.

---

## Mejora 2 — Visor de `db_history` al fondo del panel, con navegación ◀ ▶

**Qué es `db_history`:** `scripts/db_history.py` toma un snapshot del estado de la DB y
lo agrega a `logs/db_history.json` (lista, hoy ~97 entradas). Cada snapshot: timestamp +
totales (matches, teams, news, players, leagues, seasons, sports, `matches_with_stats`,
`score_minus_one`, `status_counts`) + conteo por liga/deporte. `show_comparison(prev, curr)`
imprime la **comparación contra el snapshot anterior** (totales con Δ, estado de partidos
con Δ, y "Cambios por liga").

**Decisiones del usuario (2026-06-04):**
1. **Mostrar el snapshot TAL CUAL la salida del script** → reproducir el formato de
   `show_comparison` (cabecera `SNAPSHOT: <ts>`, totales con Δ, estado de partidos, cambios
   por liga vs el anterior).
2. **Navegar entre snapshots** con botones **◀ / ▶** (recorrer las ~97+ entradas; cada vista
   = comparación de snapshot[i] vs snapshot[i-1]). Arrancar en el más reciente.
3. **Ubicación: al fondo del panel.** Se **ejecuta automáticamente al terminar la
   extracción** (cuando finaliza una corrida `update_matches`/extracción → toma un snapshot
   nuevo, que pasa a ser la vista más reciente).
4. **Consulta al remoto AUTORIZADA:** `db_history.py` solo hace `SELECT` (seguro). Puede
   consultar `96.30.195.40/sports_db` para tomar el snapshot. (Nota: credenciales hoy
   hardcodeadas en `db_history.py` líneas ~25.)

**Implementación:**
- **Backend (`api/`):**
  - `GET /api/db_history` → lista de snapshots (timestamps + índice) para el navegador.
  - `GET /api/db_history/{idx}` → la **comparación idx vs idx-1** renderizada como texto
    (reusar la lógica de `show_comparison`, refactorizada para devolver string en vez de
    `print`), o devolver ambos snapshots y formatear en el front. Preferible: backend
    devuelve el **texto ya formateado** (fiel a la salida del script).
  - Disparo automático al terminar extracción: hook en `process_manager` (al detectar fin de
    `update_matches`) que corre `db_history.py` (toma snapshot del remoto, lo agrega al JSON).
    Opcional: `POST /api/db_history/snapshot` para tomar uno manual.
- **Frontend:**
  - Recuadro al fondo (estilo el visor de logs: monoespaciado, scroll), mostrando el texto de
    la comparación del snapshot seleccionado.
  - Botones **◀ ▶** + indicador `snapshot i/N — <timestamp>`. Empezar en el último.
  - Auto-refrescar a la entrada más nueva cuando termina una extracción.
- **Robustez:** los snapshots viejos tienen menos campos (la estructura creció). Usar `.get(...
  , 0)` como ya hace `show_comparison` para tolerar ausencias. El primer snapshot (sin
  anterior) → mostrar sin Δ.

---

## Pendiente de decisión al implementar
- Si el texto de la comparación se genera en backend (recomendado, fiel al script) o en front.
- Si además del auto-snapshot al terminar extracción se agrega botón manual "Tomar snapshot".
