# Sesión — Organización del proyecto + script de integridad de DB

Fecha: 2026-06-01. Objetivo: avanzar la hoja de ruta de
[organizacion_proyecto.md](organizacion_proyecto.md): archivar la UI vieja,
ampliar el plan con el panel de control y la visión funcional, y **desarrollar
el script de verificación de integridad de la DB** (sección 4).

---

## 1. Dashboard Flet legacy → archivado
- `dashboard/` (Flet, `app.py` 1698 LOC, referenciaba `/root/scraper_v3`) movido a
  **`old_versions/dashboard/`**. NO borrado: queda para eliminar cuando el usuario
  lo decida. La UI vigente es `api/` (FastAPI) + `frontend/` (React+Vite).

## 2. Plan de organización ampliado
- **Sección 7 — Integración del panel de control (FastAPI+React)**: pendientes
  detectados al auditar el panel: `paralel_teams.py` no usa `run_control`/`run_status`
  (pause/stop de Equipos no es limpio); `run_news.py`/`run_leagues.py` igual;
  `frontend/dist` desactualizado (recompilar); puertos en docs desfasados (real
  API **8009** / Vite **5174**, no 8000/5173); falta README de arranque;
  `api/`+`frontend/` sin commitear; dos caminos de live (`main2.py` vs
  `live_runner.py`+`src/live_function.py`); confirmar que `config.py` apunte a local.
- **Sección 8 — Ideas fundamentales / visión funcional** (detalles a definir):
  1) control total del scraper desde el frontend (noticias, selección de ligas,
     extracción granular); 2) validación exhaustiva de toda la BD + alertas
     accionables; 3) alertas de fallos vía Telegram (reusar `src/telegram_notify.py`,
     hoy solo en `live_runner.py`); 4) integración total de herramientas/scripts.

## 3. Script de integridad de DB — IMPLEMENTADO (sección 4)
- **`scripts/verificar_integridad_db.py`** — auditoría **read-only** de `sports_db`.
  - Conexión forzada a solo-lectura: `get_conn()` + `set_session(readonly=True)`
    → Postgres rechaza cualquier escritura. Solo SELECT; reporta IDs, no toca nada.
  - **Reusa** `_INCONS_QUERIES`, `_STATUS_LEGACY_VALUES`, `get_conn` de
    `api/services/database.py` (mismo origen de verdad que la pestaña Inconsistencias).
  - **19 chequeos en 4 familias**:
    - REFERENCIAL: `match_no_league/season/country`, `league_no_sport/country`,
      `team_no_country`, `fk_roto_team`.
    - ESTRUCTURA: `detail_no_2`, `detail_home_visitor`, `match_no_detail`,
      `detail_no_score`, `league_no_season`.
    - CALIDAD: `score_minus_one`, `status_legacy`.
    - DUPLICADOS: `dup_sport/league/country/team/season/match`.
  - Flags: `--only KEY`, `--limit N`, `--by-league`, `--json` (→ `logs/integridad_*.json`),
    `--list`, `--no-color`. Exit code **2=high / 1=medium / 0=ok** (gancho para
    Telegram §8.3 y cron).
  - Docstring extenso + diagrama ASCII al inicio; comentarios por función.
  - **Verificado**: compila OK; `--list` y `--help` corren (no conectan).

## 4. PENDIENTE para la próxima sesión
- **PROBAR `verificar_integridad_db.py` contra la BD** — BLOQUEADO: `config.py`
  apunta a IP **remota** (`96.30.195.40`), no local. Antes de ejecutar, decidir:
  (a) apuntar `config.py` a la DB local (`desarrollo_local.md`) y probar ahí, o
  (b) autorización explícita para correr la auditoría read-only contra remoto.
  Recordar regla: jamás conectar a remoto sin pedido explícito + confirmación.
- Tras probar: marcar [x] el "PROBAR" de §4 y, si aparecen inconsistencias,
  documentarlas / corregirlas con los `fix_*` (DELETE solo con aprobación puntual).
- Seguir con el resto del plan (orden sugerido por el usuario: empezó por §4).
