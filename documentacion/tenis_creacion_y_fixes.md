# Tenis — creación de partidos: diagnóstico, fixes y pruebas

**Fecha:** 2026-06-26. Contexto: el live (`main2.py`) detectaba partidos de tenis en
vivo (Wimbledon) pero los descartaba con `[DB-SKIP] Partido NO EXISTENTE en la BD`
(≈71% de todos los DB-SKIP eran tenis). Causa: el live **solo actualiza**; los
partidos de tenis **nunca se creaban**.

---

## 1. Arquitectura (creación vs live) — por qué fallaba

Dos responsabilidades **separadas**, con **drivers/procesos distintos**:

- **Creación** (results/fixtures → BD): inserta `match`, `match_detail`, `team`,
  `player`, `score_entity`, `league_team`. Driver propio (corrección / prueba).
- **Live** (`main2.py`, cada 120s): mira los partidos en vivo y por cada uno hace
  `get_match_id` para **encontrar el partido YA existente** y actualizar score+status.
  **No crea.** Si no existe → `[DB-SKIP]`. Driver propio (`tmp/live_driver.json`).

```
CREACIÓN (driver propio)   → inserta el partido en la BD
        ↓
LIVE (driver propio, 120s) → encuentra ese partido y le actualiza el score
```

Football ya funciona así. Tenis daba 100% `[DB-SKIP]` porque la creación nunca corría
para tenis: en `check_points/leagues_info.json` las 11 ligas de tenis tienen
`extract_results=False` y `extract_fixtures=False`, no hay checkpoints (solo
`WTA_French_Open` viejo), y `crear_fixtures_ligas.py` **no contempla tenis** (busca
`/team/`, pero tenis usa `/player/`). El flujo de creación de tenis existe en
`milestone4.get_complete_match_info_tennis` (usa `save_team_player_single/doubles`).

**Nombres:** `match.name` se arma con nombres CORTOS ('Rus A.~Podrez V.') en
`milestone4.get_result` (línea ~134), el MISMO formato que usa el live
(`milestone7` línea ~36). Por lo tanto, una vez creados, **el live SÍ los encuentra**
(no hay desajuste de nombres; descartada esa hipótesis).

---

## 2. Fixes aplicados (código)

| # | Archivo / símbolo | Problema | Cambio |
|---|---|---|---|
| 1 | `src/milestone6.py` `get_player_data_tennis` | Foto: `img[@loading="eager"]` fallaba intermitentemente (el atributo se asienta tarde) → `NoSuchElementException` sin try/except → **tumbaba la creación del partido**. | Selector estable `img.heading__logo` + `WebDriverWait` 5s + fallback `player_photo=''`. |
| 2 | `src/milestone4.py` `save_team_player_doubles` | Nunca seteaba `country_id` → KeyError en INSERT de player/team. Además solo enlazaba al **último** jugador en `team_players_entity`. | Resuelve `country_id` (como singles) y crea una fila `team_players_entity` por **cada** jugador de la pareja. |
| 3 | `src/milestone4.py` `get_complete_match_info_tennis` | `score_entity.points` (columna `double`) recibía str ('0','2'). | `points → float` con respaldo `-1.0`. |
| 5 | `src/milestone6.py` `get_player_data_tennis` | DOB: chequeaba `'age'` (minúscula) pero la clave es `'Age'` → **TODOS** los jugadores quedaban con `1900-01-01`. | Búsqueda case-insensitive de la clave + parseo defensivo de la fecha entre paréntesis. |
| 4 | `src/common_functions.py` `launch_navigator` + `scripts/start_driver.py` | Un driver `lightweight` NO carga imágenes (`permissions.default.image=2`), pero la creación necesita descargar fotos/logos. | Nuevo parámetro **`load_images`** / flag **`--load-images`**: fuerza la carga de imágenes aunque sea lightweight. |

### Gotcha de `sport_id` (NO es bug del código real, sí del harness)
La FK `team.sport_id → sport.sport_id` exige el **UUID** del deporte, no el string.
En la tabla `sport`, tenis es name `'Tennis'` con `sport_id =
31ddfbbd-5141-4b13-87bc-993552727af8`. Al construir `league_info` para crear:
- `sport_name='TENNIS'` (project UPPER) → usado para el branch en
  `save_team_player_single` y rutas de checkpoints.
- `sport_id` = UUID real, resuelto con `data_base.get_dict_sport_id()['Tennis']`
  (NO hardcodear `'TENNIS'`).

---

## 3. Pruebas (en seco, sin escribir) + 1 escritura verificada

Herramientas `_debug_` creadas (scratchpad, read-only salvo la de escritura):
- `scripts/_debug_tennis_schema.py` — introspección read-only del esquema (campos
  obligatorios/tipos/longitudes).
- `scripts/_debug_tennis_dryrun.py` — arma los dicts del flujo real y valida contra
  el esquema, sin escribir (saves bloqueados + BD readonly + `save_image` stub).
- `scripts/_debug_tennis_robust.py` — corre el flujo sobre MUCHOS partidos/jugadores
  de varias ligas y cuenta fallos. Args: `[target] [results|fixtures|both] [filtro_liga]`.
- `scripts/_debug_tennis_write_one.py` — crea **1** partido real (camino real).
- `scripts/_debug_tennis_verify.py` — verifica read-only todas las tablas del partido.

**Resultados:**
- Robustez: **61 partidos / 122 jugadores / 3 ligas (AUS Open, Wimbledon, WTA Wimb.)
  → 0 fallos de datos.** `no_photo=0` (fix #1 100%); `no_dob` pasó de 60→0 (fix #5).
- Escritura real: 1 partido `Bolkvadze M.~Kinoshita H.` (WTA Wimbledon), verificadas
  las 7 tablas (FK `sport_id` OK, `points` numéricos, formatos/longitudes OK).
- 1 escritura parcial del 1er intento (player huérfano por el bug de `sport_id`) fue
  **limpiada** con aprobación explícita (`_debug_cleanup_orphan_player.py`, DELETE por
  ID exacto previa verificación de no-referencia).

### Límite operativo hallado (NO es fallo por-partido)
Con `--load-images`, el Firefox del driver **acumula memoria** en corridas largas; en
el 3er lote (French Open) el SO lo mató (OOM) y la corrida se colgó. **Una corrida de
creación masiva de tenis necesita el mismo reciclaje de driver por memoria que el live**
(`DRIVER_MEM_LIMIT_MB` / hot-swap). Ver [[feedback_driver_hotswap]].

---

## 4. Pendiente (próximos cambios)

1. **Cablear la creación de tenis al flujo** para que cree los partidos de hoy/próximos
   de las ligas en vivo (Wimbledon): rama TENNIS en el creador (usar
   `get_links_participants` + `save_team_player_single/doubles`, NO `get_team_links_from_match`),
   construyendo `league_info` con `get_dict_sport_id()` para el `sport_id` UUID.
2. **Reciclaje de driver por memoria** en la corrida de creación con imágenes.
3. **Dobles (fix #2):** corregido en código pero **no probado en vivo** (no hay liga de
   dobles registrada en `leagues_info.json`, todas son singles).

Reglas vigentes: jamás pkill/quit firefox sin confirmación; solo INSERT/UPDATE (DELETE
caso por caso con aprobación). Ver `CLAUDE.md` y [[project_scraper_panel]].
