# API — scraper_V2.0 Control API

FastAPI como intermediaria entre el frontend React y los procesos Python del scraper.

---

## Inicio

```bash
cd scraper_V2.0
source env/sports_env/bin/activate
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Swagger UI: `http://localhost:8000/docs`

---

## Endpoints de control de procesos

### `POST /api/{section}/start`
Lanza el proceso del scraper para la sección indicada.

**Secciones:** `news` | `leagues` | `teams` | `results` | `fixtures` | `players` | `live`

**Body:**
```json
{ "workers": 3, "sports": ["FOOTBALL", "BASKETBALL"], "days": 31 }
```

| Campo | Aplica a | Default |
|---|---|---|
| `workers` | teams, results, fixtures, players | 2 |
| `sports` | news, leagues, teams, players | [] |
| `days` | news | 31 |

**Respuesta 200:**
```json
{ "ok": true, "pid": 12345, "cmd": "python paralel_execution.py 3 results --no-confirm" }
```
**Respuesta 409:** proceso ya corriendo.

---

### `POST /api/{section}/stop`
Para el proceso limpiamente escribiendo `{"command":"stop"}` en `logs/run_control_{section}.json`. El script termina la liga actual antes de salir.

### `POST /api/{section}/pause`
Escribe `{"command":"pause"}`. El script se bloquea al final de la liga actual.

### `POST /api/{section}/resume`
Escribe `{"command":"resume"}`. El script retoma desde donde pausó.

### `GET /api/{section}/status`
Estado actual del proceso.

**Respuesta:**
```json
{
  "section": "results",
  "status": "running",
  "pid": 12345,
  "started_at": "2024-03-15T10:00:00",
  "run_status": {
    "workers": {
      "0": { "status": "running", "current_league": "BRAZIL_Serie A Betano" },
      "1": { "status": "done" }
    },
    "completed_leagues": 8,
    "total_leagues": 45
  }
}
```

### `GET /api/status/all`
Estado de todas las secciones en una sola llamada.

---

## Endpoints de ligas

### `GET /api/leagues?sport=FOOTBALL`
Lista todas las ligas enriquecidas con estadísticas de DB.

**Respuesta:**
```json
[{
  "sport": "FOOTBALL",
  "key": "BRAZIL_Serie A Betano",
  "league_name": "Serie A Betano",
  "league_id": "abc123",
  "teams_db": 20,
  "matches_db": 380,
  "extract_results": true,
  "extract_fixtures": false,
  "teams_extract": false
}]
```

### `PATCH /api/leagues/{sport}/{key}`
Habilita o deshabilita una liga para una sección.

**Body:**
```json
{ "field": "extract_results", "value": true }
```

**Campos válidos:** `extract_results` | `extract_fixtures` | `teams_creation`

### `GET /api/leagues/sports`
Lista de deportes disponibles en `leagues_info.json`.

---

## Endpoints de configuración

### `GET /api/config`
Lee `check_points/CONFIG.json`.

### `PATCH /api/config`
Actualiza campos en `CONFIG.json`. Solo los campos enviados se modifican.

**Body ejemplo:**
```json
{
  "EXTRACT_NEWS": {
    "TIME": "0 9 * * *",
    "SPORTS": ["FOOTBALL", "TENNIS"],
    "MAX_OLDER_DATE_ALLOWED": 31
  }
}
```

---

## Endpoints de estadísticas

### `GET /api/stats`
Conteos globales por deporte.

**Respuesta:**
```json
[{
  "sport": "Football",
  "leagues": 45,
  "teams": 800,
  "matches": 15000,
  "players": 22000
}]
```

### `GET /api/stats/live`
Partidos con status `LIVE` o `COMPLETED` del día de hoy.

### `GET /api/inconsistencias`
Resumen de inconsistencias detectadas en la base de datos (alimenta la pestaña
Inconsistencias del frontend). Resultado cacheado 60 s.

**Respuesta:**
```json
{
  "timestamp": "2026-05-24T09:49:42",
  "summary": {
    "score_minus_one":  2714,
    "fk_roto_team":     2729,
    "detail_no_2":      7,
    "detail_no_score":  5,
    "status_legacy":    0
  },
  "items": [
    { "key": "score_minus_one", "label": "Partidos pasados con score = -1",
      "severity": "high", "count": 2714 }
  ],
  "by_league": {
    "score_minus_one": [
      { "sport": "Football", "country": "ENGLAND",
        "league": "Premier League", "count": 233 }
    ]
  }
}
```

Cada `by_league[key]` viene con top 15. Ver `documentacion/mejoras_performance.md`
para la receta de corrección de cada categoría.

---

## WebSocket — Streaming de logs

### `WS /ws/{section}/logs`

Al conectar:
1. Recibe el historial acumulado (hasta 500 líneas) inmediatamente.
2. Recibe cada nueva línea de stdout del proceso en tiempo real.
3. Cuando el proceso termina, recibe `{"type":"status","value":"stopped"}`.

**Ejemplo JavaScript:**
```js
const ws = new WebSocket('ws://localhost:8000/ws/results/logs')
ws.onmessage = ({ data }) => console.log(data)
```

Múltiples clientes pueden conectarse al mismo stream simultáneamente.

---

## Archivos de control

| Archivo | Escribe | Lee |
|---|---|---|
| `logs/run_control_{section}.json` | API | Script Python |
| `logs/run_status_{section}.json` | Script Python | API |
| `logs/{section}_{timestamp}.log` | API (stdout capture) | — |

---

## Estructura de archivos

```
api/
├── main.py              # FastAPI app, CORS, lifespan, routers
├── config.py            # Rutas del proyecto (PROJECT_ROOT, LOGS_DIR, etc.)
├── routers/
│   ├── control.py       # POST start/stop/pause/resume, GET status
│   ├── leagues.py       # GET/PATCH ligas
│   ├── stats.py         # GET stats globales y live
│   └── app_config.py    # GET/PATCH CONFIG.json
├── services/
│   ├── process_manager.py   # subprocess lifecycle + log streaming
│   └── database.py          # queries psycopg2 directas (sin importar data_base.py)
└── ws/
    └── logs.py          # WebSocket handler
```

---

## Comandos lanzados por sección

| Sección | Comando |
|---|---|
| news | `python scripts/run_news.py --sports FOOTBALL,TENNIS --days 31` |
| leagues | `python scripts/run_leagues.py --sports FOOTBALL` |
| teams | `python paralel_teams.py 2 --no-confirm [--sport FOOTBALL]` |
| results | `python paralel_execution.py 3 results --no-confirm` |
| fixtures | `python paralel_execution.py 3 fixtures --no-confirm` |
| players | `python paralel_players.py 2 --no-confirm [--sport FOOTBALL]` |
| live | `python main2.py` |
