# Especificación — Ejecución permanente (engine + panel)

> **Estado:** diseño aprobado (2026-06-26). **Paso 1 en CÓDIGO (2026-07-07),
> sin probar** — ver §8.1: `scripts/engine_runner.py`, gate `ENGINE_OWNS_SCHEDULER`
> en `api/main.py`, y los dos unit files en `deploy/`. Prueba local bloqueada
> (config→remoto). Pasos 2–6 pendientes.
> Origen: `nuevos_requerimientos/nuevos_requerimientos_scraper_b2c.md`.
> Reconcilia y reemplaza como "fuente de verdad de esta fase" las brechas 5.1–5.6
> de ese documento, apoyándose en el backlog ya existente
> [`PENDIENTES_FUNCIONAMIENTO.md`](PENDIENTES_FUNCIONAMIENTO.md) (§1–§5).
>
> **Regla operativa:** todo se prueba **en LOCAL primero**. El despliegue al
> servidor (systemd) es el último paso y se hace con autorización explícita.
> NUNCA tocar la BD remota ni el servidor sin pedido + confirmación en sesión.

---

## 1. Objetivo

Que el scraper se ejecute **de forma permanente en background en un servidor**,
independiente de que el frontend esté abierto:

- **Live** siempre corriendo (driver liviano dedicado).
- **Noticias** ≥ 1 vez/día, frecuencia configurable desde el frontend.
- **Inconsistencias** disparado automáticamente cuando el Live registra ligas
  problemáticas, para completar la data faltante.

El **frontend + API** son solo el **panel**: muestran qué se está ejecutando y
permiten **configurar** (frecuencias, on/off) y lanzar **ejecuciones extra**.
El panel puede caerse o cerrarse y el motor sigue corriendo.

---

## 2. Arquitectura objetivo

```
        ┌──────────────────────────────┐         ┌──────────────────────────────┐
        │  scraper-panel.service       │         │  scraper-engine.service      │
        │  (API FastAPI :8009 + front) │         │  (motor — siempre corriendo) │
        │                              │         │                              │
        │  - LEE estado                │  files  │  - supervisa LIVE (always)   │
        │  - ESCRIBE CONFIG.json       │◄───────►│  - corre el SCHEDULER        │
        │  - dispara "ejecutar ahora"  │ (puente)│  - dueño del Driver 2        │
        │    (escribe señales)         │         │    (on-demand, serializado)  │
        └──────────────────────────────┘         └──────────────────────────────┘
                                                          │
                          ┌───────────────────────────────┼───────────────────────────┐
                          ▼                                ▼                           ▼
                   ┌─────────────┐                 ┌──────────────┐            ┌──────────────┐
                   │ DRIVER 1    │                 │ DRIVER 2     │            │  (cola de    │
                   │ Live        │                 │ completo     │            │   tareas     │
                   │ liviano     │                 │ on-demand    │            │   Driver 2)  │
                   │ PERMANENTE  │                 │ news + incons│            └──────────────┘
                   └─────────────┘                 └──────────────┘
```

**Dos procesos systemd a nivel de sistema** (decisión 2026-06-26: Opción A,
dos servicios), ambos `Restart=always` y habilitados al boot, corriendo como
`User=jorge` (proceso de usuario normal; el scraping NO requiere privilegios).

### 2.1 Drivers (modelo confirmado)

| Driver | Tipo | Ciclo de vida | Quién lo usa |
|---|---|---|---|
| **Driver 1 — Live** | Liviano (`lightweight=True`, sin imágenes) | **Permanente** (siempre vivo, reciclado por hot-swap) | `main2.py` / Live |
| **Driver 2 — Tareas** | **Completo** (carga imágenes) | **On-demand**: se abre cuando hay trabajo, se cierra al quedar ocioso | Noticias **y** Inconsistencias |

Decisiones confirmadas (2026-06-26):

1. **Driver 2 serializado:** Noticias e Inconsistencias **no corren a la vez**
   en el Driver 2. Van en **cola, una tarea a la vez**.
