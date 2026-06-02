# Mejoras de performance y validaciones del scraper

Documento operativo para validar integridad de datos y cerrar partidos que
quedaron sin actualizar por la sección live.

Toda consulta y script de este documento se ejecutan desde la raíz del repo:

```bash
cd /home/jorge/work/scraper_V2.0
```

---

## 1. Estado real detectado (snapshot 2026-05-24)

| Categoría | Conteo |
|---|---|
| Partidos totales por status — COMPLETED / SCHEDULED / LIVE | 4452 / 3521 / 28 |
| Partidos `status='LIVE'` con fecha pasada (los que cubre el script actual) | 28 |
| Partidos `status='SCHEDULED'` con `score_entity.points = -1` y fecha pasada (gap real) | **2714** |
| Partidos con `match_detail` != 2 (integridad rota) | 7 |
| `match_detail` sin `score_entity` | 5 |
| `match_detail` apuntando a `team_id` inexistente | **2729** |

> El bloque importante: `fix_live_matches.py` solo captura los **28** partidos
> en estado `LIVE`. Los **2714** SCHEDULED con `-1,-1` no entran al filtro
> actual, por eso "nunca se ejecutó la sección live" para ellos.

---

## 2. Validaciones de integridad (rápidas, sin scraping)

Ejecutar en este orden antes de cualquier corrección. Son consultas
de solo lectura.

### 2.1 Distribución de status

```bash
python3 scripts/check_match_status.py
```

Salida esperada: solo `COMPLETED`, `SCHEDULED`, `LIVE`. Si aparecen valores
legacy (`completed`, `schedule`, `R`, `P`, `IN PROGRESS`), correr con `--run`
para normalizar.

### 2.2 Partidos LIVE / completados con datos consistentes

```bash
python3 scripts/validacion.py --status LIVE
python3 scripts/validacion.py --status COMPLETED --sport_id <id>
```

Verifica que cada `match` traiga **dos** filas en `match_detail` (HOME/VISITOR),
que ambos `team` existan y que `score_entity.points` no sea NULL/-1.

### 2.3 Chequeos puntuales adicionales (queries directas)

Guardar como `scripts/db_integrity_quick.sql` o lanzar con `psql -h localhost
-U db_admin -d sports_db`:

```sql
-- a) Partidos sin exactamente 2 match_detail
SELECT match_id, COUNT(*) AS detail_count
FROM match_detail
GROUP BY match_id
HAVING COUNT(*) <> 2;

-- b) match_detail sin score_entity asociado
SELECT md.match_detail_id, md.match_id
FROM match_detail md
LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
WHERE se.match_detail_id IS NULL;

-- c) match_detail apuntando a team inexistente (FK rota)
SELECT md.match_detail_id, md.match_id, md.team_id
FROM match_detail md
LEFT JOIN team t ON t.team_id = md.team_id
WHERE t.team_id IS NULL;

-- d) Partidos pasados con score = -1 (los candidatos a re-extracción)
SELECT m.status, m.sport_id, COUNT(DISTINCT m.match_id) AS partidos
FROM match m
JOIN match_detail  md ON md.match_id = m.match_id
JOIN score_entity  se ON se.match_detail_id = md.match_detail_id
WHERE se.points = -1 AND m.match_date < CURRENT_DATE
GROUP BY m.status, m.sport_id
ORDER BY partidos DESC;
```

Cualquier conteo > 0 en (a), (b) o (c) es un bug real que debe corregirse a
mano o con un script dedicado **antes** de re-scrapear: si re-creamos
`score_entity` sobre `match_detail` con FK rota seguimos arrastrando basura.

---

## 3. Cerrar partidos con resultado `-1,-1`

### 3.1 Diagrama de funcionamiento de `fix_live_matches.py`

