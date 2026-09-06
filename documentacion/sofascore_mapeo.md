# Mapeo SofaScore ↔ base de datos

> **Para qué:** tener un **sitio web de respaldo** del Live por si FlashScore falla —cae,
> cambia su HTML o bloquea al scraper—. El respaldo escribe en la **misma `sports_db`,
> sin cambiar una sola tabla**: lo único que hace falta es traducir los nombres para
> localizar el partido correcto. Esa traducción vive en estos archivos.
>
> **La base de datos no se toca.** El mapeo solo sirve para BUSCAR bien; una vez
> localizado el partido, la escritura pasa por las funciones de siempre
> (`get_match_id`, `update_score`, `update_match_status`).

---

## Los tres archivos, por orden de autoridad

| Archivo | Qué guarda | Quién lo escribe |
|---|---|---|
| `check_points/sofascore_overrides.json` | **Correcciones manuales. Mandan sobre todo.** | a mano |
| `check_points/sofascore_map.json` | liga de la BD → torneo de SofaScore (`unique_id`) | `build_sofascore_map.py` |
| `check_points/sofascore_teams_map.json` | equipo de SofaScore → equipo de la BD, por liga | `build_sofascore_teams_map.py` |

Se consultan en ese orden: si hay corrección manual, se usa y no se pregunta más.

## Cómo se generan

```bash
./scripts/start_sofascore.sh                     # driver visible, se queda abierto

sports_env/bin/python scripts/build_sofascore_map.py       --deporte Football --dias 4
sports_env/bin/python scripts/build_sofascore_teams_map.py --deporte Football --dias 7
sports_env/bin/python scripts/validar_sofascore.py         --deporte Football --dias 4
```

Para un deporte **fuera de temporada** se valida contra sus últimas jornadas con
`--desde`: `--deporte Basketball --desde 2026-06-25 --dias 11`.

## Cómo se elige el torneo (y por qué así)

1. **Nombre exacto** dentro del mismo país.
2. **Parcial**, incluso sin espacios: la BD dice `Liga Pro` y SofaScore `LigaPro Serie A`.
3. **Tokens compartidos**: `Serie A Betano` ↔ `Brasileirão Betano` comparten *betano*.
4. **Verificación por equipos** — y esta manda sobre las tres anteriores: se piden los
   partidos del torneo candidato y se comprueba que sus equipos son los de la BD. Si no
   coinciden, no es el torneo por mucho que se llame igual.

Tres reglas que salieron de errores reales, no de la teoría:

- **Filtrar por deporte.** El buscador de SofaScore mezcla deportes: sin filtro, el
  `World Cup` de baloncesto se emparejó con el **FIFA World Cup de fútbol**.
- **Penalizar variantes**: `U17`, `Women`, `Qual.`, `Youth`… `EuroBasket` se estaba
  emparejando con `FIBA U17 Basketball World Cup`.
- **El nombre de la BD puede ser impreciso.** Lo que la BD llama `WORLD/World Cup` de
  baloncesto es en realidad la `FIBA World Cup Qualification, Europe` — se descubrió
  porque los equipos coincidían (30 de 32) y el nombre no. Está fijado en los overrides.

## Cómo se localiza cada partido

1. Nombre exacto de los dos equipos (ya traducidos con el mapa).
2. **Fecha + hora**, cuando la hora es real.
3. **Similitud por tokens con prefijos** (`atl` ⊂ `atletico`), exigiendo que peguen los
   **dos** equipos y que el mejor candidato saque ventaja al segundo. Ante empate **no se
   empareja**: es preferible perder un partido a escribir el marcador en otro.

Dos trampas que hay que respetar:

- **La fecha manda.** Pedir una fecha a SofaScore devuelve también días contiguos: NPB
  pedido el día 8 devuelve 12 partidos = los 6 del 8 más los 6 del 9. Y en béisbol el
  mismo enfrentamiento se repite tres días seguidos (una serie), con marcadores
  distintos. Se filtra por la fecha real del evento y solo se recurre a los días
  contiguos si ese día no hay nada.
- **La hora solo vale si es real.** Los partidos `SCHEDULED` de la BD tienen hora
  placeholder (toda la jornada con el mismo `start_time`); solo los que el live ya tocó
  tienen hora buena, y ahí coincide al minuto con SofaScore.

## Estado (2026-09-06)

| Deporte | Ligas | Equipos | Validación |
|---|---:|---:|---|
| Football | 5 | 86 | 37/40 (92 %) |
| Baseball | 2 | 22 | **23/23 (100 %)** |
| American Football | 2 | 41 | **24/24 (100 %)** |
| Basketball | 2 | 38 | 26/28 (93 %) |
| Hockey | 1 | 15 | **29/29 (100 %)** |
| **TOTAL** | **12** | **202** | **139/144 (97 %)** |

Lo que no cruza no es un fallo del emparejador: son partidos **reprogramados** (la BD
tiene `Llaneros~Dep. Cali` el 6-sep y SofaScore el 8-sep). El respaldo, además de cubrir
caídas, sirve para **detectarlos**.

Sin cubrir todavía: Tennis (fuera de temporada, y su estructura es por ATP/WTA, no por
país), Boxing y Motor Sport (sin actividad en la BD).

## Corregir un mapeo a mano

Editar `check_points/sofascore_overrides.json`:

```json
{
  "leagues": { "Basketball": { "WORLD_World Cup": { "unique_id": 10437, "nota": "..." } } },
  "teams":   { "Football":   { "COLOMBIA_Primera A": { "Atlético Nacional": "Atl. Nacional" } } }
}
```

El `unique_id` sale de la URL del torneo en sofascore.com, o del propio
`build_sofascore_map.py`, que lo imprime. El nombre del equipo debe ser **exacto** al de
la BD, porque con él se busca el partido.

## Comprobación en vivo

```bash
sports_env/bin/python scripts/live_sofascore_extract.py --deporte Football --loop 60
```

Imprime liga, partido, marcador de SofaScore y marcador de la BD lado a lado. Ninguno de
estos scripts escribe en la base de datos.
