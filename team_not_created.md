# Equipos pendientes de crear / desambiguar

Generado por `scripts/fix_missing_teams.py` (ejecucion del 2026-05-24).

Lista los equipos referenciados por `match.name` que no se pudieron registrar
automaticamente en `league_team` durante el fix. Para cada uno se incluye toda
la informacion de la liga, deporte, temporada y partido afectado — todo lo
necesario para que un humano (o un script posterior) complete la informacion
faltante en DB.

---

## Caso 1 — AMBIGUOUS

### `Nublense` — Liga de Primera (Chile)

Hay **dos `team_id`** registrados con el mismo `team_name`, `sport_id` y
`country_id`. El clasificador automatico no puede elegir uno.

**Candidatos:**

| team_id | country_id | partidos previos en Liga de Primera 2026 |
|---|---|---|
| `c3c247e0-40cd-4f3d-9e03-fa708b7b2024` | `4w11r5rm30xhcph3c` (CHILE) | **0** |
| `a98cc9a5-4f39-4b02-b08a-7faa8abaa0f8` | `4w11r5rm30xhcph3c` (CHILE) | **5**  ← recomendado |

**Recomendacion:** registrar el `team_id = a98cc9a5-4f39-4b02-b08a-7faa8abaa0f8`
en `league_team` (es el que ya tiene matches en la liga; el otro es duplicado
huerfano que conviene marcar para borrar despues).

**Info de la liga / partido afectado:**

| campo | valor |
|---|---|
| sport | Football |
| sport_id | `1cbecbaf-1b6c-438b-881b-320ffc264806` |
| country | CHILE |
| country_id | `4w11r5rm30xhcph3c` |
| league_name | Liga de Primera |
| league_id | `7b0f4cfa-6a3e-449a-b91e-271efbcd5853` |
| season_name | 2026 |
| season_id | `3b815bbf-d9ef-4705-8ee9-c149fa5f7818` |
| match_id afectado | `347c6402-fefa-41ca-98f5-fe9855605436` |
| match name | `D. Concepcion~Nublense` |
| match_date | 2026-03-06 |
| rol faltante | visitor |

**SQL para resolverlo manualmente:**

```sql
-- 1) registrar el team_id correcto en league_team para esa temporada
INSERT INTO league_team (instance_id, team_meta, team_position, league_id, season_id, team_id)
VALUES (
  gen_random_uuid()::text,  -- o un UUID generado en Python
  NULL, NULL,
  '7b0f4cfa-6a3e-449a-b91e-271efbcd5853',
  '3b815bbf-d9ef-4705-8ee9-c149fa5f7818',
  'a98cc9a5-4f39-4b02-b08a-7faa8abaa0f8'
);

-- 2) (opcional) marcar el team_id duplicado huerfano para revisar:
SELECT * FROM team WHERE team_id = 'c3c247e0-40cd-4f3d-9e03-fa708b7b2024';
```

Luego corre `scripts/fix_inconsistent_matches.py --apply` para completar el
`match_detail` faltante de `D. Concepcion~Nublense`.

---

## Caso 2 — TEAM_MISSING

Equipos referenciados en `match.name` que NO existen en la tabla `team`. Hay
que crearlos antes de poder registrar el `match_detail`.

### `Central Africa` — World Cup (Football)

| campo | valor |
|---|---|
| team_name | Central Africa |
| sport | Football |
| sport_id | `1cbecbaf-1b6c-438b-881b-320ffc264806` |
| country (liga) | WORLD |
| country_id (liga) | `1szntdq0kvp6odaob` |
| league_name | World Cup |
| league_id | `2e7ee992-42e9-4347-927e-a2bc27e08027` |
| season_id | `838e04dd-a825-44b7-99e7-d266303151db` |
| match_id afectado | `b8bb3b8c-0acb-4dd0-93b7-8408e120e109` |
| match name | `Central Africa~Mali` |
| match_date | 2025-03-24 |
| rol faltante | home |

**Decision pendiente:** que `country_id` asignar al team. El partido es de la
World Cup (country = WORLD), pero la seleccion deberia ir asociada al pais
correspondiente (Republica Centroafricana). Antes de crear el `team`,
verificar si existe `country` para Centroafrica:

```sql
SELECT * FROM country WHERE country_name ILIKE '%central%' OR country_name ILIKE '%afric%';
```

Si no existe, crearlo primero. Si existe, usar su `country_id` al crear el `team`:

```sql
INSERT INTO team (team_id, country_id, team_desc, team_logo, team_name, sport_id)
VALUES (
  gen_random_uuid()::text,
  '<country_id-de-Centroafrica>',
  NULL, NULL,
  'Central Africa',
  '1cbecbaf-1b6c-438b-881b-320ffc264806'
);
```

---

### `Mali` — World Cup (Football)

| campo | valor |
|---|---|
| team_name | Mali |
| sport | Football |
| sport_id | `1cbecbaf-1b6c-438b-881b-320ffc264806` |
| country (liga) | WORLD |
| country_id (liga) | `1szntdq0kvp6odaob` |
| league_name | World Cup |
| league_id | `2e7ee992-42e9-4347-927e-a2bc27e08027` |
| season_id | `838e04dd-a825-44b7-99e7-d266303151db` |
| match_id afectado | `b8bb3b8c-0acb-4dd0-93b7-8408e120e109` |
| match name | `Central Africa~Mali` |
| match_date | 2025-03-24 |
| rol faltante | visitor |

Misma logica que `Central Africa`: verificar/crear `country` para Mali, luego
crear el `team`.

---

## Pasos para completar todo

1. Resolver los 3 casos arriba (UPDATE/INSERT manual o usando
   `fix_missing_teams.py --apply --create-teams` — pero ese flag usa el
   `country_id` de la liga (`1szntdq0kvp6odaob` = WORLD), lo cual NO es ideal
   para selecciones nacionales; preferible hacerlo manual).

2. Correr `python scripts/fix_inconsistent_matches.py --apply` para insertar
   los `match_detail` faltantes ahora que ya existen los `team_id`.

3. Verificar que ya no quedan inconsistencias:

```bash
python scripts/fix_inconsistent_matches.py    # dry-run debe reportar 0
```

---

## Estado al momento de la ejecucion

- Total equipos faltantes detectados: **13**
- Registrados automaticamente en `league_team`: **10**
- Pendientes en este documento: **3** (1 ambiguous + 2 team_missing)
