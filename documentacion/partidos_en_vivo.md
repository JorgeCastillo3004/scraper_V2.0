# Partidos en Vivo — `milestone7.py`

Monitorea partidos en curso en FlashScore y actualiza sus scores en PostgreSQL en tiempo real.

---

## Función principal

```python
live_games(driver, list_sports, interval=60, check_control=None)
```

| Parámetro | Tipo | Descripción |
|---|---|---|
| `driver` | WebDriver | Sesión Selenium activa |
| `list_sports` | list[str] | Deportes a monitorear. Ej: `['FOOTBALL', 'BASKETBALL', 'HOCKEY']` |
| `interval` | int | Segundos entre cada ciclo de actualización (default 60) |
| `check_control` | callable | Función opcional para pause/stop externo (de `main2.py`) |

**Archivo de entrada:** `check_points/sports_url_m2.json`

---

## Arquitectura — Loop continuo

```
live_games(driver, list_sports, interval=60)
│
└─ WHILE True:
     │
     ├─ current_date = datetime.now().date()
     │
     └─ Por cada sport_name en list_sports:
          │
          ├─ wait_update_page(driver, dict_sports_url[sport_name], "container__heading")
          ├─ dismiss_cookies(driver)
          │
          ├─ give_click_on_live(driver, sport_name)   ← desde milestone8.py
          │    └─ Hace click en el botón "LIVE" de FlashScore
          │    └─ Retorna True si hay partidos en vivo, False si no hay
          │
          ├─ SI live_games_found:
          │    │
          │    ├─ get_live_match(driver, sport_name)
          │    │    └─ Lee filas del DOM con clase 'sportName {sport}'
          │    │    └─ Solo procesa filas de ligas con PIN activo (is_pinned=True)
          │    │    └─ Retorna: [{match_id, name, home, visitor, home_result,
          │    │                  visitor_result, league_name, league_country, status}]
          │    │
          │    └─ Por cada match_info en list_live_match:
          │         │
          │         ├─ get_match_id(league_country, league_name, current_date, name)
          │         │    └─ Busca el match_id en DB por fecha + nombre
          │         │
          │         ├─ SI match_id encontrado:
          │         │    ├─ get_math_details_ids(match_id)
          │         │    │    └─ {match_detail_id: is_home_flag}
          │         │    ├─ update_score({match_detail_id, points: home_result})
          │         │    ├─ update_score({match_detail_id, points: visitor_result})
          │         │    └─ update_match_status({match_id, status})
          │         │
          │         └─ SI match_id NO encontrado: continúa con el siguiente
          │
          └─ Espera hasta completar `interval` segundos:
               └─ Loop en slices de 2s, llama check_control() en cada slice
```

---

## Funciones internas

| Función | Rol |
|---|---|
| `get_live_match` | Itera las filas del DOM filtradas por deporte y PIN activo; retorna lista de partidos en vivo |
| `get_live_result` | Extrae nombre de equipos y score de una fila de partido |
| `update_status` | Lee el estado del partido (`event__stage`); retorna `'LIVE'` o `'COMPLETED'` |
| `give_click_on_live` | Hace click en el filtro "LIVE" (importado de `milestone8.py`) |

---

## Selectores clave

```python
# Contenedor de partidos por deporte
'//div[@class="sportName {sport}"]/div'

# Cabecera de liga (para detectar PIN)
'.//div[@data-testid="wcl-headerLeague"]'
data-pinned = "true"   # solo ligas fijadas se procesan

# Score
'.//*[contains(@class, "event__score--home")]'
'.//*[contains(@class, "event__score--away")]'

# Estado del partido
'.//div[@class="event__stage"]'   # "Finished" → COMPLETED, otro → LIVE

# Nombre de equipos
'.//*[contains(@class, "event__homeParticipant")]'   # Football
'.//*[contains(@class, "event__participant--home")]'  # Basketball
```

---

## Flujo de datos — Actualización en DB

```
FlashScore (DOM en vivo)
    │
    ├─ get_live_match()  →  lista de partidos detectados
    │
    └─ Por cada partido:
         ├─ get_match_id()          →  busca en DB por (country, liga, fecha, nombre)
         ├─ get_math_details_ids()  →  recupera {match_detail_id: is_home}
         ├─ update_score()          →  actualiza puntos en tabla score
         └─ update_match_status()   →  actualiza status en tabla match
                                        ('LIVE' o 'COMPLETED')
```

---

## Manejo de errores

- `InvalidSessionIdException` / `WebDriverException` → se **relanza** para que `main2.py` reinicie el driver
- Cualquier otro error por deporte → `[WARN]` y continúa con el siguiente deporte
- Cada actualización de match está en su propio try/except → un fallo no para el ciclo

---

## Llamada desde notebook

```python
# Monitoreo activo
live_games(driver, ['FOOTBALL', 'BASKETBALL', 'HOCKEY'])

# Con intervalo personalizado (120 segundos entre ciclos)
live_games(driver, ['FOOTBALL'], interval=120)
```

---

## Contexto de uso

`live_games` es ejecutada por `main2.py` en un hilo separado del scraping programado:

```python
# main.py
with ThreadPoolExecutor(max_workers=2) as executor:
    executor.submit(main1_loop)   # scraping programado
    executor.submit(main2_loop)   # live scores → live_games()
```