2. **Driver 2 siempre completo** (con imágenes), aunque a veces Inconsistencias
   solo complete scores sin necesitar logos. Se prioriza simplicidad.
3. **El engine es dueño** del Driver 1 y del Driver 2. El panel **no abre
   drivers**; cuando el usuario pide algo desde la UI, el panel **escribe una
   señal** y el engine la ejecuta. Así nunca compiten dos procesos por el mismo
   driver.

En estado estable hay **1 solo driver vivo** (el Live liviano). El Driver 2
aparece y desaparece según haya noticias o inconsistencias que procesar — esto
elimina de raíz el problema del **driver de corrección ocioso** (~3.45 GB,
documentado en `AGENTE_MEMORIA.md` / `ESTRATEGIAS_DRIVERS_RECURSOS.md`).

---

## 3. Mapa de reuso (qué ya existe)

Esta fase es **integración y ajuste**, no desarrollo desde cero. Lo que ya está:

| Pieza | Estado hoy | Archivo |
|---|---|---|
| Driver Live liviano dedicado | ✅ existe | `api/services/driver_manager.py` → instancia `live` (`lightweight=True`, `tmp/live_driver.json`) |
| Driver de corrección (completo) | ✅ existe, **pero siempre-vivo ocioso** | `api/services/driver_manager.py` → instancia `correction` (`tmp/driver_session.json`) |
| Loop de Live | ✅ existe | `src/main2.py`, `src/milestone7.py` (`get_live_match`, solo ligas pinned) |
| Noticias abre/cierra su propio driver | ✅ **ya es on-demand** | `scripts/run_news.py` (`launch_navigator` + `login` + `driver.quit()`) |
| Scheduler embebido (news + fix_team_ids) | ✅ existe, **dentro de la API** | `api/services/scheduler.py` |
| Config del scheduler | ✅ existe | `check_points/CONFIG.json` (`EXTRACT_NEWS`, `FIX_TEAM_IDS`, `LIVE_MISSING_REPAIR`) |
| Archivo de incidencias de Live | ✅ **ya existe con formato definido** | `check_points/live_missing_leagues.json` |
| Disparo auto de Inconsistencias | 🟡 existe **apagado** | `CONFIG.json` → `LIVE_MISSING_REPAIR` (`ENABLED:false`, `EVERY_MINUTES:60`, `APPLY:true`) |
| Completado de partidos / fix | ✅ existe | `scripts/update_pending_matches.py`, `scripts/fix_null_team_ids.py`, `crear_fixtures_ligas.py --from-pin --today` |
| Patrón run_control (pausa/stop limpio) | ✅ parcial | `_check_control()` en varios scripts |

**Brechas del doc original ya resueltas:** 5.2 (contrato del archivo de
incidencias) y 5.4 (scheduler de noticias). El grueso del trabajo nuevo es
**reubicar** (scheduler → engine), **consolidar** (Driver 2) y **supervisar**
(systemd + Live always-on).

---

## 4. Contrato del archivo de incidencias (5.2 — ya implementado, se documenta)

`check_points/live_missing_leagues.json` — JSON **único acumulativo**, escrito por
el Live, leído por Inconsistencias. Formato real (verificado 2026-06-26):

```json
{
  "updated_at": "2026-06-26T08:04:31.957243",
  "leagues": {
    "BASEBALL|JAPAN|NPB": {
      "sport": "BASEBALL",
      "country": "JAPAN",
      "league": "NPB",
      "count": 228,
      "first_seen": "2026-06-13T09:04:18.625458",
      "last_seen": "2026-06-13T11:16:46.440934",
      "status": "resolved",
      "sample_matches": ["Equipo A~Equipo B", "..."]
    }
  }
}
```

- **Clave:** `SPORT|COUNTRY|LEAGUE`.
- **Estados:** `pending` / `resolved` / `ignored` (evita reprocesar lo ya hecho).
- **Concurrencia:** un solo escritor (Live) reescribe el archivo completo con
  `updated_at`; el lector (engine/Inconsistencias) lo lee entre tareas. No hay
  escritura simultánea de dos procesos sobre el mismo registro porque el **engine
  serializa** Driver 2. (Si en el futuro se quisiera blindar: rename atómico.)