```
                ┌─────────────────────────────────────────────────────┐
                │  python3 scripts/fix_live_matches.py [--run] [--yes]│
                └─────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  [1] get_pending_live_matches()                               │
        │       SELECT match + league + sport + country                 │
        │       WHERE m.status = 'LIVE'                                 │
        │         AND m.match_date < CURRENT_DATE     ◄── filtro actual │
        └───────────────────────────────────────────────────────────────┘
                                       │ lista de partidos
                                       ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  [2] Agrupar por (sport, country, league)                     │
        │       defaultdict(list) → by_league                           │
        │       buscar URL de "results" en leagues_info.json            │
        └───────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                          ┌──── DRY-RUN ?──────┐
                          │                    │
                       Sí │                    │ No (--run)
                          │                    │
                          ▼                    ▼
                    listar y salir   ┌─────────────────────┐
                                     │ [3] launch_navigator│
                                     │     login FlashScore│
                                     └─────────────────────┘
                                               │
                                               ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  Para cada liga con partidos pendientes:                      │
        │   • wait_update_page(results_url, 'container__heading')       │
        │   • dismiss_cookies()                                         │
        │   • load_until_date(driver, oldest_match_date)                │
        │        └─ click repetido a "Show more matches" hasta abarcar  │
        │           la fecha más antigua del lote                       │
        │   • scan_results_page(driver, league_matches)                 │
        │        └─ por cada fila visible: matchear "home~visitor"      │
        │           extraer score, link_details                         │
        └───────────────────────────────────────────────────────────────┘
                                       │ found = {match_id: scraped}
                                       ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  Para cada match encontrado: update_match_in_db()             │
        │   • abrir link_details + get_match_info + get_statistics_game │
        │   • get_math_details_ids(match_id)  →  HOME/VISITOR detail_id │
        │   • UPDATE score_entity   SET points = N    (por detail_id)   │
        │   • UPDATE match          SET status = 'COMPLETED'            │
        │   • UPDATE match          SET statistic = <json>              │
        └───────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                          ┌────────────────────────┐
                          │  RESUMEN final         │
                          │   ok / not_found /     │
                          │   skipped / error      │
                          └────────────────────────┘
```

Estados de salida posibles por partido:

| Resultado | Causa | Acción manual sugerida |
|---|---|---|
| `ok` | Partido encontrado en FlashScore y BD actualizada | — |
| `not_found` | No apareció en la página de results | Validar `results` URL en `leagues_info.json`; reintentar |
| `skipped` | Usuario respondió `n` en modo interactivo | — |
| `error` | Excepción navegando/extrayendo | Revisar log; partido sigue marcado y vuelve en próxima corrida |

### 3.2 Script existente

Hay dos puntos de entrada:

| Script | Cuándo usarlo |
|---|---|
| `scripts/fix_live_matches.py` | Standalone — abre su propio Firefox y hace login |
| `scripts/run_fix_live.py`     | Reutiliza el driver vivo del notebook `main_depuracion.ipynb` (lee `tmp/driver_session.json`) |

Ambos llaman a `get_pending_live_matches()` definido en `fix_live_matches.py`,
que hoy filtra por:

```python
WHERE m.status = 'LIVE' AND m.match_date < CURRENT_DATE
```

### 3.3 Modificación propuesta — unificar el script

**Objetivo:** que el mismo `fix_live_matches.py` cubra ambos casos sin
duplicar lógica:

- (caso original) `status='LIVE'` + fecha pasada
- (caso nuevo)   fecha pasada + algún `score_entity.points = -1` (sin importar
                  el status, así absorbe SCHEDULED y eventuales LIVE huérfanos)

Cambio puntual en `scripts/fix_live_matches.py` dentro de
`get_pending_live_matches`:

```python
def get_pending_live_matches(only_status=None, sport=None, date_from=None, date_to=None):
    """
    Retorna partidos que requieren cierre desde FlashScore.

    Criterio unificado:
      • fecha < hoy
      • Y (status = 'LIVE'  OR  algún score_entity.points = -1)
    Filtros opcionales para correr por lotes.
    """
    print('\n[1] Consultando DB...')
    con = psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = con.cursor()

    sql = """
        SELECT DISTINCT
               m.match_id, m.name, m.match_date, m.league_id, m.season_id,
               l.league_name, c.country_name, s.name, m.status
        FROM match m
        JOIN league  l  ON m.league_id  = l.league_id
        JOIN sport   s  ON l.sport_id   = s.sport_id
        JOIN country c  ON l.country_id = c.country_id
        LEFT JOIN match_detail md ON md.match_id = m.match_id
        LEFT JOIN score_entity se ON se.match_detail_id = md.match_detail_id
        WHERE m.match_date < CURRENT_DATE
          AND (
                m.status = 'LIVE'
             OR se.points = -1
          )
    """
    params = []
    if only_status:
        sql += " AND m.status = %s "; params.append(only_status)
    if sport:
        sql += " AND s.name = %s ";   params.append(sport)
    if date_from:
        sql += " AND m.match_date >= %s "; params.append(date_from)
    if date_to:
        sql += " AND m.match_date <= %s "; params.append(date_to)
    sql += " ORDER BY s.name, l.league_name, m.match_date;"

    cur.execute(sql, params)
    cols = ['match_id','name','match_date','league_id','season_id',
            'league_name','country_name','sport_name','status']
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close(); con.close()

    by_status = {}
    for r in rows: by_status[r['status']] = by_status.get(r['status'], 0) + 1
    print('  Partidos a cerrar: %d  | desglose: %s' % (len(rows), by_status))
    return rows
```

Cambios adicionales recomendados en el mismo archivo:

1. **CLI extendida** (parseo con `argparse`, no `sys.argv` manual):

   ```bash
   python3 scripts/fix_live_matches.py --run --sport FOOTBALL \
           --from 2026-04-01 --to 2026-04-30 --yes
   ```

2. **Reporte por status en el resumen final** — ya hoy se imprime
   `ok / not_found / skipped / error`; añadir cuántos venían de `LIVE` vs.
   `SCHEDULED` con `-1` para verificar que el script está limpiando ambos.

3. **Idempotencia**: tras actualizar, el `status='COMPLETED'` + score real
   sacan al partido del filtro, así que re-correr es seguro.

### 3.4 Ejecución

```bash
# 1. Verificar candidatos en dry-run
python3 scripts/fix_live_matches.py
#   → imprime la lista completa de partidos candidatos sin tocar nada

# 2. Corrida real, con confirmación por partido
python3 scripts/fix_live_matches.py --run

# 3. Corrida real, sin confirmación (lotes grandes)
python3 scripts/fix_live_matches.py --run --yes
```

Variante con notebook abierto (driver ya autenticado, evita login repetido):

```bash
python3 scripts/run_fix_live.py
```

Requiere haber generado `tmp/driver_session.json` (celdas 4 y 5 del
notebook `main_depuracion.ipynb`).

### 3.4bis Bug de parseo de fechas (corregido)

`get_last_visible_date` en `scripts/fix_live_matches.py` extraía día/mes con
`re.findall(r'\d+', ...)` pero **descartaba el año** y siempre asignaba
`date.today().year`. FlashScore admite tres formatos en la lista de results:

| Formato | Cuándo aparece |
|---|---|
| `"DD.MM."`         (+ opcional `HH:MM`) | partido del año actual |
| `"DD.MM.YY"`       (+ opcional `HH:MM`) | partido de un año anterior, año corto |
| `"DD.MM.YYYY"`     (+ opcional `HH:MM`) | partido de un año anterior, año completo |

El bug impedía cerrar los **681 SCHEDULED + 2967 COMPLETED de 2025** que aún
estaban en BD con score `-1`: el `load_until_date` creía que la página ya
había alcanzado el rango (`2026 ≤ 2026`) y se detenía antes de cargar los
partidos viejos.

Fix aplicado: nueva función `parse_flashscore_date(raw)` con regex
`(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})?` que:

- Toma día/mes en los dos primeros grupos (FlashScore es DD.MM).
- Si hay tercer grupo de **4 dígitos** → lo usa como año literal.
- Si hay tercer grupo de **2 dígitos** → lo trata como YY y prefija `20`.
- Si no hay tercer grupo → usa el año actual.

