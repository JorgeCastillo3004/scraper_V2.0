# Dashboard — Requerimientos y Estado de Implementación

**Archivo:** `dashboard/app.py`
**Framework:** Flet (Python) — UI web en puerto 8502
**Acceso:** `http://<SERVER_IP>:8502`
**Autenticación:** usuario/contraseña (env: `DASH_USER`, `DASH_PASS`)

---

## HEADER (barra superior)

| Funcionalidad | Estado |
|---|---|
| Mostrar totales globales de DB: partidos, equipos, noticias | ✅ Listo |
| Indicador de conexión a DB (punto verde/rojo) | ✅ Listo |
| Reloj con hora actual | ✅ Listo |
| Botón refrescar stats globales | ✅ Listo |
| Botón cerrar sesión | ✅ Listo |

---

## LOGIN
# puedes colocan una bandera para deshabilitar y al final de todas las pruebas se coloca, debes preguntar cuadno hacerlo  ❌ Pendiente |
| Funcionalidad | Estado |
|---|---|
| Pantalla de login con usuario y contraseña | ✅ Listo |
| Validación de credenciales (env vars con fallback) | ✅ Listo |
| Persistencia de sesión (page.session) | ✅ Listo |

---

## TAB: NOTICIAS

Controla la ejecución de `main_manual_adjust.py`.

| Funcionalidad | Estado |
|---|---|
| Mostrar últimas fechas guardadas por deporte (`last_saved_news.json`) | ✅ Listo |
| Botón Iniciar — lanza `milestone1.py` debe crear un driver, no hace falta realizar el login , ejecutar la funcion main_extract_news(driver, ['FOOTBALL','TENNIS','GOLF',"TENNIS", "BASKETBALL","AMERICAN_SPORTS","HOCKEY"], MAX_OLDER_DATE_ALLOWED=30) | ❌ Pendiente |
| se debe agregar un selector que permita configuar la hora de ejecucion y frecuencia de ejecucion.| ❌ Pendiente |
| Botón Detener — termina el subproceso | ✅ Listo |
| Log viewer en tiempo real (streaming stdout del proceso) | ✅ Listo |
| Indicador de estado: inactivo / ejecutando / finalizado | ✅ Listo |
| Coloreo de líneas de log (error=rojo, warn=amarillo, ok=verde) | ✅ Listo |
| Actualizar info de checkpoint al terminar | ✅ Listo |
| Programación de ejecución: seleccionar fecha/hora y frecuencia | ❌ Pendiente |

---

## TAB: LIGAS

Gestiona `check_points/leagues_info.json` y muestra stats por liga desde la DB.

| Funcionalidad | Estado |
|---|---|
| Cargar ligas desde `leagues_info.json` agrupadas por deporte | ✅ Listo |
| Sub-tabs por deporte (Football, Basketball, Baseball, Am. Football, Hockey) | ✅ Listo |
| Tabla por deporte con columnas: Liga, Equipos, Completados, Programados, En vivo, Results (switch), Fixtures (switch) | ✅ Listo |
| Switch results/fixtures por liga — modifica estado en memoria | ✅ Listo |
| Botón Guardar — persiste cambios de switches en `leagues_info.json` | ✅ Listo |
| Contador de ligas activas (results / fixtures) | ✅ Listo |
| Botón Recargar — recarga `leagues_info.json` y reconstruye la tabla | ✅ Listo |
| Botón "Actualizar desde DB" — consulta stats reales por liga | ✅ Listo |
| Notificación SnackBar al completar actualización desde DB | ✅ Listo |
| Consulta partidos COMPLETED / SCHEDULED / IN PROGRESS por `league_id` | ✅ Listo |
| Consulta equipos via `league_team JOIN team` por `league_id` | ✅ Listo |
| Guardar teams y matches en `leagues_info.json` tras actualizar desde DB | ✅ Listo |
| Spinner de carga mientras se obtienen stats de DB | ✅ Listo |
| Rebuild de filas en DataTable al recibir stats (no mutación de controles) | ✅ Listo |

---

## TAB: PARTIDOS

Controla la ejecución paralela de `paralel_execution.py` para las secciones `results` y `fixtures`.

**Mecanismo de comunicación:**
- Dashboard → proceso: escribe comando en `logs/run_control_{section}.json`
- Proceso → dashboard: escribe estado en `logs/run_status_{section}.json` cada ~0.25s
- Dashboard lee el archivo de status cada 2s (polling)