No se rediseña este contrato; se **reutiliza tal cual**.

---

## 5. El engine (`scripts/engine_runner.py` — nuevo, fino)

Entrypoint que lanza `scraper-engine.service`. **No reimplementa lógica**: orquesta
piezas existentes en un proceso de larga vida. Responsabilidades:

### 5.1 Supervisión del Live (always-on)
- Asegura que el Driver 1 (liviano) y el loop de `main2.py` estén corriendo.
- Si el loop muere, lo relanza (además del `Restart=always` de systemd a nivel
  de proceso completo). Reúsa el reciclaje hot-swap ya existente del Live.
- Cumple PENDIENTE §2.1 / §4.4 (watchdog del Live).

### 5.2 Scheduler (movido desde la API)
- Reúsa **la lógica** de `api/services/scheduler.py` (loop `_*_due` / `_next_*_run`).
- Lee `check_points/CONFIG.json` en cada vuelta → frecuencias en caliente.
- Tareas programadas:
  - **Noticias** (`EXTRACT_NEWS`): cada N horas, ≥1/día.
  - **Inconsistencias / live_missing** (`LIVE_MISSING_REPAIR`): cada N min,
    procesa las ligas `pending` del archivo de incidencias.
  - **fix_team_ids** (`FIX_TEAM_IDS`): diario a una hora (ya existe).
  - (Futuro / §4 del backlog) barrido `--from-pin --today`, `update_matches`.
- **El scheduler deja de correr en la API** (ver §6) para no duplicarse.

### 5.3 Dueño del Driver 2 (on-demand, serializado)
Ciclo de vida del Driver 2, gestionado **solo** por el engine:

```
loop del engine:
  ¿toca Noticias (por horario)  o  hay ligas 'pending' en live_missing
   o  hay una señal "ejecutar ahora" del panel?
     → si Driver 2 NO está abierto: abrirlo (completo, con login)
     → encolar y ejecutar la(s) tarea(s) UNA a la vez:
          - Noticias  → main_extract_news (reusa run_news/milestone1)
          - Inconsistencias → update_pending_matches / fix_null_team_ids / crear --today
     → al vaciar la cola y no quedar nada pendiente: cerrar Driver 2 (quit)
```

- **Serializado:** un mutex/cola interno; nunca dos tareas a la vez en Driver 2.
- **Cierre por ociosidad:** al terminar la última tarea y no haber pendientes,
  `driver.quit()` libera la RAM. Si llega trabajo nuevo, se reabre.
- Reúsa `DriverManager` (instancia "tareas") o el patrón `launch_navigator` +
  `login` que ya usa `run_news.py`. **Decisión de implementación:** unificar la
  instancia `correction` para que sea on-demand (con idle-close) en lugar de
  crear una tercera; el Driver 2 = la instancia de corrección, pero gestionada
  por el engine con apertura/cierre por demanda.

---

## 6. El panel (API + frontend) — pasa a plano de control delgado

### 6.0 Cómo funciona HOY (verificado, punto de partida)
```
Frontend (React) ──HTTP──► API (:8009) ──► process_manager ──► script (Popen detached, setsid)
                              │                   └─► escribe run_control_<sección>.json
                              │                   └─► WebSocket: logs del script al front en vivo
                              └─► lifespan: sched.start_scheduler()  (scheduler DENTRO de la API)
```
La API **es hoy la ejecutora**: lanza los scripts (`subprocess.Popen(...,
start_new_session=True)`), escribe `run_control_*.json`, corre el scheduler.
El front la controla por HTTP (sin consola). **Fragilidades:** si la API se
reinicia, el scheduler muere y se pierde el rastro de procesos
(`process_manager.py:314`: `get_status` reporta "stopped" aunque el detached
siga vivo); Live depende del panel; dos ejecutores pelearían por el Firefox.