Importante: la alternativa del regex es `\d{4}|\d{2}` (4 primero) para que
"2025" no quede atrapado en la rama de 2 dígitos. Validado con 10 casos en
`scripts/fix_live_matches.py` (incluye DD/MM de un solo dígito y combinaciones
con HH:MM detrás).

Una sola corrida por liga ya alcanza tanto partidos del año en curso como
históricos.

### 3.5 Manejo de lotes grandes

2714 partidos es demasiado para una sola corrida headless. Sugerencia:

1. Procesar por **deporte** (`--sport FOOTBALL`).
2. Procesar por **fecha** en rangos de 7–14 días (`--from / --to`).
3. Loggear a archivo: `python3 scripts/fix_live_matches.py --run --yes 2>&1 | tee logs/fix_live_$(date +%F).log`.
4. Tras cada lote: re-correr query (d) de §2.3 para confirmar que el conteo bajó.

---

## 3bis. Reporte de integridad por liga (snapshot 2026-05-24)

Las consultas de §2.3 agrupadas por liga muestran patrones muy distintos.

### A) Partidos con `match_detail` distinto de 2  (total: 5)

| Deporte | País | Liga | Partidos rotos |
|---|---|---|---|
| Football | CHILE | Liga de Primera | 5 |

### B) `match_detail` sin `score_entity`  (total: 5)

| Deporte | País | Liga | detail sin score |
|---|---|---|---|
| Football | CHILE | Liga de Primera | 5 |

> A y B coinciden en la misma liga — son los mismos 5 partidos donde la
> creación del segundo `match_detail` falló a medio camino, por lo que
> tampoco se generó su `score_entity`.

### C) `match_detail` con `team_id` inexistente  (total: 2729 — top 15)

| Deporte | País / Confederación | Liga | detail huérfanos |
|---|---|---|---|
| Football | WORLD | World Cup | **752** |
| Football | ASIA  | World Cup | 290 |
| Football | NORTH & CENTRAL AMERICA | World Cup | 276 |
| Football | AFRICA | World Cup | 241 |
| Football | EUROPE | Euro | 231 |
| Football | SOUTH AMERICA | World Cup | 228 |
| Basketball | ARGENTINA | Liga A | 217 |
| American Football | CANADA | CFL | 158 |
| Football | ECUADOR | Liga Pro | 68 |
| Football | EUROPE | World Cup | 58 |
| Football | AUSTRALIA & OCEANIA | World Cup | 58 |
| Football | CHINA | Super League | 35 |
| Basketball | BRAZIL | NBB | 28 |
| Football | COLOMBIA | Primera A | 27 |
| Football | COSTA RICA | Primera Division | 11 |

Resumen por deporte:

| Deporte | Detail con FK rota |
|---|---|
| Football | 2294 |
| Basketball | 255 |
| American Football | 158 |

### Diagnóstico del patrón en (C)

El grueso son **torneos de selecciones nacionales** (`World Cup`, `Euro`) —
1934 de 2294 en Football, ~84% del total. Hipótesis dominante: cuando estos
torneos se cargan, los equipos se insertan como `team` con `country_id` de
la confederación (ASIA, EUROPE, ...) pero después un re-scrape los reinserta
con un `country_id` real (e.g. la selección de Brasil bajo `BRAZIL`) y los
viejos `team` quedan borrados o reemplazados, dejando `match_detail.team_id`
apuntando al UUID original que ya no existe.

Casos secundarios (Liga A basket Argentina, CFL Canadá, NBB Brasil):
ligas con cambios frecuentes de franquicia/nombre — mismo mecanismo, menor
escala.

### Propuesta de solución

1. **Auditoría dirigida** — generar el listado completo de match_detail
   huérfanos con nombre del partido y `team_id` original:

   ```sql
   SELECT md.match_id, m.name, md.team_id, m.match_date, l.league_name
   FROM match_detail md
   LEFT JOIN team   t ON t.team_id   = md.team_id
   JOIN match  m ON m.match_id   = md.match_id
   JOIN league l ON l.league_id  = m.league_id
   WHERE t.team_id IS NULL
   ORDER BY l.league_name, m.match_date;
   ```

