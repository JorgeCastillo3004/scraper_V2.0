# Creación de Partidos — `milestone4.py`

Extrae resultados (partidos jugados) y fixtures (partidos futuros) de cada liga habilitada en FlashScore. Es el módulo más grande (~1820 líneas). Soporta ejecución secuencial y ejecución paralela con múltiples workers.

---

## Funciones principales

### Ejecución secuencial
```python
results_fixtures_extraction(driver, list_sports, name_section='results', leagues_subset=None)
```

### Ejecución paralela (usada por `paralel_execution.py`)
```python
extraction_by_dict(driver, sport_leagues_dict, name_section='results')
```

### Deportes especiales (Tennis, Golf, Boxing)
```python
extraction_special_sports_list(driver, sport_list, name_section='results')
```

| Parámetro | Descripción |
|---|---|
| `driver` | WebDriver activo |
| `list_sports` | Lista de deportes: `['FOOTBALL', 'BASKETBALL', 'BASEBALL', 'AM._FOOTBALL', 'HOCKEY']` |
| `sport_leagues_dict` | Dict sport → lista de ligas: `{'FOOTBALL': ['BRAZIL_Serie A Betano']}` |
| `name_section` | `'results'` o `'fixtures'` |
| `leagues_subset` | Opcional: lista de nombres de liga para procesar solo un subconjunto |

---

## Deportes soportados

| Grupo | Deportes | Función de extracción |
|---|---|---|
| **Principales** | FOOTBALL, BASKETBALL, BASEBALL, AM._FOOTBALL, HOCKEY | `get_complete_match_info` |
| **Especiales** | TENNIS | `get_complete_match_info_tennis` |
| **Especiales** | GOLF | `get_complete_match_info_golf` |
| **Especiales** | BOXING | `extract_info_boxing` |
| **Motor** | FORMULA 1 | `create_events_f1` |

---

## Arquitectura — `results_fixtures_extraction` (secuencial)

```
results_fixtures_extraction(driver, list_sports, name_section)
│
├─ Carga: leagues_info.json, dict_sport_id
│
└─ Por cada sport_name en list_sports (solo SUPPORTED_SPORTS):
     │
     └─ Por cada (league_name, league_info) en leagues_info[sport_name]:
          │
          ├─ ¿extract_results.extract == false? → [SKIP]
          │
          ├─ claim_league(league_id, name_section)
          │    └─ DB: marca liga como 'running' — evita colisiones
          │
          ├─ get_league_checkpoint(league_id, name_section)
          │    └─ Obtiene: cp_round, cp_match (punto de reanudación)
          │
          ├─ wait_update_page(driver, league_url, "container__heading")
          ├─ dismiss_cookies(driver)
          │
          ├─ ¿Archivos de ronda ya existen?
          │    └─ NO → navigate_through_rounds()  →  crea Round_N.json
          │
          ├─ get_complete_match_info(driver, league_info, dict_league, cp_round, cp_match)
          │    └─ Ver diagrama interno →
          │
          ├─ league_info[extract_key]['extract'] = False
          ├─ save_check_point(leagues_info.json)
          └─ release_league(league_id, name_section, status)
```

---

## Arquitectura — `extraction_by_dict` (paralelo, con reintentos)

```
extraction_by_dict(driver, sport_leagues_dict, name_section)
│
├─ Inicialización con retry (INIT_MAX_RETRIES=3, backoff 15s/30s/45s)
│    └─ get_dict_sport_id() + load_check_point(leagues_info.json)
│
└─ Por cada (sport_name, league_list):
     │
     └─ Por cada league_name:
          │
          ├─ Recarga leagues_info.json desde disco
          │    └─ Garantiza que cambios de otros workers sean visibles
          │
          ├─ ¿extract == false? → [SKIP]
          │
          ├─ claim_league()  →  [SKIP si otro worker la tiene]
          │
          ├─ Verificar sesión activa:
          │    └─ Si botón LOGIN visible → re-login automático
          │
          ├─ NIVEL A — retry navegación (LEAGUE_NAV_RETRIES=3):
          │    └─ wait_update_page() + dismiss_cookies()
          │
          ├─ NIVEL B — retry creación de rondas (LEAGUE_NAV_RETRIES=3):
          │    └─ navigate_through_rounds()  →  solo si no existen aún
          │
          ├─ NIVEL C — retry extracción (LEAGUE_MAX_RETRIES=2):
          │    └─ get_complete_match_info()
          │
          ├─ league_info[extract_key]['extract'] = False
          ├─ save_check_point()
          │
          └─ [finally] release_league()
               └─ Si falla el release: loguea pero no relanza
```

