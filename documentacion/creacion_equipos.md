# Creación de Equipos — `milestone3.py`

Extrae los equipos de cada liga desde la tabla de posiciones (standings) de FlashScore y los persiste en PostgreSQL. Soporta ligas con múltiples divisiones.

La extracción puede ejecutarse de dos formas:

- directa, llamando `teams_creation(driver, list_sports)`
- desde la app de control, usando `paralel_teams.py` y la pestaña **Creación de Equipos**

---

## Función principal

```python
teams_creation(driver, list_sports)
```

| Parámetro | Tipo | Descripción |
|---|---|---|
| `driver` | WebDriver | Sesión Selenium activa |
| `list_sports` | list[str] | Deportes a procesar. Ej: `['FOOTBALL', 'BASKETBALL']` |

> TENNIS y GOLF son ignorados automáticamente (son deportes individuales sin equipos en standings).

**Checkpoint de entrada/salida:** `check_points/leagues_info.json`
**Checkpoint de salida por liga:** `check_points/leagues_season/{SPORT}/{liga}.json`

---

## Flujo desde el frontend

La vista **Creación de Equipos** no envía toda la metadata de la liga desde React. El frontend solo envía la selección mínima:

```json
{
  "workers": 2,
  "sports": ["FOOTBALL"],
  "leagues": [
    { "sport": "FOOTBALL", "key": "BRAZIL_Serie A Betano" },
    { "sport": "FOOTBALL", "key": "COLOMBIA_Primera A" }
  ]
}
```

Luego la API:

```text
POST /api/teams/start
  └─ api/services/process_manager.py
       ├─ carga check_points/leagues_info.json
       ├─ arma selected_leagues_dict con las ligas elegidas
       ├─ guarda tmp/teams_selection_*.json
       └─ lanza:
          python3 paralel_teams.py <workers> --no-confirm --selection-file <path>
```

Formato del diccionario generado:

```python
{
  "FOOTBALL": {
    "BRAZIL_Serie A Betano": {
      "...": "metadata original tomada de leagues_info.json"
    }
  }
}
```

Esto evita duplicar lógica en React y hace que el proceso use exactamente la misma metadata del checkpoint maestro.

### Lógica de selección — qué se procesa y qué se salta

Cuando el proceso viene del frontend (con `--selection-file`), **la selección del usuario es la autorización**. No se aplican filtros adicionales basados en flags del checkpoint:

| Condición | Modo automático (`get_pending_leagues`) | Modo selección frontend |
|---|---|---|
| `teams_creation.extract == false` | salta la liga | **ignora el flag — procesa igual** |
| `teams == 0` en leagues_info | salta la liga | **procesa — busca en standings** |
| Liga ya completada en checkpoint | salta la liga | **procesa — puede haber equipos nuevos** |

Una vez dentro del worker, el skip ocurre **a nivel de equipo individual** (no de liga):

```text
standings scrapeado → dict_teams_availables
        │
        ├─ ya en checkpoint (leagues_season JSON)  → skip sin navegar
        ├─ ya en DB (get_teams_by_league_id)        → skip sin navegar
        └─ realmente nuevo                          → navegar + scrape + insert
```

Una sola consulta a DB por liga (no por equipo) obtiene todos los equipos existentes. Solo se navega y extrae información de equipos verdaderamente nuevos.

---

## Vista frontend: qué muestra

La sección **Creación de Equipos** del frontend usa `/api/leagues` y `/api/leagues/sports`.

Columnas y métricas principales:

| Campo UI | Fuente |
|---|---|
| `Equipos DB` | conteo real en la DB remota |
| `Esperados` | `league_info["teams"]` en `leagues_info.json` |
| `Results / Fixtures` | conteos reales en DB (`match.status`) |
| `Estado checkpoint` | `teams_creation.status` |
| `Último equipo` | `teams_creation.last_team_created` |

Funciones disponibles en la vista:

- filtro por deporte usando deportes reales de la tabla `sport` en DB
- toggle ON/OFF por liga sobre `teams_creation.extract`
- selección múltiple de ligas
- filtro opcional por pocos equipos en DB: `teams_db <= threshold`
- resumen agregado de ligas habilitadas, pendientes, equipos DB y esperados
- panel de screenshots por worker

---

## Screenshots del proceso

`paralel_teams.py` guarda capturas por worker durante la extracción.

Ubicación:

```text
logs/screenshots/teams/
├─ latest/
│  ├─ worker_0.png
│  ├─ worker_0.json
│  ├─ worker_1.png
│  └─ worker_1.json
└─ history/
   └─ worker_<id>_<timestamp>_<label>.png
```

Uso:

- `latest/` mantiene la última captura visible por worker
- `history/` guarda hitos y errores para depuración

Momentos típicos de captura:

- driver listo
- antes de abrir standings
- standings cargado
- página de equipo
- liga completada
- error/reintento

API relacionada:

```text
GET /api/teams/screenshots
```

El frontend consulta ese endpoint por polling y muestra la última captura de cada worker en la vista `Equipos`.

En servidor no hace falta ver el navegador en pantalla: las capturas siguen funcionando aunque el driver vaya en headless.

---

## Arquitectura — Flujo principal