### 6.1 Diseño objetivo — REGLA DE ORO: un solo dueño
```
Frontend ─HTTP─► API (panel) ─escribe─► CONFIG.json / run_control_*.json ─lee─► ENGINE ─► ejecuta
   ▲                 │                                                              │
   └──muestra────────┴──lee── engine_status.json + logs ◄────────escribe───────────┘
```
- **Frontend ↔ API: NO cambia.** Sigue siendo HTTP, mismos endpoints, sin
  consola. Cumple "controlar todo desde el front instalado en el servidor".
- **API = plano de control delgado:** traduce cada acción del front en una
  **escritura de archivo** (config o `run_control`) y **lee estado** para
  mostrarlo. Deja de ejecutar/supervisar cosas de larga vida.
  - Quitar `sched.start_scheduler()` del `lifespan` de `api/main.py` (el engine
    es el único que corre el scheduler — nunca duplicado).
  - El streaming de logs por WebSocket se mantiene, pero **tailing de los
    archivos de log** que escribe el engine (no de un `Popen` propio), así
    sobrevive a reinicios del panel.
  - `get_status` deja de depender del `Popen` local → lee `engine_status.json`
    (arregla el falso "stopped").
- **Engine = único ejecutor/dueño** de Live (Driver 1), scheduler y Driver 2.
  Es el único que hace `Popen`/abre drivers. **Reusa `process_manager` y
  `driver_manager`** (el mismo código que hoy usa la API), pero ahora desde el
  engine.
- Beneficio clave: **reiniciar el panel NO interrumpe el trabajo**; el engine
  sigue. Un solo dueño de drivers ⇒ cero carreras por el Firefox.
- Cumple PENDIENTE §1 (control desde el frontend) y §5.5 del doc original.

### 6.2 Puente panel ↔ engine (por archivos, sin BD nueva)
Dos canales, **distinto ciclo de vida**, los dos escritos por la API (en nombre
del front) y leídos por el engine:

| Canal | Qué lleva | Archivo | Ciclo de vida |
|---|---|---|---|
| **Configuración** | frecuencias, on/off, apply, deportes | `check_points/CONFIG.json` | **Persistente** (sobrevive reinicios; el engine lo relee cada vuelta) |
| **Órdenes / control** | run_now, pause, stop, resume, run_league | `logs/run_control_<módulo>.json` (ya existen, uno por módulo) | **Imperativo, de un solo uso**: el engine lo lee, ejecuta y **resetea a `null` (ack)** |
| **Estado** | heartbeat, tarea/driver activo, last_run/next_run | `tmp/engine_status.json` (nuevo) + logs (ya existen) | El engine escribe, la API lee |

- **No mezclar config con órdenes:** las órdenes se consumen/borran (un
  `run_now` no puede re-dispararse cada vuelta); la config debe persistir. Por
  eso van en archivos separados.
- **`run_control` — verbos:** hoy `command ∈ {pause, stop, resume, null}`. Se
  **añaden** `run_now` y `run_league` (con payload, ej. `{"command":
  "run_league", "league": "BASEBALL|JAPAN|NPB"}`). Para **arrancar** una tarea
  lo lee el **engine**; para **pausar/detener** una corrida ya viva lo sigue
  leyendo el **propio script** con `_check_control()` (mismo archivo, dos
  lectores según el momento).
- **Escrituras atómicas:** todo archivo puente se escribe con **temp + rename**
  (nunca lectura de un JSON a medio escribir). Reusar el patrón ya usado para
  `live_missing_leagues.json`.

---

## 7. Servicios systemd (despliegue — último paso, con autorización)

