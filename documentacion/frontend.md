# Frontend — scraper_V2.0 Control Panel

App web React + Vite para monitorear y controlar el pipeline de scraping desde el navegador.

---

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 18 + Vite + TailwindCSS |
| Backend API | FastAPI (ya en `requirements.txt`) |
| Comunicación en tiempo real | WebSocket (FastAPI nativo) |
| Base de datos | PostgreSQL vía psycopg2 (ya en `requirements.txt`) |
| Control de procesos | `subprocess.Popen` + archivos de control JSON |

---

## Arquitectura general

```
Browser (React + Vite)
  │
  ├─ HTTP (REST)   →  FastAPI  →  PostgreSQL / leagues_info.json / CONFIG.json
  └─ WebSocket     →  FastAPI  →  stdout de procesos Python (logs en tiempo real)

FastAPI
  ├─ Lanza procesos:   subprocess.Popen('python paralel_execution.py 3 results')
  ├─ Para procesos:    escribe logs/run_control_{section}.json → {"command":"stop"}
  ├─ Pausa procesos:   escribe logs/run_control_{section}.json → {"command":"pause"}
  └─ Lee estado:       logs/run_status_{section}.json
```

### Cómo se para o pausa un script

Los scripts ya tienen el mecanismo implementado. FastAPI **no mata el proceso** — solo escribe un archivo JSON:

```python
# FastAPI escribe:
logs/run_control_results.json  →  {"command": "stop"}
logs/run_control_results.json  →  {"command": "pause"}
logs/run_control_results.json  →  {"command": "resume"}
```

El script lee ese archivo en cada iteración de su loop y reacciona limpiamente (termina la liga actual antes de parar). Esto aplica a `paralel_execution.py`, `paralel_teams.py` y `paralel_players.py`.

Para `main2.py` (live), el mismo mecanismo aplica vía `check_control` callback que recibe `live_games`.

### Streaming de logs

```
FastAPI lanza:  subprocess.Popen([...], stdout=PIPE, stderr=STDOUT)
FastAPI lee:    proceso.stdout.readline()  — línea a línea
FastAPI envía:  WebSocket.send_text(línea)
React recibe:   onmessage → append a terminal virtual
```

---

## Pestañas de la aplicación

### 1. Noticias
**Script:** `main1.py` (sección NEWS) o llamada directa a `milestone1.py`

**Funcionalidades:**
- Ver y editar la configuración de schedule: hora de ejecución (`TIME` en `CONFIG.json`) y `MAX_OLDER_DATE_ALLOWED`
- Selector de deportes habilitados para la extracción
- Botón **Ejecutar ahora** → lanza extracción inmediata (ignora el cron)
- Botón **Detener**
- Terminal en tiempo real con el stdout del script (WebSocket)
- Badge de estado: `RUNNING` / `STOPPED`

```
┌─ Noticias ──────────────────────────────────────────────────┐
│  Schedule:  [08:00]  Frecuencia: [Diaria ▼]                 │
│  MAX días:  [31]                                            │
│  Deportes:  [✓ FOOTBALL] [✓ TENNIS] [✓ BASKETBALL] [...]   │
│                                                             │
│  [▶ Ejecutar ahora]  [■ Detener]        ESTADO: STOPPED    │
│                                                             │
│  ┌─ Logs ────────────────────────────────────────────────┐  │
│  │ [NEWS] FOOTBALL - procesando...                       │  │
│  │   [0] 2024-03-15 → 2024-03-15 10:00:00               │  │
│  │   ✓ agregada (total batch: 3)                         │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

### 2. Ligas
**Script:** `milestone2.py` → `create_leagues(driver, list_sports)`

**Funcionalidades:**
- Tabla con ligas registradas en DB: sport / país / liga / temporada / equipos / partidos
- Selector de deportes para lanzar creación de nuevas ligas
- Botón **Crear ligas** → lanza `create_leagues` para los deportes seleccionados
- Terminal con logs en tiempo real
- Badge de estado por proceso

```
┌─ Ligas ─────────────────────────────────────────────────────┐
│  Crear ligas para:                                          │
│  [✓ FOOTBALL] [✓ BASKETBALL] [✓ BASEBALL] [✓ HOCKEY] [...]  │
│  [▶ Crear ligas]  [■ Detener]       ESTADO: STOPPED        │
│                                                             │
│  ┌─ Ligas registradas ──────────────────────────────────┐   │
│  │ Sport      │ País       │ Liga            │ Equipos  │   │
│  │ FOOTBALL   │ Brazil     │ Serie A Betano  │ 20       │   │
│  │ BASKETBALL │ USA        │ NBA             │ 30       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ Logs ────────────────────────────────────────────────┐  │
│  │ ...                                                   │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

