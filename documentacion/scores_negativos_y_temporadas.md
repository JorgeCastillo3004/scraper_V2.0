# RUNBOOK — Partidos con score -1 (proceso recurrente)

> Proceso que se ejecuta **periódicamente** para limpiar `score_entity.points = -1`
> (score no capturado) en partidos PASADOS. Metodología + scripts. Autoridad de
> reglas: `CLAUDE.md` (solo INSERT/UPDATE; DELETE con OK explícito por caso).
> Última corrida completa: 2026-06-16 (225 pasados → 0).

---

## 0. TL;DR del flujo

1. **Detectar** los pasados con -1 y agruparlos por liga.
2. **Verificar la temporada contra FlashScore** (nombre en `.heading__info`, NO el `season_id`).
3. **Clasificar** y tratar:
   - Temporada **VIEJA** → etiquetar `status='OLD_SEASON'` + score **0-0**.
   - Temporada **ACTUAL** y el partido **aparece en FlashScore con score** → completar.
   - **No aparece en FlashScore** (results ni fixtures) → fantasma → borrar (con OK).
   - **Aparece en OTRO deporte** (liga homónima) → cross-deporte → borrar el espurio (con OK).

---

## 1. Detección (read-only)

`points = -1` = score nunca capturado. Ojo: los **SCHEDULED futuros** con -1 son legítimos
(aún no se juegan). El problema son los **PASADOS** (`match_date < CURRENT_DATE`).

Query base por liga:
```sql
SELECT s.name, l.league_name, count(DISTINCT m.match_id)
FROM match m
JOIN match_detail md ON md.match_id=m.match_id
JOIN score_entity se ON se.match_detail_id=md.match_detail_id
LEFT JOIN league l ON l.league_id=m.league_id
LEFT JOIN sport  s ON s.sport_id=l.sport_id
WHERE se.points=-1 AND m.match_date < CURRENT_DATE
GROUP BY 1,2 ORDER BY 3 DESC;
```

---

## 2. Verificación FIABLE de temporada (clave)

⚠️ **NO** comparar `match.season_id` con `leagues_info.season_id`: esos campos están sucios
(~137 `season` con `start=end`, huérfanas, season_id de leagues_info a veces viejo). Dio
falsos (Bolivia clasificada "actual" pero los partidos no estaban en FlashScore).

**Método correcto** (reusa `milestone2.get_league_data`): abrir el link de la liga en
FlashScore y leer el nombre de temporada de **`.heading__info`** (dentro de `.container__heading`).
Comparar con el `season_name` de la DB de esos partidos.

Script: **`scripts/_debug_verify_seasons_flashscore.py`** (lee `tmp/_affected_leagues.json`,
que se arma con una query como la de §1 + el league_id/season_name/results_url por liga).

Resultados posibles por partido:
- nombre DB **==** nombre FlashScore → **ACTUAL** (ver §4.2).
- nombre DB **!=** FlashScore → **VIEJA** (ver §4.1). El resultado viejo suele estar en el
  **archivo** `…/{liga}-{AÑO}/results/` (ej. Brasil `serie-a-betano-2025`), que NO se persigue.
- el partido **no aparece** en results ni fixtures → fantasma/cross-deporte (§4.3 / §4.4).

---

## 3. Causa raíz de los fantasmas (corregida)

`get_match_id`/resolución de liga matcheaba por `country_name`+`league_name` **sin deporte**.
Ligas homónimas en deportes distintos colisionan: **WORLD 'World Cup'** existe en fútbol Y
básquet; **TURKEY 'Super Lig'** en fútbol Y básquet. Por eso 64 clasificatorios FIBA Basketball
quedaron creados bajo la liga de **fútbol** con score -1.

**Hardening (2026-06-16):** todo lookup debe filtrar por deporte.
- `get_match_id(..., sport=)` — si `sport=None` imprime **cuadro rojo** y sigue.
- LIVE (`milestone7`, `live_function`) pasa el deporte y **saltea + cuadro rojo** si no resuelve.
- Helper **`common_functions.red_box_warning(title, lines)`** = caja ANSI roja "NO DEBERIA
  OCURRIR NUNCA" que **no detiene** el proceso. Si aparece en logs → hay un caller a corregir.