```ini
# /etc/systemd/system/scraper-engine.service
[Unit]
Description=Scraper engine (Live permanente + scheduler news/inconsistencias)
After=network-online.target
Wants=network-online.target

[Service]
User=jorge
WorkingDirectory=/RUTA/scraper_V2.0
ExecStart=/RUTA/scraper_V2.0/env_sports/bin/python -m scripts.engine_runner
Restart=always
RestartSec=5
# Reglas del driver: el engine NO debe matar firefox/gecko ajenos (ver DRIVER_RULES.md)

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/scraper-panel.service
[Unit]
Description=Scraper panel (API FastAPI + frontend)
After=network-online.target scraper-engine.service

[Service]
User=jorge
WorkingDirectory=/RUTA/scraper_V2.0
ExecStart=/RUTA/scraper_V2.0/env_sports/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8009
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Instalación (sudo **una sola vez**):
```bash
sudo cp scraper-engine.service scraper-panel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now scraper-engine.service scraper-panel.service
```
Operación normal (sin sudo): `systemctl status/restart` como usuario sobre estos
units; logs con `journalctl --user`/`journalctl -u`. El scraping corre como
`jorge`, sin privilegios.

---

## 8. Plan de implementación incremental (orden)

Cada paso se prueba **en local** antes de seguir. No tocar servidor hasta §8.6.

> **Hallazgo (2026-06-26):** `api/services/scheduler.py` **ya orquesta los 3
> módulos** del requerimiento: `_news_tick` (Noticias), `_fix_tick` (fix_team_ids)
> y `_lm_tick` (LIVE_MISSING_REPAIR = auto-reparación de inconsistencias del
> Live). Su `_loop()` (línea 510) ya lee CONFIG.json en caliente y persiste
> estado. Por eso el engine es **casi solo un envoltorio** del scheduler +
> supervisión del Live. `pm.start_process` es **engine-safe**: `_broadcast` se
> omite si no hay event loop (`process_manager.py:374`), así que el scheduler
> corre igual fuera de la API.

1. **Engine mínimo + scheduler movido.** 🟡 **Código escrito (sin probar).**
   - ✅ `scripts/engine_runner.py` — corre `sched.start_scheduler()` + supervisa
     `main2.py` por heartbeat (mtime del log) + escribe `tmp/engine_status.json`.
   - ✅ `api/main.py` — el arranque del scheduler queda detrás de
     `ENGINE_OWNS_SCHEDULER` (default `0` = comportamiento histórico; el panel en
     marcha NO cambia).
   - ✅ `deploy/scraper-engine.service` y `deploy/scraper-panel.service`.
   - ⏳ **Pendiente de PROBAR en local** (bloqueado): el espejo `sports_container`
     no está arriba y `config.py` apunta al **remoto** (`96.30.195.40`). Para
     probar: levantar el espejo local y apuntar `config.py` a la BD local; luego
     correr `ENGINE_OWNS_SCHEDULER=1 env_sports/bin/python -m scripts.engine_runner`
     y verificar que Noticias/fix/live-missing disparan y que el Live se supervisa.
     **NUNCA probar contra el remoto sin permiso explícito.**
2. **Driver 2 on-demand.** Hacer que la instancia de corrección se abra por
   demanda y se cierre por ociosidad, gestionada por el engine. Verificar que no
   queda driver ocioso tras una corrida.
3. **Cola serializada Noticias + Inconsistencias** sobre el Driver 2. Verificar
   que no corren a la vez y que comparten el mismo driver completo.
4. **Activar `LIVE_MISSING_REPAIR`** (hoy `ENABLED:false`): el engine lee
   `live_missing_leagues.json` y completa las `pending`. Probar primero en
   dry-run (`APPLY:false`) en local.
5. **Panel solo-lectura/control:** API deja de correr el scheduler; UI muestra
   `engine_status.json`; "ejecutar ahora" escribe señales que el engine consume.
6. **Despliegue al servidor** (con autorización explícita): instalar los dos
   units systemd, habilitar al boot, verificar `Restart=always` y arranque
   tras reboot.

---

## 9. Robustez / "que no pueda fallar" (garantías de diseño)

Requisito explícito de Jorge (2026-06-26): debe ser **sólido**, desplegado en
servidor, y controlable 100% desde el frontend **sin enviar comandos por
consola**. Garantías concretas:

| # | Garantía | Cómo se logra |
|---|---|---|
| R1 | **Self-healing + arranque al boot** | Ambos units systemd con `Restart=always` + `enable` (arrancan al bootear, reviven si caen). |
| R2 | **Reiniciar el panel NO interrumpe el trabajo** | El engine es el dueño de Live/scheduler/Driver 2; la API es desechable. Caer/reiniciar el panel no toca la ejecución. |
| R3 | **Un solo dueño de los drivers ⇒ cero carreras** | Solo el engine hace `Popen`/abre drivers. El panel jamás lanza un proceso ni abre Firefox. Respeta `DRIVER_RULES.md`. |
| R4 | **Sin estados parciales en BD ante crash** | Cada partido se escribe en **una transacción atómica** (`_apply_match_atomic`, ya implementado); crash/SIGKILL ⇒ ROLLBACK ⇒ se reprocesa. |
| R5 | **Puente sin corrupción** | Archivos puente escritos con **temp + rename** atómico; lecturas nunca ven JSON a medias. |
| R6 | **Órdenes idempotentes** | `run_now`/`run_league` se **ackean** (reset a `null`) tras consumirse ⇒ nunca doble ejecución. |
| R7 | **Estado real (no mentiras)** | El panel lee `engine_status.json` (heartbeat con timestamp), no un `Popen` local ⇒ se acaba el falso "stopped" tras reinicio (`process_manager.py:314`). |
| R8 | **Recuperación determinista** | Al (re)arrancar, el engine **relee `CONFIG.json`** y reconstruye su agenda (last_run/next_run persistidos, patrón `scheduler_*_state.json`); el Live se reengancha o reabre el Driver 1. |
| R9 | **Driver 2 no deja RAM colgada** | Cierre por ociosidad (`quit()` ordenado); si el engine cae con Driver 2 abierto, systemd lo reinicia y el `start_driver` hace cleanup del huérfano antes de reabrir. |
| R10 | **Control total desde el front, sin consola** | Front ↔ API por HTTP (mismos endpoints de hoy); todo botón se traduce a escritura de archivo que el engine ejecuta. La consola solo se usa una vez para instalar los units. |

### 9.1 Observabilidad
- **Logs:** por módulo en `logs/` (ya existe) + `journalctl -u scraper-engine`
  / `-u scraper-panel`.
- **Estado visible en el front:** `engine_status.json` (heartbeat, tarea/driver
  activo, last_run/next_run por tarea) servido por la API.
- **Heartbeat:** el engine estampa su latido cada N s; si el panel ve un latido
  viejo, muestra "engine sin responder" (no asume que todo está bien).
- Alertas/Grafana: **fuera de alcance de esta fase** (mejora futura, 5.6).

---

## 10. Reglas que esta fase NO rompe

- **Driver:** el engine respeta `docs/DRIVER_RULES.md` — el cierre del Driver 2
  es `quit()` ordenado sobre **su propio** driver (nunca `pkill` firefox/gecko;
  nunca toca el Live ni el navegador del usuario).
- **BD:** solo INSERT/UPDATE; jamás DELETE/DROP/TRUNCATE (CLAUDE.md).
- **Remoto:** nada se ejecuta contra el servidor/BD remota sin pedido +
  confirmación explícita en sesión.

---

## 11. Referencias

- Requerimientos origen: `nuevos_requerimientos/nuevos_requerimientos_scraper_b2c.md`
- Backlog que reconcilia: `PENDIENTES_FUNCIONAMIENTO.md` (§1–§5)
- Scheduler: `api/services/scheduler.py`, `check_points/CONFIG.json`
- Drivers: `api/services/driver_manager.py`, `docs/DRIVER_RULES.md`
- Live: `src/main2.py`, `src/milestone7.py`, `check_points/live_missing_leagues.json`
- Noticias: `scripts/run_news.py`, `src/milestone1.py`, `noticias.md`
- Inconsistencias: `scripts/update_pending_matches.py`, `scripts/fix_null_team_ids.py`,
  `crear_fixtures_ligas.py`
- Operación del panel: `RUNBOOK_PANEL.md`