2. **Script de reconciliación** — nuevo `scripts/reconcile_orphan_teams.py`
   que para cada `match_detail` huérfano:

   - Parsea `match.name` (`"home~visitor"`) y deduce qué lado (home/visitor)
     corresponde por `match_detail.home`.
   - Busca un `team` por `team_name` exacto o normalizado (lowercase,
     sin acentos) en el mismo `sport_id`.
   - Si encuentra una sola coincidencia → re-vincular (`UPDATE match_detail
     SET team_id = ?`).
   - Si encuentra varias o ninguna → loguear a `tmp/orphan_unresolved.csv`
     para revisión manual.

   Dry-run / `--run` igual que `fix_live_matches.py`.

3. **Activar FK declarativa en BD** para que el problema no se vuelva a
   producir silenciosamente:

   ```sql
   ALTER TABLE match_detail
     ADD CONSTRAINT match_detail_team_fk
     FOREIGN KEY (team_id) REFERENCES team(team_id)
     DEFERRABLE INITIALLY DEFERRED;
   ```

   La cláusula `DEFERRABLE` permite que las cargas batch del scraper validen
   al `COMMIT` y no fila por fila. Antes de aplicarla, el script de
   reconciliación tiene que dejar 0 huérfanos o el `ALTER` falla.

4. **Caso especial selecciones (World Cup / Euro)** — revisar
   `src/milestone3.py` (`teams_creation`): unificar el criterio para que la
   selección de un país siempre se inserte con el mismo `country_id`
   (el del país, no el de la confederación), y dedupe por nombre antes de
   insertar.

5. **Para los 5 partidos de Chile Liga de Primera (A + B)** — son
   recuperables corriendo el script live una vez aplicado §3.3, ya que
   tienen score = -1. Si tras correr siguen rotos, eliminar manualmente y
   re-extraer la temporada.

### E) Score = -1 — top 15 ligas afectadas

| Deporte | País | Liga | Partidos con score = -1 |
|---|---|---|---|
| Football | ENGLAND | Premier League | 233 |
| Football | GERMANY | Bundesliga | 209 |
| Football | ITALY | Serie A | 189 |
| Football | TURKEY | Super Lig | 170 |
| Football | FRANCE | Ligue 1 | 155 |
| Football | BELGIUM | Jupiler Pro League | 125 |
| Hockey | CZECH REPUBLIC | Extraliga | 107 |
| Football | BRAZIL | Serie A Betano | 106 |
| Football | ARGENTINA | Liga Profesional | 105 |
| Football | COLOMBIA | Primera A | 104 |
| Football | RUSSIA | Premier League | 97 |
| Basketball | EUROPE | Euroleague | 94 |
| Hockey | FINLAND | Liiga | 90 |
| Football | WORLD | World Cup | 84 |
| Football | SPAIN | LaLiga | 83 |

Patrón: las ligas top mundiales son las más afectadas — lo esperable si el
módulo live tuvo caídas o ventanas sin ejecutarse. No es un problema por
liga sino del scheduler de `main2.py`. Solución: §3.3 + §4.1.

---

## 4. Mejoras de performance del scraper

Apuntan a reducir el volumen de partidos que terminan con `-1,-1` y a acortar
el tiempo de re-extracción.

### 4.1 Frecuencia del módulo live

`src/milestone7.py` (`live_games`) corre en `main2.py` en loop continuo.
Para que no se acumulen partidos sin cierre:

- Garantizar que `main2.py` esté **siempre arriba** (un duplicado o caída
  silenciosa explica los 2714 SCHEDULED con `-1`).
- Verificar a diario con: `ps aux | grep main2 | grep -v grep`.
- Logs en `logs/` deberían mostrar movimiento de los últimos 5–15 min.

### 4.2 Sin instancias duplicadas

Duplicados causan freezes y peticiones dobles (ver `desarrollo_local.md` §9).
Antes de lanzar cualquier ejecución masiva:

```bash
pkill -f "uvicorn api.main"   # solo si se va a relanzar la API
pkill -f "vite"               # solo si se va a relanzar el frontend
ps aux | grep geckodriver | grep -v grep   # sin huérfanos
```

