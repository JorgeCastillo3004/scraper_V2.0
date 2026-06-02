# Sesión — Creación de fixtures faltantes + scripts de mantenimiento

Fecha: 2026-05-30. Objetivo central: para las **ligas pineadas** que no tienen
partidos creados, **crear los fixtures** (navegando la sección *fixtures*),
**creando los equipos** que falten (desde el link de cada match), el **estadio**
y el **partido** completo. En el camino se corrigieron varios bugs de datos.

---

## Índice de scripts (esta sesión)

| Script | Descripción corta |
|---|---|
| [`crear_fixtures_ligas.py`](../crear_fixtures_ligas.py) | **Principal.** Crea fixtures faltantes de ligas pineadas: navega *fixtures* → entra a cada match → crea equipos + estadio + season (si falta) + match/detail/score. Flags: `--apply` (escribe; default dry-run), `--stop-after-first-team` (prueba), **`--from-pin`** (detecta solo ligas con partidos de HOY faltantes en DB; reusa driver o lanza `start_driver.py` con login), **`--rescan`** (re-escanea y mergea fixtures nuevos al checkpoint). **Checkpoint** por liga en `check_points/fixtures_progress/{SPORT}/{league_key}.json` (lista de matches + cursor `done`/`last_index` → retoma sin re-procesar). Ligas detectadas faltantes pero sin entrada/fixtures en `leagues_info` NO se ignoran: advertencia fuerte `‼ [INCOMPLETO]` + se persisten en `_PENDIENTES_COMPLETAR_{SPORT}.json`. Log en `logs/crear_fixtures_*.log` (incluye `url=` del match). |
| [`completado_de_ligas.py`](../completado_de_ligas.py) | Crea **solo las ligas pineadas faltantes** en DB. Reusa `milestone2.create_leagues` (entra a cada liga, verifica en DB, crea si falta). Default = lista estándar de deportes; `--sports` para acotar. FORMULA 1 solo asegura la liga. |
| [`scripts/pin_leagues_match_count.py`](../scripts/pin_leagues_match_count.py) | **Read-only.** Cuenta partidos en DB (total + hoy) por cada liga pineada (vista ALL). Escribe `logs/pin_match_count_*.log` con deporte/país/liga. |
| [`scripts/show_matches_db.py`](../scripts/show_matches_db.py) | **Read-only.** Lista partidos en DB agrupados por deporte → liga. Default = hoy; acepta fecha o rango. |
| [`scripts/_debug_seasons_check.py`](../scripts/_debug_seasons_check.py) | **Read-only.** Diagnóstico: por deporte, cuántas ligas tienen/no tienen `season` asociada + formato de `season_name`. |
| [`scripts/_debug_pin_check.py`](../scripts/_debug_pin_check.py) | **Debug.** En el driver vivo, lista partidos de ligas pineadas (vista ALL) y verifica contra DB con `get_match_id` (mismos campos que el flujo live). |
| [`scripts/_debug_pin_insert_dryrun.py`](../scripts/_debug_pin_insert_dryrun.py) | **Debug.** Dry-run de qué se insertaría por cada partido pineado faltante. Contiene `resolve_league_id` (league_id por país+nombre) y `strip_phase_suffix`, reutilizados por otros scripts. |
| [`scripts/_debug_match_info.py`](../scripts/_debug_match_info.py) | **Debug.** Inspecciona la página de un match (read-only) para ubicar selectores (usado para hallar el bloque de estadio). |

---

## Hallazgos y correcciones de fondo (afectan al pipeline general)

1. **Nombre de deporte DB vs proyecto.** La tabla `sport` guarda Title Case
   (`Football`) pero el proyecto referencia UPPER (`FOOTBALL`). `milestone2.create_leagues`
   no mapeaba y creaba un **deporte duplicado** (`FOOTBALL` además de `Football`).
   - Fix: aplicar `check_points/sport_name_map.json` (igual que milestone3).
   - Limpieza: se borró el `sport` `FOOTBALL` duplicado + sus 13 ligas + 13 seasons
     (todas duplicadas, 0 matches). Quedó un solo `Football` (49 ligas).

2. **Sufijo de fase en el DOM.** FlashScore pega la fase al título de la liga
   (`Liga 1 - Apertura`, `Champions League - Play Offs`); la DB guarda el nombre
   base (`Liga 1`). El match exacto fallaba → falsos "no encontrada".
   - Fix: `strip_phase_suffix()` (recorta tras el primer `" - "`) — centralizado
     en `data_base.get_match_id` (beneficia también al flujo LIVE de milestone7/
     live_function) y usado en `resolve_league_id`. Seguro: ninguna liga real
     tiene `" - "` en su nombre.
   - `get_match_id` ahora imprime los campos exactos usados en la consulta.

