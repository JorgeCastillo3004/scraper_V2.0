# Inconsistencias — partidos "fantasma" (a revisar, NO borrados)

> Generado 2026-06-16. Decisión de Jorge: **dejarlos documentados como
> inconsistencias**, no borrar. Revisar con más detalle más adelante.

## Contexto

Durante la reparación de `match_detail.team_id IS NULL` (modo
`fix_null_team_ids.py --db-only`, NULL 159 → 3 esta sesión), quedaron **3
partidos** cuyo lado "Great Britain" no se puede enlazar porque **no existe el
team** y **el partido no aparece en FlashScore**.

## Los 3 partidos

| match_id | nombre | fecha | start_time | status | rounds | league |
|---|---|---|---|---|---|---|
| `bb4fe98f-7481-4cbd-af8b-a311800a1d50` | Great Britain~Italy | 2026-02-27 | 19:30 | SCHEDULED | ROUND_3_3 | WORLD / World Cup (`2e7ee992…`) |
| `4298682e-228d-4dd3-8c9c-bb722b9fc439` | Italy~Great Britain | 2026-03-02 | 18:30 | SCHEDULED | ROUND_4_4 | WORLD / World Cup (`2e7ee992…`) |
| `9a9182fd-b1a6-4ee4-826d-0cd38ea6f442` | Lithuania~Great Britain | 2026-07-02 | 16:00 | SCHEDULED | ROUND_5_1 | WORLD / World Cup (`2e7ee992…`) |

Cada uno tiene 2 filas `match_detail` (el lado Italy/Lithuania **sí** está
resuelto; el lado "Great Britain" está NULL) y 2 filas `score_entity`.

## Evidencia de que son fantasma (FlashScore, 2026-06-16, READ-ONLY)

Páginas revisadas: `football/world/world-championship/{results,fixtures}` y
`football/africa/world-championship/fixtures` (heading "World Championship").

- **"Great Britain" no aparece** en ninguna página (sí aparecen Italy, Lithuania,
  France, Senegal).
- Italy **no tenía partido** el 27.02 ni el 02.03; sus partidos reales cercanos
  fueron 26.03 Italy–Northern Ireland y 31.03 Bosnia–Italy.
- **Great Britain no compite como selección en el Mundial FIFA de fútbol** (UK
  juega como Inglaterra / Escocia / Gales / Irlanda del Norte por separado).

## A revisar más adelante (sugerencias)

- Confirmar en FlashScore si existe alguna página/competición donde "Great
  Britain" juegue (¿otro deporte mal-etiquetado como Football? ¿un playoff
  reestructurado?). Por países, **Great Britain no existe** como selección de
  fútbol, así que probablemente sea data mal-scrapeada.
- Verificar de qué scrape salieron (revisar logs / origen del `league_id` WORLD).

## SQL de borrado — LISTO pero NO EJECUTADO (requiere OK explícito por caso)

```sql
-- Repetir por cada match_id de la tabla de arriba:
DELETE FROM score_entity WHERE match_detail_id IN
  (SELECT match_detail_id FROM match_detail WHERE match_id='<match_id>');
DELETE FROM match_detail WHERE match_id='<match_id>';
DELETE FROM match WHERE match_id='<match_id>';
```

> Regla del proyecto: nunca DELETE sin aprobación explícita por caso mostrando
> exactamente qué se borra (ver `CLAUDE.md`).
