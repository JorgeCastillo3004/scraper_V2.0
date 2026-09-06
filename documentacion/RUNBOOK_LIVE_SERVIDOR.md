# RUNBOOK — Live en el servidor (`live_v2` + systemd)

> **EMPEZAR AQUÍ para operar el live que corre permanentemente en el servidor.**
> Para el panel local (API 8009 + Vite 5174) ver [`RUNBOOK_PANEL.md`](RUNBOOK_PANEL.md).
> Para acceso/credenciales de los servidores ver [`servidores_y_acceso.md`](servidores_y_acceso.md).
>
> Estado: **operativo desde 2026-08-30** (systemd). Antes corría en tmux, ver §6.

---

## 1. Qué corre y dónde

| | |
|---|---|
| Servidor | `104.156.244.145` — `ssh scraper_server` (hostname remoto `DevOps`) |
| Directorio | `/home/scraper/live_v2/` |
| Proceso | `run_live.sh` → `main2.py --sports <9 deportes> --interval 60` → geckodriver → Firefox headless |
| Escribe en | BD remota `96.30.195.40 / sports_db` (la misma que usa el panel local) |
| Arranque | `systemd --user` + linger (arranca solo tras reboot) |

`live_v2` es un **deploy aislado y mínimo**, creado a propósito para no tocar el código
viejo (marzo/abril) de `/home/scraper/scraper_v3`. Solo contiene lo que el live necesita:

```
live_v2/
├── main2.py             # loop del live
├── config.py            # credenciales (LIVE_HEADLESS lo fuerza run_live.sh)
├── run_live.sh          # lanzador con auto-restart (while true)
├── rotate_logs.sh       # rotación de logs (§4)
├── src/                 # milestones
├── scripts/driver_session.py
├── check_points/
├── venv/                # venv propio (+ geckodriver linux64 en venv/bin)
└── logs/
```

**⚠️ El servidor NO tiene los scripts de Inconsistencias** (`update_pending_matches.py`,
`fix_inconsistent_matches.py`, `crear_fixtures_ligas.py`, …). Eso solo existe en local.
Para correr Inconsistencias contra la BD hay dos caminos: hacerlo **desde local** (que ya
tiene todo), o **desplegar** primero esos scripts al servidor. Ver §7.

---

## 2. Operación diaria

Todos los comandos llevan **`--user`** (son unidades de usuario, no de sistema). Por SSH
no interactivo hace falta exportar `XDG_RUNTIME_DIR` primero:

```bash
ssh scraper_server
export XDG_RUNTIME_DIR=/run/user/$(id -u)

systemctl --user status  scraper-live        # ¿está vivo?
systemctl --user restart scraper-live        # reiniciar
systemctl --user stop    scraper-live        # parar (¡deja de actualizar la BD!)
systemctl --user start   scraper-live
```

Unidades instaladas:

| Unidad | Qué hace |
|---|---|
| `scraper-live.service` | El live. `Restart=always`, `RestartSec=15` |
| `scraper-logrotate.timer` | Dispara la rotación de logs cada 6 h |
| `scraper-logrotate.service` | `oneshot` que ejecuta `rotate_logs.sh` |

Archivos: `~/.config/systemd/user/scraper-{live.service,logrotate.service,logrotate.timer}`.

### Por qué unidades de usuario y no de sistema

El usuario `scraper` **no tiene sudo sin contraseña**, así que no se puede escribir en
`/etc/systemd/system`. La vía de usuario logra lo mismo, pero **exige linger**:

```bash
loginctl enable-linger scraper     # ya aplicado; sin esto NO arranca al boot
loginctl show-user scraper -p Linger   # debe decir Linger=yes
```

Sin linger, los servicios de usuario solo viven mientras haya una sesión abierta: el
servidor reiniciaría y el live no volvería. **Si alguna vez se reinstala el server,
esto es lo primero que hay que rehacer.**

---

## 3. Verificar que está sano

```bash
ssh scraper_server '
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user is-active scraper-live
  tail -30 /home/scraper/live_v2/logs/live_persist.log
'
```

Qué buscar en el log:

| Línea | Significa |
|---|---|
| `[CICLO N] inicio/fin … leído en Xs` | El loop gira. Un ciclo normal tarda 40–100 s |
| `[OK] <partido> \| score A-B \| status=… \| N copia/s actualizada/s` | **Escribió en la BD** ✅ |
| `[DB-SKIP] Partido NO EXISTENTE en la BD` | Lo vio en FlashScore pero no está en `match`. El live **solo actualiza, no crea** |
| `[VENTANA] <deporte> fuera de ventana hasta ~HH:MM UTC — se saltea` | Normal: optimización horaria por deporte |
| `No route to host` / `OperationalError` | ❌ Perdió la BD. El live hace *fail-open* (poll de todo) pero no escribe |

Un arranque limpio no debe tener ningún `Traceback` ni `OperationalError`.

> `[DB-SKIP]` masivo en tenis es **conocido y esperado**: la creación de partidos de tenis
> aún no está cableada al flujo. Ver [`tenis_creacion_y_fixes.md`](tenis_creacion_y_fixes.md).

Contra la BD (read-only, desde local):

```bash
cd /home/jorge/work/scraper_V2.0
./env_sports/bin/python -c "
import psycopg2, config
c=psycopg2.connect(host=config.DB_HOST,dbname=config.DB_NAME,user=config.DB_USER,
                   password=config.DB_PASS,connect_timeout=12)
cur=c.cursor(); cur.execute(\"select status,count(*) from match group by status order by 2 desc\")
print(cur.fetchall()); c.close()"
```

---

## 4. Logs y rotación

| Archivo | Qué es | Crecimiento |
|---|---|---|
| `logs/live_persist.log` | Log del live (el útil para diagnosticar) | ~0,13 MB/día |
| `geckodriver.log` | Ruido de Firefox: errores JS de anuncios, WebGL. **Sin valor diagnóstico** | **46 MB/día ≈ 1,4 GB/mes** |
| `logs/rotate.log` | Registro de cada rotación | mínimo |

`geckodriver` **no rota nada por su cuenta y hace append entre reinicios**: al relanzar el
live no empieza de cero, sigue engordando el mismo archivo. Sin rotación crece sin límite
(llegó a 275 MB antes de instalarse esto).

`rotate_logs.sh`, disparado por el timer cada 6 h:

| Archivo | Se rota si supera | Conserva |
|---|---|---|
| `geckodriver.log` | 50 MB | últimos 2 MB |
| `logs/live_persist.log` | 50 MB | últimos 10 MB |

Con 46 MB/día y chequeo cada 6 h, el techo real de `geckodriver.log` es **~60 MB**.

### ⚠️ Regla: truncar, NUNCA borrar ni mover

geckodriver y systemd mantienen el archivo abierto en modo **append**. Si se borra o se
renombra, los procesos siguen escribiendo en el **inode huérfano**: el espacio en disco
**no se libera** hasta reiniciar el servicio, y el archivo nuevo queda mudo. Por eso el
script hace `tail -c NM > tmp; cat tmp > archivo` (trunca a 0 y reescribe la cola),
que respeta el descriptor abierto. Verificado: rotó 275 MB → 2 MB con el live corriendo,
sin cortarlo y sin dejar huecos dispersos.

Forzar una rotación a mano:

```bash
systemctl --user start scraper-logrotate.service
cat /home/scraper/live_v2/logs/rotate.log
```

---

## 5. Diagnóstico rápido

| Síntoma | Causa probable | Acción |
|---|---|---|
| `is-active` dice `inactive`/`failed` | Crash repetido | `systemctl --user status scraper-live` + `tail logs/live_persist.log` |
| Log congelado hace horas, servicio `active` | Firefox colgado sin morir | `systemctl --user restart scraper-live` |
| `No route to host` en bucle | BD remota caída o firewall | Probar `bash -c "cat </dev/null >/dev/tcp/96.30.195.40/5432"`. Es infra de José |
| Partidos viejos colgados en `status=LIVE` | El live murió sin poder cerrarlos | Corregir con el flujo de Inconsistencias (§7) |
| Disco creciendo | Rotación no corre | `systemctl --user list-timers scraper-logrotate.timer` |
| Todo parado tras un reboot | **Linger desactivado** | `loginctl show-user scraper -p Linger` → si `no`, `enable-linger` |