3. **`leagues_info.json` con `league_id` desactualizado.** Para varias ligas el
   `league_id` del JSON **no existe** en la tabla `league` → `ForeignKeyViolation`
   al crear season/match. Fix: `crear_fixtures_ligas.py` resuelve el **league_id
   real** desde la DB (`resolve_league_id` por país+nombre) e ignora el del JSON.

4. **Estadio en bloque nuevo (lazy-load).** El estadio está en
   `[data-testid="wcl-summaryMatchInformation"]` → pares `wcl-infoLabel_` /
   `wcl-infoValue` (`Venue:` / `Capacity:`). Los selectores viejos
   (`matchInfoData`, `summaryMatchInformation/div`) ya no aplican.
   - Fix en `ensure_match_stadium` (de `crear_fixtures_ligas.py`): selector con
     guion bajo `wcl-infoLabel_` (evita el doble match wrapper+span que metía la
     capacidad como nombre) + **scroll a la sección + WebDriverWait + reintentos**
     (la sección carga lazy). Crea el stadium si no existe, lo reusa si existe.

5. **`ensure_team_created` (fix_null_team_ids.py)**: se le agregó el parámetro
   retrocompatible `stadium_out` y un print `[TEAM FIELDS]` de los campos del
   equipo a insertar (verificación).

---

## Estrategia de `crear_fixtures_ligas.py` (flujo)

```
por cada liga pineada (clave 'PAIS_Liga' en leagues_info.json):
  resolver league_id REAL en DB (resolve_league_id país+nombre)  ← evita FK por JSON viejo
  navegar URL de FIXTURES
  ensure_season: season_name del encabezado; si no existe en DB → crear (save_season_database)
  scan_fixtures_page: get_result(row,'fixtures') → {name 'home~visitor', fecha, match_url}
  por cada fixture:
    detectar país del match (fallback al de la liga)
    ensure_match_stadium (scroll+wait → wcl-summaryMatchInformation) → crear/reusar
    get_team_links_from_match → ensure_team_created(home/away)  (crea equipo+league_team)
    check_match_duplicate (league_id, fecha, name)  → si existe, skip
    save_math_info (status=SCHEDULED) + match_detail (home/visitor) + score (points=-1)
```

Reusa bloques ya probados: `fix_null_team_ids` (driver vivo, team links, creación
de equipo), `milestone4.get_result`/`get_time_date_format`, `data_base.*`.

---

## Estado FINAL de la sesión (2026-05-31)

- **9 ligas FOOTBALL extraídas** (status SCHEDULED), **545 matches**, todos con
  **2 `match_detail`**, season y país (integridad verificada en DB):
  VENEZUELA 4, BOLIVIA 34, BRAZIL 113, CHILE 133, CHINA 122, ECUADOR 116,
  EUROPE Champions League 1, PERU 8, URUGUAY 14.
- **Estadios**: ~100% salvo BRAZIL (87/113 — fixtures futuros sin VENUE en la página).
- **Fixes de fondo aplicados** (ver sección arriba): naming deporte, sufijo de
  fase, `league_id` viejo en JSON (se resuelve real desde DB), estadio en
  `wcl-summaryMatchInformation` (scroll+wait), **apóstrofe** (parametrizado
  `get_stadium_id`/`get_list_id_teams`/`check_team_duplicates`), **timing de
  fixtures** (`scan_fixtures_page` espera filas + reintenta), expand "show more"
  hasta que no crezca, **checkpoint** idempotente, **`--from-pin`**.

## Pendientes para la próxima sesión
- Hoja de ruta de organización del proyecto: **[organizacion_proyecto.md](organizacion_proyecto.md)**
  (empezar por inventario/renombrado de scripts + script de integridad de DB).
- `EUROPE / Champions League`: 3 filas duplicadas en `league` (preexistente) → consolidar.
- `BRAZIL`: 26 fixtures sin estadio (reintentar con más wait, o aceptar).
- Revisar `check_points/fixtures_progress/_PENDIENTES_COMPLETAR_*.json` si aparece
  (ligas con faltantes sin entrada en `leagues_info` → crear con `completado_de_ligas.py`).
- Agregar `page_load_timeout` + reintento a los scripts con driver (evitar cuelgues como el visto).
- Metodología de trabajo: **[metodologia_desarrollo.md](metodologia_desarrollo.md)**.