### 3. Equipos
**Script:** `paralel_teams.py` → `teams_creation` (milestone3)

**Funcionalidades:**
- Tabla de ligas con columnas: sport / liga / equipos esperados / equipos en DB / results / fixtures / estado checkpoint
- Selector multi-liga filtrable por deporte
- Selector de número de workers (1–5)
- Filtro opcional por pocos equipos en DB (`teams_db <= threshold`)
- Toggle por liga sobre `teams_creation.extract`
- Botón **Crear equipos** → lanza `paralel_teams.py N --selection-file ...` con las ligas seleccionadas
- Botón **Detener** / **Pausar** / **Reanudar**
- Resumen agregado de ligas habilitadas, pendientes y conteos
- Panel de screenshots por worker
- Terminal con logs por worker

```
┌─ Equipos ───────────────────────────────────────────────────┐
│  Workers: [3 ▼]    Filtrar: [FOOTBALL ▼]  Máx equipos: [5]  │
│                                                             │
│  ┌─ Selección de ligas ─────────────────────────────────┐   │
│  │ [✓] Serie A Betano   │ DB 18 │ Esp 20 │ 340/40     │   │
│  │ [✓] Primera A        │ DB 12 │ Esp 20 │ 270/18     │   │
│  │ [ ] Premier League   │ DB 20 │ Esp 20 │ 380/0      │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  [▶ Crear equipos]  [⏸ Pausar]  [■ Detener]  RUNNING       │
│                                                             │
│  ┌─ Capturas ───────────────────────────────────────────┐   │
│  │ Worker 0  [screenshot]   Worker 1  [screenshot]     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### Notas operativas

- La lista de deportes sale de la tabla `sport` en la DB remota y luego se mapea al nombre usado por el proyecto.
- `Esperados` viene de `check_points/leagues_info.json`, campo `teams`.
- `Equipos DB`, `Results` y `Fixtures` vienen de conteos reales en la DB remota.
- El frontend envía solo `{sport, key}` por liga; la API completa la metadata cargando `leagues_info.json`.
- Las capturas se sirven desde `logs/screenshots/teams/latest/` vía FastAPI.

---

### 4. Partidos
**Script:** `paralel_execution.py` → `extraction_by_dict` (milestone4)

**Funcionalidades:**
- Tabs internos: **Results** | **Fixtures**
- Tabla de ligas con: sport / liga / partidos en DB / `extract_results.extract` / `extract_fixtures.extract`
- Toggle por liga para habilitar/deshabilitar (escribe en `leagues_info.json`)
- Selector de número de workers
- Botón **Extraer results** → lanza `paralel_execution.py N results` con ligas seleccionadas
- Botón **Extraer fixtures** → lanza `paralel_execution.py N fixtures`
- Botón **Detener** / **Pausar** / **Reanudar**
- Terminal con logs por worker

```
┌─ Partidos ──────────────────────────────────────────────────┐
│  [Results]  [Fixtures]                                      │
│                                                             │
│  Workers: [3 ▼]    Filtrar: [FOOTBALL ▼]                   │
│                                                             │
│  ┌─ Ligas ──────────────────────────────────────────────┐   │
│  │      Liga             │ Partidos │ Results │ Fixtures │   │
│  │ [✓] Serie A Betano    │  380     │   ON ●  │  OFF ○   │   │
│  │ [✓] Primera A         │  270     │   ON ●  │  OFF ○   │   │
│  │ [ ] Premier League    │  380     │   ON ●  │   ON ●   │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  [▶ Extraer Results]  [▶ Extraer Fixtures]                  │
│  [⏸ Pausar]  [■ Detener]               ESTADO: STOPPED     │
│                                                             │
│  ┌─ Logs ──────────────────────────────────────────────┐    │
│  │ [W0] LIGA: FOOTBALL / Serie A Betano                │    │
│  │ [W0] Rondas creadas: 38                             │    │
│  │ [W1] LIGA: FOOTBALL / Primera A                     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

