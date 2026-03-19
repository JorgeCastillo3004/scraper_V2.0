# PROJECT_CONTEXT.md
> Documento de onboarding para agentes nuevos. Explica arquitectura, flujo de datos, módulos y archivos clave.

---

## 1. ¿Qué hace este proyecto?

**scraper_V2.0** es un pipeline de recolección de datos deportivos. Extrae información de **FlashScore.com** usando Selenium y la persiste en **PostgreSQL**. Corre en un servidor remoto de forma continua con dos hilos principales: uno para scraping programado y otro para scores en vivo.

**Deportes cubiertos:** Football, Basketball, Baseball, Hockey, American Football, Tennis, Golf, Boxing, Formula 1

---

## 2. Arquitectura general

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                              │
│         ThreadPoolExecutor → 2 threads en paralelo          │
└────────────────┬────────────────────┬───────────────────────┘
                 │                    │
    ┌────────────▼──────────┐  ┌──────▼───────────────────┐
    │       main1.py        │  │       main2.py            │
    │  Scraping programado  │  │   Scores en vivo          │
    │  (cron scheduling)    │  │   live_games()            │
    └────────────┬──────────┘  └──────────────────────────┘
                 │
    ┌────────────▼──────────────────────────────────────────┐
    │              6 secciones (CONFIG.json schedule)        │
    │  news → leagues → teams → results → fixtures → players │
    └────────────┬──────────────────────────────────────────┘
                 │
    ┌────────────▼──────────────────────────────────────────┐
    │                src/milestone*.py                       │
    │  Extracción por sección vía Selenium + Firefox         │
    └────────────┬──────────────────────────────────────────┘
                 │
    ┌────────────▼────────────┐   ┌──────────────────────┐
    │   check_points/*.json   │   │     PostgreSQL         │
    │   (estado intermedio)   │   │  (persistencia final) │
    └─────────────────────────┘   └──────────────────────┘
```

**Ejecución paralela alternativa** (`paralel_execution.py`):
```
python paralel_execution.py 3 results
    → Abre 3 browsers → reparte ligas → cada worker corre extraction_by_dict()
    → DB-based claim/release evita colisiones entre workers
```

---

## 3. Archivos de entrada y cuándo usarlos

| Archivo | Cuándo usar |
|---|---|
| `main.py` | Producción — lanza todo el sistema |
| `main1.py` | Solo scraping programado (sin live) |
| `main2.py` | Solo scores en vivo |
| `main_manual_adjust.py` | Debug/pruebas — flags booleanos por sección |
| `paralel_execution.py` | Extracción masiva de results/fixtures en paralelo |

---

## 4. Módulos `src/`

### 4.1 `milestone1.py` — Noticias
- **Función principal:** `main_extract_news(driver, list_sports, MAX_OLDER_DATE_ALLOWED)`
- Navega a la sección News de FlashScore por cada deporte
- Extrae listado (`get_list_recent_news`) + detalle (`get_news_info_part2`)
- **Checkpoint:** `check_points/last_saved_news.json` — guarda última fecha por deporte
- **Selectores CSS actualizados** (FlashScore migró a clases `wcl-*`):
  ```python
  XPATH_ARTICLES = '//div[@class="fsNews"]//a[contains(@class,"wcl-article")]'
  XPATH_TITLE    = './/*[contains(@class,"wcl-headline") or @role="heading"]'
  XPATH_META     = './/*[contains(@class,"wcl-newsMeta")]'
  XPATH_IMAGE    = './/figure//img'
  ```
- Scroll infinito reemplazó el botón "Show more"

### 4.2 `milestone2.py` — Ligas y temporadas
- **Función principal:** `create_leagues(driver, list_sports)`
- Navega el árbol de FlashScore: deporte → categoría → liga → temporada
- Crea registros en DB: country, league, season
- **Checkpoint:** `check_points/leagues_season/{SPORT}/{league}.json`

### 4.3 `milestone3.py` — Equipos
- **Función principal:** `teams_creation(driver, list_sports)`
- Para cada liga en `leagues_info.json` extrae la tabla de equipos de FlashScore
- Guarda equipos en DB + genera `league_team_entity`
- **Checkpoint:** `check_points/leagues_season/{SPORT}/{league}.json` (campo `teams_ready`)

### 4.4 `milestone4.py` — Results y Fixtures (módulo más grande: ~1450 líneas)
- **Función principal:** `results_fixtures_extraction(driver, list_sports, name_section)`
- **Función para paralel:** `extraction_by_dict(driver, sport_leagues_dict, name_section)`
- Itera rondas → partidos → extrae resultado/fixture por partido
- Guarda archivos de ronda en `check_points/results/{PAÍS_Liga}/` o `fixtures/`
- Inserta en DB: match, match_details, score
- **Control de errores:**
  ```python
  MATCH_MAX_ATTEMPTS = 3           # reintentos por partido
  LEAGUE_MAX_RETRIES = 2           # reintentos por liga
  LEAGUE_MAX_CONSECUTIVE_FAILS = 4 # warning si supera
  ```
- Deportes especiales: Tennis (`get_complete_match_info_tennis`), Golf, Boxing, F1

### 4.5 `milestone6.py` — Jugadores
- **Función principal:** `players(driver, list_sports)`
- Navega por cada equipo → extrae squad → per jugador extrae stats
- Checkpoint por equipo en `check_points/leagues_season/`

### 4.6 `milestone7.py` / `milestone8.py` — Live scores
- **M7:** `live_games(driver, list_sports)` — encuentra partidos en vivo y los registra
- **M8:** `update_lives_matchs(driver)` — actualiza scores de partidos ya registrados
- Usados por `main2.py`

### 4.7 `common_functions.py` — Utilidades transversales (655 líneas)
Funciones que usan TODOS los milestones:

| Grupo | Funciones clave |
|---|---|
| Selenium | `launch_navigator`, `login`, `dismiss_cookies`, `wait_update_page` |
| Checkpoints JSON | `load_json`, `save_check_point`, `load_check_point` |
| Scheduling | `execute_section`, `update_data` |
| Liga/ronda | `store_league_info`, `enable_league`, `get_resume_point`, `update_resume_point` |
| Utilidades | `process_date`, `generate_uuid`, `clean_field`, `save_image` |

### 4.8 `data_base.py` — Acceso a PostgreSQL (760 líneas)
Todas las operaciones de DB. Grupos:

| Grupo | Funciones clave |
|---|---|
| Conexión | `getdb()`, `ensure_connection()` |
| País/Deporte | `create_country`, `get_country_id`, `get_dict_sport_id` |
| Liga/Temporada | `save_league_info`, `save_season_database` |
| Equipo | `save_team_info`, `get_team_id_db`, `check_team_duplicates` |
| Partido | `save_math_info`, `save_score_info`, `check_match_duplicate` |
| Jugador | `save_player_info`, `check_player_duplicates` |
| Noticias | `save_news_database` |
| **Checkpoint multi-worker** | `claim_league`, `release_league`, `update_league_checkpoint`, `get_league_checkpoint`, `cleanup_stale_leagues` |

---

## 5. Archivo central: `check_points/leagues_info.json`

Es el **registro maestro de ligas**. Controla qué ligas se extraen y en qué estado están.

### Estructura:
```json
{
  "FOOTBALL": {
    "Argentina_Liga Profesional": {
      "league_id": "abc123",
      "country_id": "xyz",
      "sport_id": "sp1",
      "season_id": "sea1",
      "teams": 28,
      "matches": 150,
      "extract_results": {
        "extract": true
      },
      "extract_fixtures": {
        "extract": false
      }
    }
  },
  "BASKETBALL": { ... },
  "TENNIS": { ... }
}
```

### Cómo se usa:

```
leagues_info.json
       │
       ├─► paralel_execution.py
       │     get_enabled_leagues(section)  → filtra extract_results.extract == true
       │     split_into_dicts(leagues, N)  → reparte entre N workers
       │
       ├─► milestone4.py
       │     results_fixtures_extraction() → itera ligas habilitadas
       │
       ├─► milestone3.py
       │     teams_creation()              → crea equipos por liga
       │
       └─► scripts/check_teams_match_db.py
             → sincroniza campos "teams" y "matches" con conteos reales en DB
```

### Para habilitar/deshabilitar una liga:
Cambiar `extract_results.extract` o `extract_fixtures.extract` a `true`/`false`.

---

## 6. `check_points/CONFIG.json` — Configuración global

Controla scheduling y deportes activos por sección:

```json
{
  "DATA_BASE": true,
  "EXTRACT_NEWS":    { "TIME": "0 8 * * *",  "SPORTS": ["FOOTBALL", "TENNIS"], "MAX_OLDER_DATE_ALLOWED": 30 },
  "CREATE_LEAGUES":  { "TIME": "0 2 * * 1",  "SPORTS": ["FOOTBALL", ...] },
  "CREATE_TEAMS":    { "TIME": "0 3 * * 2",  "SPORTS": ["FOOTBALL", ...] },
  "GET_RESULTS":     { "TIME": "0 6 * * *",  "SPORTS": ["FOOTBALL", ...] },
  "GET_FIXTURES":    { "TIME": "0 7 * * *",  "SPORTS": ["FOOTBALL", ...] },
  "GET_PLAYERS":     { "TIME": "0 4 * * 0",  "SPORTS": ["FOOTBALL", ...] }
}
```

`main1.py` recarga este archivo cada 5 segundos → permite cambiar schedules en caliente.

---

## 7. Sistema de checkpoints (dos niveles)

### Nivel 1 — Archivos JSON (`check_points/`)
```
check_points/
├── CONFIG.json                    # Schedules globales
├── leagues_info.json              # Maestro de ligas y tambien se registra el check point para cada liga.
├── last_saved_news.json           # Última noticia por deporte
├── scraper_control.json           # Señales de control (pause/stop)
├── results/
│   └── {PAÍS}_{Liga}/
│       ├── Round_1.json           # Partidos pendientes de ronda 1
│       └── Round_2.json
├── fixtures/
│   └── {PAÍS}_{Liga}/
│       └── Round_N.json
└── leagues_season/
    └── {SPORT}/
        └── {Liga}.json            # Estructura de rondas/temporada
```

### Nivel 2 — Tabla `running_leagues` (PostgreSQL)
Para coordinación entre múltiples workers:
```sql
-- Columnas: league_id, section, host, started_at, status, current_round, current_match
-- Status: 'running' | 'completed' | 'interrupted'
```

**Flujo claim/release en milestone4:**
```
claim_league(league_id, section)
    ↓ si True (no la tiene otro worker)
get_league_checkpoint()  →  resume desde current_round/current_match
    ↓ por cada partido exitoso
update_league_checkpoint(round, match)
    ↓ al terminar
release_league(league_id, section, status='completed')
    ↓ si crash
cleanup_stale_leagues()  →  marca 'interrupted' → disponible para retry
```

---

## 8. `paralel_execution.py` — Motor de ejecución paralela

### Flujo completo:
```
python paralel_execution.py 3 results
    │
    ├─ get_enabled_leagues('results')     # Lee leagues_info.json
    ├─ split_into_dicts(leagues, N=3)     # Round-robin entre 3 workers
    ├─ _show_distribution()               # Muestra tabla + pide confirmación
    │
    └─ ThreadPoolExecutor(max_workers=3)
         │
         ├─ worker(0, dict_w0, 'results')
         ├─ worker(1, dict_w1, 'results')
         └─ worker(2, dict_w2, 'results')
              │
              ├─ launch_navigator()       # Abre Firefox headless
              ├─ login()
              ├─ extraction_by_dict()     # milestone4.py
              └─ retry logic (MAX=8, backoff exponencial)
```

### Estado global en paralel_execution:
```python
_file_lock     # Lock para escritura en leagues_info.json
_state_lock    # Lock para estado de workers
_worker_status # worker_id → 'running'|'done'|'error'|'retrying'
_stop_event    # señal global de parada
_pause_event   # señal global de pausa
```

### UI en terminal (Rich):
- Panel por worker con logs en tiempo real
- Intercepta prints de milestone4 via `_patched_print()`

---

## 9. Dashboard (`dashboard/app.py`)

Web UI construida con **Flet**. Corre en el servidor remoto.

```
http://<SERVER_IP>:8502
```

Funcionalidades:
- Ver status del scraper (running/stopped)
- Start/stop/pause por sección
- Ver logs en tiempo real
- Configurar ligas (enable/disable por liga)
- Stats de DB (conteos por deporte/liga)

```bash
python dashboard/app.py         # Producción
python dashboard/run_dev.py     # Dev con auto-reload (watchdog)
```

---

## 10. Scripts de utilidad (`scripts/`)

| Script | Uso frecuente |
|---|---|
| `show_running_leagues.py` | Ver qué ligas están corriendo ahora |
| `db_status.py` | Resumen completo de DB por deporte |
| `compare_rounds.py results` | Ver ligas con rounds pendientes sin procesar |
| `sync_checkpoints.py` | Subir checkpoints locales al servidor (SFTP) |
| `update_server.py py` | Deploy de archivos .py al servidor |
| `update_server.py images` | Deploy de imágenes nuevas |
| `clean_all.py` | Reset de checkpoints (CUIDADO: mayormente comentado) |
| `check_teams_match_db.py` | Sync campos teams/matches de leagues_info.json con DB |
| `stop_process.py` | Matar procesos browser/geckodriver |
| `connect_driver.py` | Reconectar a sesión Selenium activa (debug) |

---

## 11. Config y credenciales

```
config.py (NO está en git — usar config_model.py como template)
├── SERVER_HOST / SERVER_USER / SERVER_PASS / SERVER_PATH
├── DB_HOST / DB_NAME / DB_USER / DB_PASS
└── FS_EMAIL / FS_PASSWORD
```

```bash
# Virtual env
source /home/you/env/sports_env/bin/activate
```

---

## 12. Flujo de datos end-to-end

```
FlashScore.com
    │  [Selenium + Firefox headless]
    ▼
milestone*.py  (extracción + parse HTML)
    │
    ├──► check_points/*.json     (estado intermedio / resume)
    │
    └──► data_base.py
              │  [psycopg2]
              ▼
         PostgreSQL
         ├── sport
         ├── country
         ├── league + league_season
         ├── team + league_team_entity
         ├── player + team_player_entity
         ├── match + match_details + score
         ├── news
         ├── stadium
         └── running_leagues  (coordinación multi-worker)
```

---

## 13. Comandos de inicio rápido

```bash
# Activar entorno
source /home/you/env/sports_env/bin/activate

# Sistema completo
python main.py

# Solo scheduled (sin live)
python main1.py

# Manual con flags (editar flags en el archivo antes)
python main_manual_adjust.py

# Paralelo — 3 workers, sección results
python paralel_execution.py 3 results

# Paralelo — sin confirmación
python paralel_execution.py 2 fixtures --no-confirm

# Ver ligas activas en DB
python scripts/show_running_leagues.py

# Ver estado DB
python scripts/db_status.py

# Sync checkpoints al servidor
python scripts/sync_checkpoints.py

# Deploy código al servidor
python scripts/update_server.py py
```

---

## 14. Patrones de código a conocer

### Retry wrapper (milestone4):
```python
def retry_match(driver, url, fn, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return fn(driver, url)
        except RETRY_EXCEPTIONS as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(30 * (attempt + 1))  # backoff exponencial
```

### Claim/release pattern (data_base.py):
```python
if claim_league(league_id, section):
    try:
        round_, match_, status_ = get_league_checkpoint(league_id, section)
        # ... extracción ...
        update_league_checkpoint(league_id, section, current_round, current_match)
    finally:
        release_league(league_id, section, 'completed')
```

### Notebook dev setup:
```python
# Celda 1 del notebook:
%load_ext autoreload
%autoreload 2
from setup_imports import *
# Configura sys.path, os.chdir y hace todos los imports
```