### 4.3 Paralelización controlada

`paralel_execution.py N results` permite N workers Firefox. Recomendaciones:

- N ≤ número de cores físicos − 1 (deja margen para FastAPI y Firefox).
- Limpiar `running_leagues` antes de correr: deja claim huérfanos si murió un worker.
- Monitorear RAM: cada Firefox headless ~ 300–500 MB.

### 4.4 Checkpoints

`check_points/leagues_info.json` controla qué ligas se extraen.
`scripts/check_teams_match_db.py` actualiza los conteos `teams` y `matches`
reales y reactiva `extract_results.extract` / `extract_fixtures.extract` cuando
una liga tiene equipos pero pocos partidos (umbral por defecto 20).

Correrlo periódicamente evita "olvidar" ligas que perdieron datos por un crash.

---

## 5. Procedimiento sugerido (orden de ejecución)

1. **Snapshot de integridad** — consultas §2.1, §2.2 y §2.3 (a, b, c).
2. **Reparar FKs rotas** (`match_detail` con `team_id` inexistente, etc.) — si
   alguna devuelve filas, escalarlo antes de re-scrapear.
3. **Conteo de gap** — query §2.3 (d). Anotar el total inicial.
4. **Aplicar parche** del WHERE en `fix_live_matches.py` (§3.3).
5. **Dry-run** del script (§3.4 paso 1). Confirmar que la lista coincide con (d).
6. **Lotes** por deporte / rango de fechas (§3.5). Conservar logs.
7. **Re-correr** query (d) tras cada lote — debe bajar monotónicamente.
8. **Validación final** — `validacion.py --status COMPLETED` sobre una muestra
   de los partidos actualizados; confirmar `score_entity.points >= 0` y
   `match.status = 'COMPLETED'`.

---

## 5bis. Pantalla "Inconsistencias" en el frontend

Existe un panel de diagnóstico solo-lectura en el control panel:

- Ruta: `http://localhost:5174/inconsistencias` (dev) o `/inconsistencias` en
  el frontend servido por FastAPI en producción.
- Endpoint: `GET /api/inconsistencias` (cacheo 60 s server-side).
- Implementación: `frontend/src/pages/Inconsistencias.jsx` + `api/routers/inconsistencias.py` + `api/services/database.py::get_inconsistencias_summary`.

Muestra los 5 conteos globales (con severidad alto/medio/bajo) y desglose por
liga (top 15) de cada categoría. Las acciones correctivas siguen lanzándose
desde terminal o desde el notebook (`fix_past_matches(driver, ...)`).

---

## 5ter. Función `fix_past_matches` en el notebook

`notebooks/main_depuracion.ipynb` incluye una celda con la función
`fix_past_matches(driver, *, only_status=None, sport=None, date_from=None, date_to=None, dry_run=True)`
que reusa el driver activo del notebook (sin abrir un Firefox extra) y permite
correr por lotes. Internamente usa la versión ampliada de
`get_pending_live_matches` (status LIVE OR score=-1).

Ejemplos:

```python
# Preview total sin escribir:
fix_past_matches(driver, dry_run=True)

# Solo SCHEDULED con -1 (excluye LIVE):
fix_past_matches(driver, only_status='SCHEDULED', dry_run=True)

# Lote acotado (Football, abril 2026):
fix_past_matches(driver, sport='Football',
                 date_from='2026-04-01', date_to='2026-04-30',
                 dry_run=False)
```

---

## 6. Referencias internas

- Filtro original: `scripts/fix_live_matches.py:40-60`
- Variante con driver activo: `scripts/run_fix_live.py:1-58`
- Validación interactiva: `scripts/validacion.py`
- Migración de status legacy: `scripts/check_match_status.py`
- Conteo y reactivación por liga: `scripts/check_teams_match_db.py`
- Módulo live: `src/milestone7.py` (función `live_games`)
- Recuperación de procesos colgados: `documentacion/desarrollo_local.md` §9

---

## 7. Workflow de testing para scripts de reparación

