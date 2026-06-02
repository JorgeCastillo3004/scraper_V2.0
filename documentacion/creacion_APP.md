# App de Control del Scraper — Propuesta

App web para monitorear y controlar el pipeline desde el navegador. Reemplaza al dashboard Flet actual (no funcional).

---

## Objetivos

- Ver en tiempo real el estado de cada sección del scraper (running / stopped / paused)
- Iniciar, detener y pausar secciones individualmente
- Ver logs en vivo de cada worker
- Habilitar/deshabilitar ligas desde la UI (edita `leagues_info.json`)
- Ver estadísticas de la DB (conteos por deporte y liga)

---

## Stack recomendado

| Capa | Tecnología | Razón |
|---|---|---|
| Backend API | **FastAPI** (ya en `requirements.txt`) | Async nativo, ya disponible |
| Frontend | **React + Vite** o **HTMX** | React para interactividad rica; HTMX si se prefiere Python-first |
| Comunicación en vivo | **WebSocket** (FastAPI nativo) | Streaming de logs y estado sin polling |
| Proceso del scraper | `subprocess` + archivos de control | Sin cambiar la arquitectura actual |
| Archivos de control | `logs/run_control_{section}.json` | Ya usado por `paralel_execution.py` |

---

## Arquitectura propuesta

```
Browser
  │  HTTP / WebSocket
  ▼
FastAPI (app/main.py)
  │
  ├─ GET  /status              →  estado de cada sección
  ├─ POST /control/{section}   →  {action: start|stop|pause|resume}
  ├─ GET  /logs/{section}      →  últimas N líneas de log
  ├─ WS   /ws/logs/{section}   →  stream de logs en tiempo real
  ├─ GET  /leagues             →  ligas habilitadas/deshabilitadas
  ├─ POST /leagues/{key}       →  toggle extract_results.extract
  └─ GET  /db/stats            →  conteos de partidos/equipos por liga
  │
  ├─ Lee:  logs/run_status_{section}.json   (estado escrito por paralel_execution.py)
  ├─ Escribe: logs/run_control_{section}.json  (comandos: stop/pause/resume)
  └─ Lee/Escribe: check_points/leagues_info.json
```

---

## Formato de archivos de control existentes

### `logs/run_status_{section}.json` (escrito por el scraper)
```json
{
  "status": "running",
  "workers": {
    "0": { "status": "running", "current_league": "BRAZIL_Serie A Betano" },
    "1": { "status": "done" }
  },
  "started_at": "2024-03-15T10:00:00",
  "total_leagues": 45,
  "completed": 12
}
```

### `logs/run_control_{section}.json` (leído por el scraper)
```json
{
  "command": "stop"    // "stop" | "pause" | "resume" | null
}
```

---

## Pantallas principales

### 1. Dashboard general
```
┌─────────────────────────────────────────────────────┐
│  scraper_V2.0  Control Panel          [2024-03-15]  │
├──────────┬──────────┬──────────┬────────────────────┤
│ RESULTS  │ FIXTURES │ LIVE     │ NEWS               │
│ RUNNING  │ STOPPED  │ RUNNING  │ STOPPED            │
│ 12/45    │  —       │  —       │  —                 │
│ [Stop]   │ [Start]  │ [Stop]   │ [Start]            │
└──────────┴──────────┴──────────┴────────────────────┘
│ Workers activos (results):                          │
│   Worker 0: BRAZIL_Serie A Betano                   │
│   Worker 1: COLOMBIA_Primera A                      │
└─────────────────────────────────────────────────────┘
```

### 2. Panel de logs (por sección)
- Stream en tiempo real via WebSocket
- Filtro por worker / nivel (INFO, WARN, ERROR)
- Scroll automático con opción de pausar

### 3. Gestión de ligas
- Tabla con: sport / country / liga / results habilitado / fixtures habilitado
- Toggle para habilitar/deshabilitar sin editar JSON manualmente
- Filtro por deporte

### 4. Estadísticas DB
- Tabla: deporte / ligas / equipos / partidos
- Llamada a `scripts/db_status.py` o queries directas via `data_base.py`

---

## Estructura de archivos propuesta

```
app/
├── main.py              # FastAPI entrypoint
├── routers/
│   ├── control.py       # endpoints de control (start/stop/pause)
│   ├── status.py        # endpoints de estado
│   ├── leagues.py       # endpoints de gestión de ligas
│   └── stats.py         # endpoints de estadísticas DB
├── services/
│   ├── scraper.py       # leer/escribir archivos de control
│   ├── leagues.py       # leer/escribir leagues_info.json
│   └── database.py      # queries de estadísticas
├── ws/
│   └── logs.py          # WebSocket handler para streaming de logs
└── frontend/            # React/HTMX (o servir desde FastAPI con StaticFiles)
```

---

## Comando de inicio

```bash
# Desarrollo
uvicorn app.main:app --reload --port 8502

# Producción
uvicorn app.main:app --host 0.0.0.0 --port 8502 --workers 1
```

---

## Integración con el scraper actual

No requiere cambios en `milestone*.py` ni `paralel_execution.py`. La app lee y escribe los mismos archivos de control que ya existen:

- `logs/run_status_{section}.json` → **solo lectura** por la app
- `logs/run_control_{section}.json` → **escritura** por la app, lectura por el scraper
- `check_points/leagues_info.json` → lectura/escritura compartida (requiere file lock)