### 5. Jugadores
**Script:** `paralel_players.py` → `players` (milestone6)

**Funcionalidades:**
- Tabla de ligas con: sport / liga / equipos / jugadores en DB
- Selector multi-liga filtrable por deporte
- Selector de número de workers
- Botón **Extraer jugadores** → lanza `paralel_players.py N --sport X`
- Botón **Detener** / **Pausar** / **Reanudar**
- Terminal con logs en tiempo real

---

### 6. Live
**Script:** `main2.py` → `live_games` (milestone7)

**Funcionalidades:**
- Botón **Iniciar** / **Detener**
- Selector de deportes a monitorear
- Selector de intervalo entre ciclos (60s, 120s, 300s)
- Terminal con logs en tiempo real (WebSocket)
- Tabla de partidos detectados en el ciclo actual: liga / local / visitante / score / estado

```
┌─ Live ──────────────────────────────────────────────────────┐
│  Deportes: [✓ FOOTBALL] [✓ BASKETBALL] [✓ HOCKEY]          │
│  Intervalo: [60s ▼]                                         │
│                                                             │
│  [▶ Iniciar]  [■ Detener]              ESTADO: STOPPED     │
│                                                             │
│  ┌─ Partidos en vivo ───────────────────────────────────┐   │
│  │ Liga          │ Local      │ Visitante  │ Score │ St  │   │
│  │ Premier Lge   │ Arsenal    │ Chelsea    │ 1 - 0 │ 67' │   │
│  │ NBA           │ Lakers     │ Celtics    │ 89-92 │ Q3  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ Logs ──────────────────────────────────────────────┐    │
│  │ [LIVE] FOOTBALL - 3 partidos encontrados            │    │
│  │ Updated: Arsenal~Chelsea                            │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

### 7. Inconsistencias
**Endpoint:** `GET /api/inconsistencias` (alimenta `pages/Inconsistencias.jsx`)

Pantalla de **diagnóstico de integridad** (solo lectura). Cada tarjeta es una
categoría de inconsistencia detectada en la base. Click en una tarjeta abre el
desglose por liga (top 15) en la tabla inferior.

Categorías mostradas (`severity` controla el color):

| key                | severity | Qué cuenta |
|---|---|---|
| `score_minus_one`  | high   | partidos pasados con `score_entity.points = -1` |
| `fk_roto_team`     | high   | `match_detail.team_id` apunta a un `team` que no existe |
| `detail_no_2`      | medium | partidos con `match_detail` ≠ 2 filas |
| `detail_no_score`  | medium | `match_detail` sin `score_entity` |
| `status_legacy`    | low    | `match.status` con valores legacy (`completed`, `R`, `P`, ...) |

```
┌─ Inconsistencias ───────────────────────────────────────────┐
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐              │
│  │ 2714 │ │ 2729 │ │  7   │ │  5   │ │  0   │              │
│  │score │ │ FK   │ │ ≠2   │ │ no   │ │legacy│              │
│  │ =-1  │ │ rota │ │detail│ │score │ │status│              │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘              │
│                                                             │
│  Desglose por liga — Partidos pasados con score = -1  [15] │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Football │ ENGLAND │ Premier League        │   233  │    │
│  │ Football │ GERMANY │ Bundesliga            │   209  │    │
│  │ Football │ ITALY   │ Serie A               │   189  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  Cómo corregir → ver mejoras_performance.md §3 / §3bis      │
└─────────────────────────────────────────────────────────────┘
```

Refresca cada 60 s y con botón manual. El resumen viene cacheado server-side
60 s para no presionar Postgres. Las acciones de corrección (lanzar
`fix_live_matches.py`, etc.) siguen haciéndose desde terminal — esta pantalla
es diagnóstico puro.

---

## API FastAPI — Endpoints

### Control de procesos
```
POST /api/{section}/start        →  lanza proceso con parámetros (workers, ligas, sport)
POST /api/{section}/stop         →  escribe {"command":"stop"}  en run_control_{section}.json
POST /api/{section}/pause        →  escribe {"command":"pause"} en run_control_{section}.json
POST /api/{section}/resume       →  escribe {"command":"resume"}
GET  /api/{section}/status       →  lee run_status_{section}.json → {status, workers, progress}
WS   /api/{section}/logs         →  stream de stdout del proceso activo
```

Secciones disponibles: `news`, `leagues`, `teams`, `results`, `fixtures`, `players`, `live`

### Ligas y configuración
```
GET  /api/leagues                →  todas las ligas de leagues_info.json con stats de DB
PATCH /api/leagues/{key}         →  toggle extract_results.extract o extract_fixtures.extract
GET  /api/config                 →  lee CONFIG.json
PATCH /api/config                →  actualiza horarios y deportes habilitados
```

### Base de datos
```
GET  /api/db/stats               →  conteos por deporte: ligas / equipos / partidos / jugadores
GET  /api/db/leagues/{sport}     →  detalle por liga: equipos + partidos (results + fixtures)
GET  /api/db/live                →  partidos con status LIVE o actualizados hoy
```

---

## Manejo de procesos — Process Manager

FastAPI mantiene un dict en memoria con los procesos activos:

```python
_processes: dict[str, subprocess.Popen] = {}