---

## Extracción por partido — `get_complete_match_info`

```
get_complete_match_info(driver, league_info, dict_league, cp_round, cp_match)
│
├─ Lee archivos Round_N.json de check_points/{section}/{PAÍS_Liga}/
│
└─ Por cada round_file:
     │
     ├─ [SKIP] Rounds anteriores al checkpoint
     │
     └─ Por cada (event_index, event_info):
          │
          ├─ [SKIP] Matches anteriores al checkpoint del round actual
          ├─ [SKIP] Si match ya está en DB: get_match_ready()
          │
          ├─ retry_match(driver, url, fn=get_match_info, max_attempts=3)
          │    ├─ wait_load_details(driver, match_url)
          │    └─ get_match_info()  →  extrae scores, estadísticas, equipos
          │
          ├─ Busca team_id_home y team_id_away en DB
          ├─ Busca/crea stadium en DB
          │
          ├─ save_math_info(event_info)
          ├─ save_details_math_info(dict_home)
          ├─ save_details_math_info(dict_visitor)
          ├─ save_score_info(dict_home)
          └─ save_score_info(dict_visitor)
               └─ update_league_checkpoint(league_id, round, match)
```

---

## Constantes de control

```python
MATCH_MAX_ATTEMPTS           = 3   # reintentos por partido
LEAGUE_MAX_RETRIES           = 2   # reintentos ante errores en get_complete_match_info
LEAGUE_NAV_RETRIES           = 3   # reintentos de navegación y creación de rondas
RETRY_BASE_DELAY             = 5   # segundos base (se multiplica por intento)
INIT_MAX_RETRIES             = 3   # reintentos para inicialización (DB/archivo)
LEAGUE_MAX_CONSECUTIVE_FAILS = 4   # warning: posible driver roto
```

---

## Checkpoint — Dos niveles

### Nivel 1 — Archivos JSON
```
check_points/
├── results/
│   └── ARGENTINA_Liga Profesional/
│       ├── Round_1.json    ← partidos de la ronda 1
│       └── Round_2.json
└── fixtures/
    └── ARGENTINA_Liga Profesional/
        └── Round_33.json
```

### Nivel 2 — Tabla `running_leagues` (PostgreSQL)
```sql
-- Columnas: league_id, section, host, started_at, status, current_round, current_match
-- Status: 'running' | 'completed' | 'interrupted'
```

El claim/release sincroniza workers en tiempo real. Las ligas con status `interrupted` son retomadas automáticamente en el siguiente ciclo de `paralel_execution.py`.

---

## Llamadas desde notebook

```python
# Extracción secuencial (deportes principales)
results_fixtures_extraction(driver, ["FOOTBALL","BASKETBALL","BASEBALL","AM._FOOTBALL"], name_section='results')

# Deportes especiales
extraction_special_sports_list(driver, ['TENNIS','GOLF'], name_section='results')

# Solo fixtures
results_fixtures_extraction(driver, ["AM._FOOTBALL"], name_section='fixtures')
```

---

## Ejecución paralela

```bash
# 3 workers, sección results
python paralel_execution.py 3 results

# 2 workers, fixtures, sin confirmación
python paralel_execution.py 2 fixtures --no-confirm
```

`paralel_execution.py` llama a `extraction_by_dict()` en cada worker con un subconjunto de ligas (round-robin desde `leagues_info.json`).