| Funcionalidad | Estado |
|---|---|
| Dos paneles independientes: RESULTS y FIXTURES | ✅ Listo |
| Selector de número de workers (1-8), default 4 | ✅ Listo |
| Diálogo de distribución de ligas por worker antes de iniciar | ✅ Listo |
| Botón Iniciar — lanza `paralel_execution.py N section --no-confirm` | ✅ Listo |
| Botón Detener — escribe comando `stop` en archivo de control | ✅ Listo |
| Botón Pausar — escribe comando `pause` en archivo de control | ✅ Listo |
| Botón Reanudar — escribe comando `resume` en archivo de control | ✅ Listo |
| Indicador de estado: inactivo / iniciando / running / paused / stopped / completed | ✅ Listo |
| Timestamp de última actualización del status | ✅ Listo |
| Worker cards: estado, liga actual, últimas 8 líneas de log por worker | ✅ Listo |
| Polling cada 2s del archivo `run_status_{section}.json` | ✅ Listo |
| Recuperar estado previo al arrancar (si existe `run_status` del run anterior) | ✅ Listo |
| Consumir stdout del subproceso para evitar bloqueo de buffer | ✅ Listo |
| Prevención de doble lanzamiento (guard en ProcessManager) | ✅ Listo |
| Barra de progreso por liga asignada a cada worker | ❌ Pendiente — requiere exponer `leagues_done/leagues_total` en `paralel_execution.py` |
| Log viewer con stdout del proceso (adicional a worker cards) | ❌ Pendiente |

---

## TAB: JUGADORES

Controla extracción de jugadores vía `main_manual_adjust.py --players-only`.

| Funcionalidad | Estado |
|---|---|
| Panel de control con botón Iniciar / Detener | ✅ Listo |
| Log viewer en tiempo real (streaming stdout) | ✅ Listo |
| Stats de jugadores en DB: total y top 10 ligas | ✅ Listo |
| Revisión y actualización de `milestone6.py` | ❌ Pendiente — verificar selectores y flujo |
| se debe integrar el milestone6, primero se debe verificar que todo este funcionando en este modulo
| tambien se debe agregar una seleccion de fecha hora de ejecucion y frecuencia.
| Se debe crear una session tmux, con la que se logre conectar y se pueda continuar ejecutando y controlando desde la app.
| se debe incluir control de ejecucion, inicio/pausa, detener, reinicar.


---

## TAB: EN VIVO  ← PRIORIDAD ACTUAL
- la session en tmux llamda "live" debe estar creada.
- en la session de tmux debe constantemente estarse ejecutando python "main2.py" usando el ambiente virtual llamado "sports_env" en caso de no existir se debe crear y instalarse las librerias indicadas en requirements.txt, en el path principal del proyecto.
- se debe obterner las impresiones que se muestran en la session llamada tmux "live", es decir al pasar a la seccion en vivo inmediatamente se deben mostrar.
- Controla la ejecución continua de `main2.py` (usa `milestone7.live_games`) via sesión **tmux**.
- Se debe poder pausar, reanudar, o detener el proceso, para ejecutar estas opciones, se usa un archivo json, que constantemente es leido por la  funcion "live_games"
- el driver no debe destruirse, solo en caso de presionar detenar. Y luego al reiniciar el proceso se ejcutaria de nuevo "python main2.py"
- realizar una prueba donde todos los botones esten funcionales y se imprima en log viewer las acciones indicadas por los botones sin ejecutar nada.
- la idea es controlor desde el panel live la ejecucion de main2.py
- las salidas e impresion del main2.py seran mostradas en esta seccion, log viewer, debe mostrarse todo con la misma velocidad de impresion que realiza el script "main2.py" evitando delays, el tamano del log viewer pude ser mas grande que el actual.
- verificar completo funcionamiento

### Arquitectura

```
tmux session "live"  — nunca se destruye, persiste independiente del dashboard
    │
    ├── venv activado al crear la sesión (source /home/you/env/sports_env/bin/activate)
    ├── pipe-pane → /tmp/live_output.log  (todo stdout redirigido aquí)
    └── proceso main2.py  (se inicia/detiene; la sesión permanece)

Control (app → proceso):   logs/run_control_live.json   { "command": "none|pause|resume|stop" }
Status  (proceso → app):   logs/run_status_live.json    { "state": "running|paused|stopped|error", "sports": [...] }

App lee output:  tail de /tmp/live_output.log en hilo daemon (no polling DB)
App lee estado:  polling run_status_live.json cada 2s
```

