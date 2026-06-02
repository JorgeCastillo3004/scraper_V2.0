# Creación de Ligas — `milestone2.py`

Navega el árbol de FlashScore (deporte → categoría → liga → temporada) y persiste los registros en PostgreSQL. También construye el archivo maestro `leagues_info.json`.

---

## Función principal

```python
create_leagues(driver, list_sports)
```

| Parámetro | Tipo | Descripción |
|---|---|---|
| `driver` | WebDriver | Sesión Selenium activa |
| `list_sports` | list[str] | Deportes a procesar. Ej: `['FOOTBALL', 'BASKETBALL', 'BASEBALL']` |

**Checkpoint de entrada/salida:** `check_points/leagues_info.json`
**Config de entrada:** `check_points/sports_url_m2.json`, `check_points/CONFIG_M2.json`

---

## Arquitectura — Flujo principal

```
create_leagues(driver, list_sports)
│
├─ Carga archivos de entrada:
│    ├─ sports_url_m2.json    →  URLs de home por deporte
│    ├─ CONFIG_M2.json        →  modos de deporte (individual/team)
│    └─ leagues_info.json     →  ligas ya procesadas (checkpoint)
│
├─ driver.execute_script("document.body.style.zoom='50%'")
│
└─ Por cada sport_name en list_sports:
     │
     ├─ ¿Deporte existe en DB?
     │    └─ NO → create_sport_dict() + save_sport_database()
     │    └─ SÍ → usa sport_id existente
     │
     ├─ get_dict_results(table='league')
     │    └─ Dict de ligas ya en DB: {sport_id_country_id_name: league_id}
     │
     ├─ wait_update_page(driver, sports_url, "container__heading")
     │
     ├─ CASO ESPECIAL — MOTOR SPORT:
     │    ├─ find_categories_motor_sport()  →  busca F1
     │    └─ create_drivers_teams()         →  crea liga + temporada + pilotos
     │
     └─ CASO GENERAL (todos los demás deportes):
          │
          ├─ find_ligues_torneos(driver)
          │    └─ Lee panel "my-leagues-list" → {key: league_url}
          │
          └─ Por cada (league_name, league_url):
               │
               ├─ wait_update_page(driver, league_url, "container__heading")
               │
               ├─ check_pin(driver)
               │    └─ Solo procesa ligas con el PIN activo (favoritas)
               │
               ├─ get_league_data() / get_league_data_boxing()
               │    └─ Extrae: sport, country, league_name, season_name, logo
               │
               ├─ get_country_id() o insert_country()
               │    └─ Busca o crea el país en DB
               │
               ├─ ¿Liga ya en DB?
               │    └─ SÍ → usa league_id existente
               │    └─ NO → save_league_info()
               │
               ├─ ¿Temporada ya en DB?
               │    └─ SÍ → usa season_id de DB
               │    └─ NO → save_season_database()
               │
               ├─ get_sections_links(driver)
               │    └─ Extrae URLs por sección: results, fixtures, standings, draw…
               │
               └─ save_check_point('check_points/leagues_info.json', dict_sport_info)
```

---

## Funciones internas

| Función | Rol |
|---|---|
| `find_ligues_torneos` | Lee el panel de ligas favoritas del sidebar de FlashScore |
| `get_league_data` | Extrae nombre, país, temporada e imagen de la cabecera de la liga |
| `get_league_data_boxing` | Variante sin campo `league_country` (Boxing no tiene subdivisión por país) |
| `get_sections_links` | Extrae las URLs de cada tab de la liga (results, fixtures, standings…) |
| `check_pin` | Verifica si la liga tiene el pin activo (solo se procesan ligas fijadas) |
| `create_sport_dict` | Construye el dict para insertar un nuevo deporte en DB |
| `find_categories_motor_sport` | Navega el menú lateral de motorsport para encontrar F1 |
| `create_drivers_teams` | Crea liga, temporada y pilotos para deportes de motor |

---

## Estructura generada en `leagues_info.json`

```json
{
  "FOOTBALL": {
    "Argentina_Liga Profesional": {
      "league_name": "Liga Profesional",
      "url":         "https://www.flashscore.com/football/argentina/liga-profesional/",
      "league_id":   "abc123",
      "season_id":   "sea456",
      "country_id":  "ctr789",
      "results":     "https://...flashscore.com/.../results/",
      "fixtures":    "https://...flashscore.com/.../fixtures/",
      "standings":   "https://...flashscore.com/.../standings/",
      "extract_results":  { "extract": true },
      "extract_fixtures": { "extract": false }
    }
  }
}
```

> Para habilitar o deshabilitar una liga: cambiar `extract_results.extract` o `extract_fixtures.extract` a `true`/`false`.

---

## Checkpoint

`leagues_info.json` se guarda después de **cada liga procesada**. Si el proceso se interrumpe, al reiniciar se saltan automáticamente las ligas ya presentes en el JSON.

---

## Inicialización (primera ejecución)

```python
initial_settings_m2(driver)
# Crea: check_points/sports_url_m2.json  →  URLs de home por deporte
# Crea: check_points/CONFIG_M2.json      →  modo de cada deporte (team/individual)
```

---

## Llamada desde notebook

```python
create_leagues(driver, ["FOOTBALL", "BASKETBALL", "BASEBALL", "AM._FOOTBALL", "HOCKEY"])
# Deportes especiales (sin standings):
create_leagues(driver, ["AM._FOOTBALL", "HOCKEY"])
```
