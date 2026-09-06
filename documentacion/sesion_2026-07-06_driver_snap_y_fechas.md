# Sesión 2026-07-06 — Fallo de lanzamiento del driver (snap gpu-2404), fix de fechas score=-1, y parada del scraper

> Resumen operativo de la sesión (2026-06-29 → 2026-07-06). Trabajo de operación +
> diagnóstico, no de cambios de arquitectura. Autoridad: `INDICE.md` → `RUNBOOK_PANEL.md`.

---

## 1. Driver no se lanza desde el frontend — CAUSA RAÍZ: snap Firefox `gpu-2404`

**Síntoma:** en la pestaña **Live**, "Iniciar driver" se queda en *"iniciando…"* y **no abre navegador**.
El launcher arranca pero `start_driver.py` muere en `webdriver.Firefox(...)`, nunca escribe la
sesión → el frontend espera para siempre.

**Error real (en `tmp/logs/live_driver_launch.log` y `driver_launch.log`):**
```
selenium ... WebDriverException: Message: Service /snap/bin/geckodriver unexpectedly exited. Status code was: 3
```
Log de geckodriver (`log_output`):
```
Content snap GPU wrapper '/snap/firefox/8568/gpu-2404/bin/gpu-2404-provider-wrapper' not found: ensure slot is connected
```

**Diagnóstico confirmado:**
- El snap **Firefox se auto-actualizó** a `152.0.3-1` (rev **8568**), que depende del content-snap
  `gpu-2404` (provider `mesa-2404`).
- La conexión figura mapeada (`snap connections firefox` → `firefox:gpu-2404 ↔ mesa-2404:gpu-2404`),
  **pero el bind-mount no está aplicado** para la rev nueva: `/snap/firefox/8568/gpu-2404/bin/`
  **no existe** (el proveedor `mesa-2404` sí tiene el wrapper). Conexión stale tras el refresh.
- Es **intermitente**: a veces geckodriver sobrevive al warning y arranca; a veces sale con status 3.
  El Firefox de escritorio sigue vivo solo porque arrancó ~10 días antes con la rev anterior.
- Descartado: NO es diferencia de entorno. La API (uvicorn) y el shell gráfico tienen `DISPLAY=:0`,
  `XAUTHORITY`, `WAYLAND_DISPLAY`, `DBUS`, `XDG_RUNTIME_DIR` **idénticos**. Reproducido el lanzamiento
  exacto (`start_driver.py --no-headless --lightweight`) desde el shell: 2/2 éxito cuando el snap
  colabora → el fallo es del snap, no del código.

**FIX (requiere sudo — lo corre el usuario):**
```bash
sudo snap disconnect firefox:gpu-2404 && sudo snap connect firefox:gpu-2404 mesa-2404:gpu-2404
```
Fuerza a snapd a re-montar `gpu-2404` en la rev 8568. Alternativa: un **reboot** reaplica los montajes.

---

## 2. Bug secundario: `driver_manager.status()` reporta "alive" falso

`api/services/driver_manager.py::status()` calcula `alive = (_pid_alive(launcher) AND existe session_file)`.
**No verifica que Firefox/geckodriver respondan.** Por eso el driver de corrección reportaba
`alive:true, session_ready:true` con su **Firefox `<defunct>`** (zombie). El status miente cuando el
navegador muere pero `start_driver.py` sigue en `signal.pause()`.

**Recomendación (pendiente):** que `status()` haga un ping real al driver (p.ej. leer `current_url`
vía el `executor_url` de la sesión) antes de declarar `alive`, o comprobar que el PID de Firefox vive.

---

## 3. Gap de supervisión de LIVE (sin engine)

En el modo actual (panel con scheduler embebido, **sin** `scraper-engine`), **nada relanza `main2.py`
si crashea**. La auto-relanzamiento de LIVE vive SOLO en `scripts/engine_runner.py` (loop cada 15s:
`_supervise_live()` + `tmp/engine_status.json`), que no está corriendo.
- LIVE sobrevive al cierre del frontend/panel (corre con `setsid`, sesión propia) — **probado**.
- Pero NO sobrevive a un crash de `main2.py` ni a un reboot.
- En esta sesión LIVE murió el **2026-07-03 19:25** y nadie lo relanzó → `score=-1` subió a 81.

**Camino a robustez total:** implementar/instalar `scraper-engine` (systemd `Restart=always`).
Ver `especificacion_ejecucion_permanente.md`.

---

## 4. Inconsistencias `score=-1` — investigación y corrección

Regla de detección (`api/services/database.py`): `se.points = -1 AND m.match_date < CURRENT_DATE`.
Es decir, "partido cuya fecha ya pasó y sigue sin resultado". Dos causas distintas encontradas:

### 4.1 Bolivia / Division Profesional (8) — problema de FECHA → CORREGIDO
- La liga tuvo un **parón de ~5 semanas** (results de FlashScore terminan el 2-jun; reanudan el 8-jul).
- Los 8 partidos fueron **pospuestos a fin de julio/agosto**. FlashScore ya movió la fecha; la BD se
  quedó con la de junio → como junio ya pasó, se marcaban como "pasado sin resultado" (**inconsistencia
  falsa por fecha vieja**, no faltaba resultado).
- Verificado con el driver (pareo estricto por equipos contra **fixtures**). **Aplicado**
  `UPDATE match.match_date` (solo fecha) de los 8 a su fecha real:

| Partido | Antes | Ahora |
|---|---|---|
| Universitario de Vinto ~ Guabira | 20-jun | 31-jul |
| SA Bulo Bulo ~ Blooming | 20-jun | 01-ago |
| Real Oruro ~ Independiente | 21-jun | 01-ago |
| Tomayapo ~ Academia del Balompie | 20-jun | 01-ago |
| Real Potosi ~ GV San Jose | 19-jun | 02-ago |
| The Strongest ~ Aurora | 21-jun | 02-ago |
| Always Ready ~ Bolivar | 21-jun | 02-ago |
| Oriente Petrolero ~ Nacional Potosi | 22-jun | 03-ago |

Al quedar `match_date > hoy`, salen del flag; cuando se jueguen, LIVE los completa. (Nota: los 8
partidos "futuros" de la BD, 11-14 jul, son del mismo calendario pospuesto y también están corridos
respecto a FlashScore — pendiente opcional de alinear.)

### 4.2 CFL / Canadá (1) — problema de RESULTADO → pendiente (fácil)
- Único flagged: **Montreal Alouettes ~ Ottawa Redblacks (29-jun)**. Los otros 67 CFL con -1 son
  temporada futura (jul-oct) → normal.
- **Sí se jugó**; FlashScore tiene el resultado **37-35** en results. Es un residuo normal del live.
  Se resuelve con la corrección de results estándar (`update_pending_matches`), no requiere cambio de fecha.

### 4.3 Antes de las correcciones (2026-06-29): backlog masivo saneado
- `update_pending_matches --mode completo --apply` sobre 11 ligas: **137 → 8** score=-1
  (298 procesados OK, 0 errores). Luego 17 nuevos del 28-jun corregidos (**25 → 8**).
- Auditoría read-only de las escrituras (agente de integridad): corrección íntegra (0 COMPLETED con -1,
  0 huérfanos, 0 duplicados nuevos). Anomalías **pre-existentes** detectadas (fuera de alcance): 77
  partidos con score real pero `status=SCHEDULED`, 12 `match_detail` sin `score_entity`, 1 FK team_id NULL.

---

## 5. Cambio de DOM en FlashScore (impacta scrapers)

FlashScore **renombró el elemento de fecha/hora**: de `event__time` → **`event__stageTime`**
(clase completa `... wcl-stageTime_... event__stageTime event__stageTime--date`). Los parsers que lean
la fecha de las filas (`event__match`) deben contemplar el nuevo selector. Detalle en los scripts
`_debug_bolivia_*` (excluidos del RAG).

---

## 6. Parada del scraper y recursos

- Los grandes consumidores de RAM (1.6 GB, 1.2 GB…) eran **pestañas del Firefox de ESCRITORIO**
  (pid 16820, hijo de gnome-shell) — no el scraper. El scraper ocupaba ~150 MB (API 63 MB + Vite 91 MB).
- **Scraper detenido por completo** (por PID exacto, nunca `pkill firefox/geckodriver`): API :8009,
  Vite :5174, drivers/geckodriver/Firefox marionette = 0, zombies (launchers muertos) reapeados,
  perfiles `/tmp/rust_mozprofile*` = 0, puertos cerrados. Firefox de escritorio + gnome-shell intactos.

---

## 7. Pendientes vivos al cierre de la sesión
1. **Snap fix** (§1) — reconectar `gpu-2404` (sudo) para que el driver deje de fallar intermitente.
2. **CFL** (§4.2) — completar el 1 partido jugado (Montreal~Ottawa 37-35).
3. **Endurecer `status()`** (§2) — ping real al driver.
4. **Robustez de LIVE** (§3) — engine systemd para relanzar main2 tras crash/reboot.
5. **score=-1 = 81** al cierre (LIVE llevaba días caído) — bajará al relanzar LIVE + corrección.
6. Opcional: alinear fechas de los 8 partidos "futuros" de Bolivia (§4.1).