### Flujo Iniciar
1. Feedback UI inmediato (spinner + botones actualizados + `page.update()`)
2. Hilo background: `_tmux_ensure_session()` → crea sesión si no existe, activa venv, reinicia pipe-pane
3. Escribe `run_control_live.json` → `{"command": "none"}`
4. Envía comando via `tmux send-keys`: `python main2.py --interval N --sports S1 S2 ...`

### Flujo Detener
1. Feedback UI inmediato
2. Hilo background: escribe JSON `stop` → main2.py cierra limpiamente
3. Tras 4s de gracia: envía `Ctrl+C` a la sesión tmux como respaldo
4. Sesión tmux **permanece activa**

### Control pause/resume
- App escribe JSON → `main2.py` lo lee en cada iteración del wait-loop (cada 2s, línea 211 de `milestone7.py`)
- ⚠ Durante el ciclo activo de scraping (líneas 162-198 de `milestone7.py`) el control **no se verifica** — el delay máximo es la duración de un ciclo completo

### Puntos de chequeo de control en el código
| Archivo | Línea | Momento |
|---------|-------|---------|
| `main2.py` | 114 | Antes de lanzar el navegador |
| `main2.py` | 123 | Después del login |
| `main2.py` | 147 | Durante delay de reintento (cada 2s) |
| `milestone7.py` | 211 | **Loop principal** — cada 2s durante el intervalo de espera entre ciclos |

### Estado de implementación

| Funcionalidad | Estado |
|---|---|
| Sesión tmux `live` — creación automática si no existe | ✅ Listo |
| Activación de venv al crear la sesión | ✅ Listo |
| `pipe-pane` → `/tmp/live_output.log` | ✅ Listo |
| Tail de log file en tiempo real → log viewer | ✅ Listo |
| Selector de deportes activos (checkboxes) | ✅ Listo |
| Selector de intervalo entre ciclos | ✅ Listo |
| Botón Iniciar — send-keys a tmux con venv Python | ✅ Listo |
| Botón Detener — JSON stop + Ctrl+C de respaldo | ✅ Listo |
| Botón Pausar / Reanudar — JSON control | ✅ Listo |
| Spinner visible mientras inicia | ✅ Listo |
| Feedback inmediato en todos los botones (`page.update()` antes del trabajo) | ✅ Listo |
| Polling status JSON cada 2s → actualiza label + botones | ✅ Listo |
| `page.update()` protegido con try/except (WebSocket closing) | ✅ Listo |
| Auth desactivada (dev mode: `DASH_DEV_SKIP_AUTH = True`) | ✅ Temporal |
| **Verificar que tmux session se crea correctamente** | ✅ Listo — lógica revisada; `cd BASE_DIR` añadido al send-keys |
| **Verificar pipe-pane activo tras reinicio de sesión existente** | ✅ Listo — pipe-pane idempotente: stop (sin arg) + start (sin -o) |
| **Verificar tail se reconecta si /tmp/live_output.log es recreado** | ✅ Listo — detección por inode, reabre y notifica en log viewer |
| Indicador visual del estado de tmux session (existe / no existe) | ✅ Listo — `lbl_tmux` junto al título, actualizado cada 2s en poll_status |
| Botón "Ver sesión tmux" — abrir terminal integrada o instrucción de conexión | ✅ Listo — AlertDialog con `tmux attach -t live` |
| Reactivar autenticación para producción | ✅ Listo — `DASH_DEV_SKIP_AUTH` lee de env var (default: False) |

---

## INFRAESTRUCTURA / TRANSVERSAL

| Funcionalidad | Estado |
|---|---|
| `ProcessManager` — gestión de subprocesos con lock thread-safe | ✅ Listo |
| `make_log_viewer` — widget reutilizable con flush opcional | ✅ Listo |
| `stream_process` — batching de stdout cada 250ms (evita saturar page.update) | ✅ Listo |
| `page.update()` protegido en hilos daemon | ✅ Listo |
| `run_dev.py` — no abre pestaña nueva en reinicios (FLET_NO_BROWSER) | ✅ Listo |
| Múltiples clientes simultáneos (Flet web multi-session) | ⚠ No verificado |
| Reconexión automática a DB si cae la conexión | ⚠ Parcial (timeout en fetch, sin retry loop) |
| Manejo de errores en queries DB (no rompe la UI) | ✅ Listo |

---

## PRÓXIMAS TAREAS PRIORITARIAS

1. **Tab En Vivo** — verificar y estabilizar flujo completo con tmux (sesión, pipe-pane, tail, control JSON)
2. **Tab En Vivo** — reactivar autenticación antes de subir a producción
3. **Tab Partidos** — log viewer con stdout del proceso
4. **Tab Jugadores** — verificar selectores y flujo de `milestone6.py`