# Iniciar
proc = subprocess.Popen(
    ['python', 'paralel_execution.py', '3', 'results'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    cwd=PROJECT_ROOT, text=True
)
_processes['results'] = proc

# Detener limpiamente (vía archivo de control)
with open('logs/run_control_results.json', 'w') as f:
    json.dump({'command': 'stop'}, f)

# Kill forzado si no responde en 30s (fallback)
proc.wait(timeout=30)
if proc.poll() is None:
    proc.terminate()
```

---

## Estructura de archivos — proyecto

```
scraper_V2.0/
├── api/
│   ├── main.py              # FastAPI app + CORS + router registration
│   ├── routers/
│   │   ├── control.py       # start/stop/pause por sección
│   │   ├── leagues.py       # lectura y edición de leagues_info.json
│   │   ├── config.py        # lectura y edición de CONFIG.json
│   │   └── stats.py         # queries a PostgreSQL
│   ├── services/
│   │   ├── process_manager.py   # subprocess lifecycle + archivos de control
│   │   └── log_streamer.py      # lectura de stdout → WebSocket
│   └── ws/
│       └── logs.py          # WebSocket handler
│
└── frontend/
    ├── src/
    │   ├── pages/
    │   │   ├── Noticias.jsx
    │   │   ├── Ligas.jsx
    │   │   ├── Equipos.jsx
    │   │   ├── Partidos.jsx
    │   │   ├── Jugadores.jsx
    │   │   └── Live.jsx
    │   ├── components/
    │   │   ├── Terminal.jsx     # terminal virtual para logs (WebSocket)
    │   │   ├── LeagueTable.jsx  # tabla de ligas con toggles
    │   │   ├── StatusBadge.jsx  # RUNNING / STOPPED / PAUSED
    │   │   └── WorkerPanel.jsx  # panel por worker con logs
    │   ├── hooks/
    │   │   ├── useWebSocket.js  # hook para logs en tiempo real
    │   │   └── useProcess.js    # start/stop/pause/status
    │   └── api/
    │       └── client.js        # axios wrapper con base URL de FastAPI
    ├── package.json
    └── vite.config.js
```

---

## Inicio del entorno

```bash
# Backend (servidor)
cd scraper_V2.0
source env/sports_env/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend (local o servidor)
cd frontend
npm install
npm run dev        # desarrollo  → http://localhost:5173
npm run build      # producción  → dist/ (servir con nginx o FastAPI StaticFiles)
```

---

## Notas de implementación

- **CORS:** FastAPI debe tener `CORSMiddleware` habilitado para aceptar peticiones desde el puerto de Vite.
- **Concurrencia:** Un solo proceso por sección a la vez. Si ya hay uno corriendo, el endpoint `/start` retorna 409.
- **Seguridad:** La API solo debe ser accesible desde la red local o vía SSH tunnel. No exponer al internet sin autenticación.
- **Logs persistidos:** Redirigir stdout de cada proceso a `logs/{section}_{timestamp}.log` además del WebSocket, para historial.