- `get_match_by_league_name`/`get_match_update` marcadas DEPRECATED (resuelven sin país/deporte).

---

## 4. Tratamiento por categoría

### 4.1 Temporada VIEJA → etiquetar + 0-0
- **`scripts/label_old_season_matches.py [--apply]`** → `UPDATE match SET status='OLD_SEASON'`
  (status es **varchar(17)**, label corto). Reversible y consultable; los saca de pendientes.
- Luego poner **0-0** (para que dejen de figurar como -1):
  `UPDATE score_entity SET points=0 WHERE points=-1 AND match_detail_id IN (detalles de OLD_SEASON)`.

### 4.2 Temporada ACTUAL → completar desde FlashScore
- **`scripts/update_pending_matches.py --league "SPORT/KEY" --mode rapido --apply`**
  (escanea la URL actual, `update_score` + `status=COMPLETED`). Dry-run sin `--apply`.
- Varias ligas en cadena: **`scripts/_chain_complete_current.sh`** (umbral reciclaje driver
  `DRIVER_MEM_LIMIT_MB`, default 3072).
- Si la **temporada nueva** no está en DB → **`crear_fixtures_ligas.py --sport X --leagues "KEY" --apply`**
  (lee `.heading__info`, crea season si falta, equipos + `league_team` + partidos, anti-duplicado).
- Si "no encontrados" en la URL actual → el partido NO está ahí (ir a §4.3/§4.4, NO inventar).

### 4.3 Fantasma (no existe en FlashScore) → borrar (con OK)
Confirmar en results **y** fixtures de la liga que el matchup **no aparece**. Si la liga está
en receso (sin results recientes ni fixtures) y hay señales de artefacto (matchups duplicados
en días consecutivos, partidos atascados en LIVE sin hora), son fantasma. Borrar (FK: score_entity
→ match_detail → match). El live los re-crea por DB-SKIP si fueran reales y se republican.

### 4.4 Cross-deporte (liga homónima) → borrar el espurio (con OK)
Comparar el matchup en el link de **cada deporte** (ej. `football/world/world-championship`
vs `basketball/world/world-cup`). Si aparece SOLO en otro deporte con score real → la copia de
este deporte es espuria. Verificar con `scripts/_debug_wc_football_vs_basket.py`. Borrar la espuria.

> Cualquier DELETE: mostrar exactamente qué se borra y pedir OK por caso (regla del proyecto).

---

## 5. Scripts del proceso

| Script | Rol |
|---|---|
| `_debug_verify_seasons_flashscore.py` | **Verificación temporada DB vs FlashScore** (`.heading__info`) por liga |
| `label_old_season_matches.py` | Etiqueta temporadas viejas `status='OLD_SEASON'` (dry-run/`--apply`) |
| `update_pending_matches.py` | Completa score+status de los ACTUALES (modos rapido/completo/solo-sin-stats) |
| `_chain_complete_current.sh` | Cadena de `update_pending_matches --apply` por liga (umbral driver 3072) |
| `crear_fixtures_ligas.py` | Crea season nueva + equipos + league_team + partidos (anti-duplicado) |
| `_debug_wc_football_vs_basket.py` | Compara un matchup entre links de distintos deportes |
| `_debug_brasil_2025_archive.py` | Confirma que un resultado viejo está en el archivo `{liga}-{año}` |
| `_debug_bolivia_21.py` / `_debug_bolivia_seasons.py` | Verifica si los partidos existen en results/fixtures |
| `_debug_null_team_baseline.py` | Auditoría read-only de inconsistencias (NULL/season/FK) |

## 6. Resultado 2026-06-16 (referencia)
225 pasados con -1 → **0**: 69 viejas etiquetadas+0-0; ~71 actuales completadas; 64 fantasmas
básquet borrados (cross-deporte); 21 Bolivia borrados (fantasma/receso). Causa raíz (filtro de
deporte) corregida con cuadros rojos. **Stats backfill** (partidos sin `statistic`) queda aparte
(`update_pending_matches --solo-sin-stats`), lo ejecuta Jorge cuando corresponda.