RAM: el server tiene 11 GB. El live con su Firefox ocupa ~1,4 GB estable. El reciclado por
memoria de `main2` **no aplica** en modo standalone (`_maybe_recycle_live` retorna cuando
`_OWN_DRIVER`, y `relaunch_live_driver` depende del panel). La red de seguridad es
OOM → crash → `run_live.sh`/systemd reinician.

---

## 6. Incidente 2026-07-23 — 38 días caído (lección)

**Qué pasó:** el servidor se reinició el 23-jul ~07:31. El live vivía en una sesión
**tmux** (`tmux_live`), que no sobrevive a un reboot, y **no había unidad systemd**.
Nadie lo relanzó: estuvo parado hasta el 2026-08-30, **38 días**.

**Cómo se detectó tarde:** no hay alerta. El síntoma en la BD eran partidos colgados en
`status=LIVE` con fecha vieja (17 en total: 4 del 18-jun, 1 del 19-jun, 3 del 18-jul,
1 del 20-jul, 6 del 22-jul), porque el live murió sin poder cerrarlos a `COMPLETED`.

**Pista falsa:** los últimos ciclos registraban `No route to host` contra la BD. Eran del
momento del reinicio, **no la causa** — la conectividad estaba bien al volver a arrancar.

**Corregido:** unidad systemd + linger (§2). Ya no depende de tmux.

**Pendiente de este incidente:** no hay notificación cuando el live se cae o se queda sin
escribir. Telegram está previsto en `config.py` (`TELEGRAM_BOT_TOKEN`/`CHAT_ID`, hoy
vacíos) pero sin configurar. Un `OnFailure=` en la unidad tampoco cubre el caso de
"vivo pero sin escribir".

---

## 7. Inconsistencias: dónde correrlas

El servidor **no tiene** los scripts. Dos opciones:

**(a) Desde local (recomendado, nada que desplegar).** La máquina local ya tiene los dos
venvs, geckodriver y la conexión verificada a la misma BD remota. Ver
[`RUNBOOK_PANEL.md`](RUNBOOK_PANEL.md) (pestaña Inconsistencias) y
[`scores_negativos_y_temporadas.md`](scores_negativos_y_temporadas.md).

**(b) Desplegar los scripts al servidor.** Habría que subir `scripts/` + dependencias
(~4 MB con `src/` y `check_points/`), como se armó `live_v2` en su día. Implica un
**segundo Firefox** en el server (hay RAM de sobra: 11 GB, live usa 1,4 GB) compitiendo
por CPU con el live.

### ⚠️ Un solo escritor

Local y servidor apuntan a la **misma BD remota**. Dos procesos escribiendo los mismos
partidos = conflictos. Antes de correr algo pesado en local, verificar qué está haciendo
el live del servidor, y viceversa. Es la decisión P7 de
[`pendientes_puesta_en_marcha.md`](pendientes_puesta_en_marcha.md), aún sin cerrar.

---

## 8. Cómo se armó el deploy (referencia)

Desplegado 2026-07-11/12 por rsync desde local. Fixes que hicieron falta y **no hay que
volver a romper**:

- **`main2.py:77`** — el fallback era `headless=False`; se cambió a `headless=LIVE_HEADLESS`
  (resuelto por `_resolve_live_headless`: env `LIVE_HEADLESS` > `config.LIVE_HEADLESS` >
  inferencia por `DISPLAY`). Sin esto el standalone intenta abrir Firefox con ventana y
  revienta en un server sin entorno gráfico. `run_live.sh` exporta `LIVE_HEADLESS=1`.
- **geckodriver ARM en server x86_64** — el del sistema daba `Exec format error`. Se puso
  el linux64 0.35.0 en `live_v2/venv/bin/` y el `PATH` de `run_live.sh` lo toma primero
  (el código lo resuelve con `shutil.which`). Firefox 121.
- **venv propio** en `live_v2/venv` (`--system-site-packages` + pip: `selenium`,
  `psycopg2-binary`, `requests`, `pycountry`, `Unidecode`, `IPython`, `psutil`).

Ver también [`especificacion_ejecucion_permanente.md`](especificacion_ejecucion_permanente.md):
el diseño completo (engine + panel como 2 servicios) del que esto es solo la primera pieza.