Patrón estandar para desarrollar y operar scripts largos que escrapean
FlashScore + escriben en DB (`fix_live_matches.py`, `fix_null_team_ids.py`,
futuros `reconcile_*`). Pensado para iteración tipo notebook + ejecución
desatendida con recovery.

### 7.1 Principios

1. **Un solo driver vivo.** Se lanza una vez (Firefox + geckodriver detached
   via `subprocess.Popen(..., start_new_session=True)`); cualquier script de
   prueba o producción **se adjunta** a él via `session_id`. Nunca se mata
   ni se relanza sin confirmación explícita del usuario (ver
   `docs/DRIVER_RULES.md` para la regla completa).
2. **Conexión por session_id persistido.** El driver guarda
   `{session_id, executor_url}` en `tmp/driver_session.json`. Cualquier script
   posterior lee ese archivo y se adjunta con la subclase `_AttachRemote`
   (override de `start_session` no-op). Ver
   `scripts/fix_null_team_ids.py::_AttachRemote`.
3. **Idempotencia.** Cada operación verifica "ya existe" antes de actuar:
   `team` se busca por nombre+sport+country antes de INSERT;
   `match_detail` se actualiza si la fila ya está aunque sin team_id; el
   `match.status` se setea solo si difiere. Esto permite re-correr el
   script sin duplicar y sin miedo.
4. **Logs estructurados.** Cada paso emite una línea (JSONL recomendado, o
   prefijos parseables tipo `[OK]`, `[ERROR]`, `[FOUND]`, `[CREATED TEAM]`).
   Permite contar con `grep -c` o `jq` sin parsear texto frágil.
5. **Heartbeat separado.** Aparte del log, un archivo de 1 línea sobreescrito
   cada N items: `tmp/run_status_<script>.json` con
   `{updated, stage, current_item, processed, ok, err, remaining}`. Un
   monitor externo lo lee con `cat` (no grep al log de 100 MB) y detecta
   "stuck" si `updated` no avanza en X minutos.
6. **Checkpoints granulares.** No solo "voy en match X" sino "voy en match X,
   stage `team_extract_visitor`". Persistir en DB (tabla `script_checkpoint`
   con columnas `script_name, item_id, stage, status, last_error`) o en JSON
   bajo `check_points/`. Al reiniciar, leer la última row `in_progress` y
   resumir desde su stage — no reprocesar el item desde cero.
7. **Separación driver / lógica.** Dos módulos limpios:
   - **`scripts/driver_session.py`** — `get_driver()`, `is_alive()`,
     `force_relaunch(confirm=True)`. Única responsabilidad: ciclo de vida
     del driver. Nada de scraping.
   - **`scripts/fix_X.py`** — recibe driver via parámetro. No lo lanza ni
     lo cierra. Solo lógica de scraping.

### 7.2 Flujo de desarrollo (scratchpad → definitivo)

Trabajar como en un notebook pero con scripts persistidos:

```
1. Lanzar driver una sola vez
   python scripts/fix_null_team_ids.py --league "FOOTBALL/AFRICA_World Cup" \
          --match-id <id_de_prueba>
   # → login + save tmp/driver_session.json + driver queda vivo detached

2. Iterar en scratchpad
   scripts/dev_playground.py    # o scripts/_debug_<tema>.py
   # importa _reuse_driver_session, se conecta al driver vivo
   # prueba funciones aisladas: get_team_links_from_match(),
   # ensure_team_created(), etc.

3. Migrar funciones validadas al script definitivo
   # ediciones en scripts/fix_X.py
   # re-correr con --apply para procesar el lote real

4. Re-correr es seguro
   # gracias a idempotencia + checkpoint, el script ignora lo ya OK
   # y continúa desde donde se quedó
```

### 7.3 Failure modes y respuesta automática

Tabla de qué hace el script ante cada tipo de error (no abortar, no matar
driver):

