# Agente de detección y reducción de memoria — spec para próxima sesión

> Creado 2026-06-13. Documento de trabajo: lo revisamos juntos antes de implementar.
> Objetivo: un agente/rutina que **mida** el consumo real de RAM del scraper, **detecte**
> los consumidores anómalos y **reduzca** el uso sin romper las reglas del proyecto
> (jamás `pkill` firefox/geckodriver ni `driver.quit()` sin confirmación; ver CLAUDE.md).

## 1. Diagnóstico medido (2026-06-13, panel + live + completado corriendo)

Sistema: 30 GiB total · **14 GiB usados** · 16 GiB disponibles · 7.3 GiB buff/cache.

Desglose real por **PSS** (memoria compartida-aware; RSS engaña con Firefox), de-duplicado
(la API "pesa" 2 GB sólo porque es el **padre** del firefox de live — la API sola ≈ 80 MB):

| Consumidor | PSS | Procesos en árbol | Estado |
|---|---:|---:|---|
| Driver de **corrección** (firefox 635443) | **3.45 GB** | 21 | **idle 10h — anómalo** |
| Driver de **live** (firefox 2642574) | 1.9 GB | 8 | en uso (cuelga de la API) |
| Firefox de **escritorio del usuario** (2319954) | 1.4 GB | 13 | **NO es del scraper** (ppid sesión) |
| 8× uvicorn `api.main` acumuladas | ~0.4 GB | — | **zombies** de reinicios previos |
| API real + main2 + vite | ~0.35 GB | — | sanos |
| **Total scraper (sin el FF del usuario)** | **~6.1 GB** | | |

`contentproc` (procesos de contenido de Firefox) en el sistema: **39** — se acumulan con el tiempo.

## 2. Causas raíz identificadas

1. **Driver de corrección ocioso e inflado (3.45 GB).** Es el mayor consumidor. No tiene
   reciclado por memoria como sí tiene el live. Queda vivo horas aunque no se use.
2. **Acumulación de procesos `uvicorn api.main` (8 vivos).** Cada reinicio mal cerrado deja
   una instancia zombie (~50 MB) + a veces hijos. El `pkill -f "uvicorn api.main"` del runbook
   **no se puede usar** porque mataría la que parienta el live → se reinician "a mano" y se
   acumulan. ~0.4 GB desperdiciados + riesgo de confusión de cuál sirve `:8009`.
3. **Firefox acumula `contentproc`.** Sin prefs de bajo consumo en el driver de corrección
   (el live ya tiene `lightweight=True`), el árbol crece (21 procesos).

## 3. Qué debe HACER el agente (sin romper reglas)

**Detección (read-only, seguro):**
- Medir PSS por árbol (reusar `driver_session.driver_tree_pss_mb` y el snippet de smaps_rollup
  de este doc). Distinguir: driver corrección, driver live, **firefox del usuario** (excluirlo),
  API que sirve vs zombies, main2, vite.
- Emitir un reporte (tabla PSS + nº de `contentproc` + antigüedad de cada árbol).
- Marcar anómalos: driver idle > umbral de tiempo, árbol > umbral de PSS, nº de uvicorns > 1.

**Reducción (acciones controladas, cada una con confirmación o regla explícita):**
- **Driver de corrección:** reciclado por memoria/inactividad igual que el live (hot-swap:
  abrir el nuevo, validar, recién ahí cerrar el viejo vía `driver.quit()` del launcher —
  NUNCA `pkill`). O bien **detenerlo si lleva > N min idle** (liberar 3.45 GB) y relanzarlo
  on-demand cuando Inconsistencias lo necesite.
- **Aplicar prefs lightweight al driver de corrección** (las mismas del live:
  `permissions.default.image=2`, `dom.ipc.processCount=1`, `fission.autostart=false`, etc.).
- **Reaper de uvicorns zombies:** detectar las que NO sirven `:8009` y NO parientan main2/live,
  y SIGTERM sólo a ésas (nunca a la que tiene hijos vivos del scraper). Idealmente arreglar el
  ciclo de reinicio para que no se acumulen (script `restart_api.sh` que mate sólo la que sirve).
- **Watchdog opcional:** correr el reporte cada X min desde el scheduler y avisar en el panel
  cuando un árbol supere el umbral.

**Prohibido (reglas del proyecto):** `pkill`/`kill -9` a firefox/geckodriver; `driver.quit()`
sin confirmación; matar el firefox de escritorio del usuario; DELETE en la BD.

## 4. Snippet de medición PSS (base para el agente)

```python
import os, glob
def pss_kb(pid):
    try:
        for l in open(f'/proc/{pid}/smaps_rollup'):
            if l.startswith('Pss:'): return int(l.split()[1])
    except Exception: return 0
    return 0
# + construir árbol por PPid (ver /proc/<pid>/status) y sumar pss_kb de descendientes
```

## 5. Entregable propuesto

- `scripts/mem_report.py` — reporte PSS read-only (detección).
- Integrar reciclado/idle-stop del driver de corrección en `driver_manager` (reusar el del live).
- `scripts/restart_api.sh` — reinicio quirúrgico (mata sólo la que sirve `:8009`) + reaper de zombies.
- (Opcional) endpoint `/api/mem/report` + tarjeta en el panel.

## 6. Pendiente para la próxima sesión
- Revisar este plan juntos y decidir alcance.
- Definir umbrales (PSS por driver, minutos de idle para auto-stop de corrección).
- Confirmar política del driver de corrección: ¿auto-stop por idle, o reciclado por memoria?