```
teams_creation(driver, list_sports)
│
├─ Carga leagues_info.json
├─ get_dict_sport_id()  →  mapeo sport_name → sport_id en DB
│
└─ Por cada sport_name en list_sports:
     │
     ├─ [SKIP] Si TENNIS o GOLF → continuar
     │
     └─ Por cada (country_league, league_info) en leagues_info[sport_name]:
          │
          ├─ ¿teams_creation.extract == false? → [SKIP]
          │
          ├─ resume_team = league_cp.get('last_team_created', '')
          │    └─ Si existe: saltar equipos hasta llegar al checkpoint
          │
          ├─ Sincronizar season_id desde DB
          │    └─ get_season_id_by_league(league_id)
          │
          ├─ url = league_info['standings'] o league_info['draw']
          │
          ├─ get_all_teams_from_standings(driver, url)
          │    │
          │    ├─ driver.get(standings_url)
          │    ├─ WebDriverWait(120s).until(rows_have_text)
          │    │
          │    ├─ ¿Hay tabs de división? (wcl-tabs data-type="secondary")
          │    │    ├─ SÍ → Por cada división:
          │    │    │        ├─ driver.get(href_division)
          │    │    │        ├─ WebDriverWait(120s).until(rows_have_text)
          │    │    │        └─ get_teams_info_part1()  →  acumula sin duplicar por team_url
          │    │    └─ NO → get_teams_info_part1()  →  extrae directamente
          │    │
          │    └─ Retorna: { team_name: {team_url, statistics, position, last_results} }
          │
          └─ Por cada (team_name, team_info_url):
               │
               ├─ [RESUME] Saltar si aún no llegamos al checkpoint
               │
               ├─ wait_update_page(driver, team_url, 'heading')
               ├─ get_teams_info_part2()
               │    └─ Extrae: team_country, team_name, stadium, logo_url
               │
               ├─ get_country_id() o insert_country()
               │
               ├─ create_team_in_db(dict_teams_db, sport_id, dict_team)
               │    ├─ ¿Equipo en caché memoria? → usa team_id
               │    ├─ ¿Equipo en DB? → usa team_id + crea league_team_entity si falta
               │    └─ ¿Equipo nuevo? → save_team_info() + save_league_team_entity()
               │
               ├─ Actualizar checkpoint: league_cp['last_team_created'] = team_name
               └─ save_check_point(leagues_info.json)
```

### Variante paralela usada por la app

```text
Frontend Equipos
  └─ POST /api/teams/start
       └─ process_manager.build_command()
            └─ python3 paralel_teams.py N --selection-file tmp/teams_selection_*.json
                 └─ run_parallel_teams()
                      ├─ split_into_workers()
                      ├─ worker_0 ... worker_N
                      └─ _teams_creation_worker()
                           └─ milestone3 helpers
```

---

## Funciones internas

| Función | Rol |
|---|---|
| `get_all_teams_from_standings` | Wrapper que maneja ligas con divisiones múltiples |
| `get_links_divisiones` | Detecta y retorna los hrefs de tabs de división |
| `get_teams_info_part1` | Extrae equipos de la tabla visible actual (selectores `ui-table__row`) |
| `get_teams_info_part2` | Navega a la página del equipo y extrae nombre, país, estadio, logo |
| `rows_have_text` | Condición de espera: verifica que las filas de la tabla tienen texto cargado |
| `create_team_in_db` | Busca en caché → busca en DB → crea si no existe; retorna `team_id` |
| `add_league_info` | Inyecta `sport_name`, `sport_id`, `league_name` en `league_info` |

---

## Selectores clave

```python
# Tabla de posiciones
'ui-table__row'                          # fila de equipo
'.//div[@class="tableCellParticipant"]'  # nombre del equipo (OBSOLETO — ver nota)
'.//div[@class="tableCellRank"]'         # posición
'.//a[@class="tableCellParticipant__name"]'  # link al equipo

# Divisiones (ligas con grupos)
'//div[@data-testid="wcl-tabs" and @data-type="secondary"]/a'

# Cabecera del equipo
'container__heading'
'.//h2[@class="breadcrumb"]/a[2]'        # país
'heading__title'                          # nombre
'heading__info'                           # estadio
'.//div[@class="heading"]/img'            # logo
```

> **Nota:** El selector `tableCellParticipant` puede fallar en algunas ligas (error visible en notebook).
> `get_all_teams_from_standings` maneja el fallback con un try/except.

---

## Checkpoint

```
check_points/
├── leagues_info.json
│     "teams_creation": {
│       "extract": true,
│       "last_team_created": "Club Brugge KV",  ← punto de reanudación
│       "status": "completed"
│     }
│
└── leagues_season/
      └── FOOTBALL/
            └── BELGIUM_Jupiler Pro League.json
                  { "Club Brugge KV": { "team_id": "...", "team_url": "..." }, ... }
```

`status = completed` indica que la liga terminó en el checkpoint.

`last_team_created` permite reanudar si el proceso se corta.

`teams` representa la cantidad esperada de equipos y es el valor que se muestra como `Esperados` en la UI.

---

## Llamada desde notebook

```python
# Todos los equipos de un deporte
teams_creation(driver, ["FOOTBALL"])

# Probar extracción de una liga específica
standings_url = 'https://www.flashscore.com/football/belgium/jupiler-pro-league/standings/'
get_all_teams_from_standings(driver, standings_url)
```