| Error | Causa común | Acción del script |
|---|---|---|
| `TimeoutException` (page load) | FlashScore lento o caída transitoria | retry 1 vez con wait*2; si falla → log + skip + checkpoint |
| `NoSuchElementException` | HTML de FlashScore cambió | log con snapshot HTML + skip + alerta al usuario |
| `ConnectionError` DB | Postgres reinició / red | `ensure_connection()` + retry hasta 3 veces |
| Driver no responde (`Message: ` vacío) | geckodriver colgado | log + halt + alerta al usuario; **NO matar driver sin confirmación** |
| Item ya procesado (UPSERT no aplica) | re-corrida o ejecución previa parcial | skip silencioso + log INFO |

Cualquier `[ERROR]` que no encaje en la tabla debe interrumpir el lote y
notificar.

### 7.4 Operación desatendida + monitor externo

Para corridas largas (cientos de matches, varias horas):

```bash
# Lanzar script en background con log JSONL
nohup ./env_sports/bin/python -u scripts/fix_null_team_ids.py \
      --league "BASKETBALL/ARGENTINA_Liga A" --apply \
      > logs/fix_argentina_$(date +%F_%H%M).jsonl 2>&1 &

# Monitor desde otra terminal
watch -n 30 'cat tmp/run_status_fix_null.json | jq .'

# Detectar stuck (no avanza en 10 min):
while sleep 60; do
  age=$(( $(date +%s) - $(date +%s -d "$(jq -r .updated tmp/run_status_fix_null.json)") ))
  [ $age -gt 600 ] && echo "STUCK ${age}s" && break
done
```

Si se detecta stuck:
1. Verificar `current_item` en el JSON de status.
2. Ir al scratchpad (`dev_playground.py`) con ese item, reproducir el caso.
3. Identificar fix → migrar al script definitivo.
4. Re-lanzar; el checkpoint hace que continúe desde el item fallido (no
   retrocede a procesados OK).

### 7.5 Scripts existentes que siguen este patrón

| Script | Driver reuse | Heartbeat | Idempotente | Checkpoint granular |
|---|---|---|---|---|
| `scripts/fix_live_matches.py` | ❌ (lanza propio) | ❌ | ✓ (status COMPLETED filtra) | ❌ (por liga) |
| `scripts/run_fix_live.py` | ✓ (tmp/driver_session.json) | ❌ | ✓ | ❌ |
| `scripts/fix_null_team_ids.py` | ✓ (`_AttachRemote`) | ❌ (a implementar) | ✓ (skip ya creados) | ❌ (a implementar) |
| `scripts/fix_inconsistent_matches.py` | n/a (solo DB) | ❌ | ✓ | ❌ |
| `scripts/fix_missing_teams.py` | n/a (solo DB) | ❌ | ✓ | ❌ |
| `scripts/dev_playground.py` | ✓ | n/a (es scratchpad) | n/a | n/a |
| `paralel_execution.py` | n/a (workers propios) | ✓ (`logs/run_status_*.json`) | ✓ (claim/release) | ✓ (por liga en DB `running_leagues`) |

`paralel_execution.py` ya implementa heartbeat + checkpoint correctamente —
usar como referencia al añadir esas features a los scripts `fix_*`.

### 7.6 Próximos pasos sugeridos

1. Formalizar **`scripts/driver_session.py`** como autoridad única del
   driver (extraer `_reuse_driver_session`, `launch_detached_driver`,
   `_save_driver_session`, `_AttachRemote` desde `fix_null_team_ids.py`).
   Actualizar todos los scripts `fix_*` para importar desde ahí.
2. Agregar **heartbeat** (`tmp/run_status_<script>.json`) a los `fix_*`
   con escritura cada item procesado.
3. Migrar prints `[OK] / [ERROR] / [FOUND]` a **JSONL** (`{ts, level, stage,
   item, msg}`) en `logs/<script>_<fecha>.jsonl`.
4. Crear tabla **`script_checkpoint`** en DB con resumibilidad por
   (script_name, item_id, stage). Adaptar `fix_null_team_ids.py` como prueba.
5. Crear **`scripts/watch_run.py`** opcional para detectar stuck
   automáticamente y pausar via `tmp/run_control_<script>.json`.

---
