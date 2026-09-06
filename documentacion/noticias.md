# Noticias — `milestone1.py`

Extrae artículos de noticias deportivas desde FlashScore y los persiste en PostgreSQL.

---

## Función principal

```python
main_extract_news(driver, list_sports, MAX_OLDER_DATE_ALLOWED=31)
```

| Parámetro | Tipo | Descripción |
|---|---|---|
| `driver` | WebDriver | Sesión Selenium activa |
| `list_sports` | list[str] | Deportes a procesar. Ej: `['FOOTBALL', 'TENNIS', 'BASKETBALL']` |
| `MAX_OLDER_DATE_ALLOWED` | int | Días hacia atrás permitidos (default 31) |

**Checkpoint de entrada:** `check_points/last_saved_news.json`
**Checkpoint de salida:** `check_points/news/{sport_name}/*.json`

---

## Arquitectura — Dos fases

```
main_extract_news(driver, list_sports)
│
│  Por cada deporte en list_sports:
│
├─ ¿Hay checkpoint de FASE 2 interrumpida?
│    └─ SÍ → extract_news_info()   [retoma directamente]
│    └─ NO → continúa con FASE 1
│
├─ FASE 1 — Recolección de links y metadata
│    │
│    ├─ wait_update_page(driver, news_url, "fsNewsSection")
│    │    └─ Navega a la URL de noticias del deporte
│    │
│    ├─ WHILE last_index < total_artículos_en_DOM:
│    │    │
│    │    ├─ get_list_recent_news(driver, MAX_OLDER_DATE_ALLOWED, last_index, last_date_saved)
│    │    │    └─ Itera artículos sin solapamiento desde last_index
│    │    │    └─ Retorna: {index: {title, published, image, news_link}}, new_last_index, enable_more_click
│    │    │
│    │    ├─ update_recent_news_found()
│    │    │    └─ Registra la fecha más reciente en last_saved_news.json (solo primer batch)
│    │    │
│    │    ├─ save_check_point('check_points/news/{sport}/{start}_{end}.json', batch)
│    │    │
│    │    └─ SI enable_more_click:
│    │         └─ click_show_more_news()  →  expande DOM (hasta 5 clics en "Show more")
│    │
└─ FASE 2 — Extracción de detalle y guardado en DB
     │
     └─ extract_news_info(driver, sport_name, last_news_saved)
          │
          ├─ Lee archivos JSON de check_points/news/{sport_name}/
          ├─ Por cada noticia:
          │    ├─ wait_load_detailed_news(driver, url)
          │    ├─ get_news_info_part2(driver, dict_news)
          │    │    └─ Extrae: cuerpo HTML, resumen, imagen principal, menciones
          │    └─ save_news_database(dict_news)
          │
          └─ Al completar cada archivo: os.remove(file_path)
```

---

## Funciones internas

| Función | Rol |
|---|---|
| `get_list_recent_news` | Itera artículos visibles en DOM desde `last_index`, retorna batch y flag de continuidad |
| `click_show_more_news` | Scroll + click "Show more" hasta `max_click_more` veces. Recibe `last_date_saved` (corte unificado) |
| `make_scroll_to_bottom` | Scroll con rebote para activar lazy-load |
| `update_recent_news_found` | Guarda la fecha nueva en `pending_last_date` (NO `last_date`); se promueve al terminar FASE 2 |
| `get_news_info_part2` | Extrae cuerpo, resumen, imagen y menciones de la noticia abierta |
| `extract_news_info` | Loop sobre JSON de FASE 1, persiste en DB. **Devuelve el driver** (posible relevo). Early-skip + reciclaje |
| `_fase1_collect` | FASE 1 extraída a helper (navegación + show_more); se invoca con retry-con-relevo. **Devuelve el driver** |
| `_compute_floor_date` | Frontera temporal ÚNICA (la usan iterador y show_more): checkpoint si existe, sino `now - max_older días` |
| `_is_driver_dead` / `_relaunch_news_driver` / `_ensure_alive` | Reciclaje del driver de noticias (detectar muerto → relanzar con login) |
| `check_enable_add_news` | (FASE 1) heurística de continuidad por título recientes |
| `save_news_database` / `news_exists` | (`data_base.py`) dedup idempotente por **`(title, news_content)`** antes de insertar |

---

## Selectores CSS/XPath

```python
XPATH_ARTICLES = '//div[@class="fsNews"]//a[contains(@class,"wcl-article")]'
XPATH_TITLE    = './/*[contains(@class,"wcl-headline") or @role="heading"]'
XPATH_META     = './/*[contains(@class,"wcl-newsMeta")]'
XPATH_IMAGE    = './/figure//img'
```

> FlashScore migró a clases `wcl-*` con sufijos aleatorios. Los selectores usan `contains()` para tolerancia.
> El botón "Show more" fue reemplazado por scroll infinito — `click_show_more_news` maneja ambos casos.

---

## Checkpoint

```
check_points/
├── last_saved_news.json
│     { "FOOTBALL": { "last_date": "2026-03-15 10:00:00",
│                     "pending_last_date": "2026-06-18 07:10:00",
│                     "phase2": {...} } }
│
└── news/
      └── FOOTBALL/
            ├── 0_12.json      ← batch: noticias del índice 0 al 12
            └── 13_24.json
```

- `last_date` — frontera temporal OFICIAL: solo se procesan noticias más recientes
- `pending_last_date` — fecha nueva recolectada en FASE 1; se PROMUEVE a `last_date` solo al
  completar FASE 2 (si FASE 2 falla, la frontera no adelanta data no guardada)
- `phase2` — estado de reanudación (archivo + índice actual); se elimina al completar

---

## Llamada desde notebook

```python
main_extract_news(driver, ['FOOTBALL','TENNIS','GOLF','BASKETBALL','AMERICAN_SPORTS','HOCKEY'], MAX_OLDER_DATE_ALLOWED=31)
```

---

## Inicialización (primera ejecución)

```python
initial_settings_m1(driver)
# Crea: check_points/sports_url_m1.json  →  URLs de noticias por deporte
# Crea: check_points/CONFIG_M1.json      →  deportes habilitados y parámetros
```

---

## Robustez, dedup y reciclaje (actualizado 2026-06-20)

El sistema fue endurecido. Verificado end-to-end sobre los 6 deportes, 0 crashes.

### 1. Dedup idempotente — clave `(title, news_content)`
`save_news_database` (`src/data_base.py`) verifica existencia ANTES de insertar. La tabla
`news` NO tiene constraint único (solo PK `news_id` aleatorio). La clave es **`(title,
news_content)`** — NO `published`: las noticias recientes traen fecha RELATIVA ("X min ago")
y `process_date` la calcula contra el "ahora" de cada corrida → `published` varía entre
corridas y un dedup por fecha dejaba pasar near-duplicados. `(title, content)` identifica la
misma noticia por contenido y preserva títulos repetidos que son noticias DISTINTAS.

### 2. Early-skip antes de navegar
En FASE 2, `news_exists(title, published)` saltea las ya guardadas SIN navegar (la FASE-1 ya
trae title+published en el JSON). Solo optimización: si no saltea, el guard de contenido lo atrapa.

### 3. Corte temporal unificado — `_compute_floor_date(last_date_saved, max_older)`
Frontera ÚNICA usada por `get_list_recent_news` Y `click_show_more_news`: con checkpoint usa
`last_date_saved` (ignora el límite de días → backfill completo); sin checkpoint usa `now -
max_older días` (bootstrap). Antes `click_show_more_news` cortaba SIEMPRE en `now-31d` ignorando
el checkpoint → no backfilleaba más de 31 días (causa del gap de abril).

### 4. Reciclaje de driver (FASE 1 + FASE 2)
El driver se cuelga tras muchas páginas (`InvalidSessionId`/`Read timed out`). Helpers:
`_is_driver_dead`, `_relaunch_news_driver`, `_ensure_alive`. FASE 2: relanza en el retry loop
(budget 10). FASE 1: `_fase1_collect` con retry-con-relevo (budget 5) + `_ensure_alive` al entrar
a cada deporte. Ambas funciones DEVUELVEN el driver; los call sites reasignan `driver = ...`.
**El driver de noticias debe ser `lightweight=False`** (con imágenes): `get_news_info_part2` usa
`visibility_of_element_located` para la imagen (necesita render). NO pasarlo a lightweight. Los
logos de equipo SÍ funcionan en lightweight (URL en DOM + `requests.get`, sin lazy-load).

### 5. Frontera diferida — `pending_last_date`
Ver sección Checkpoint. Avanza `last_date` solo al completar FASE 2.

### Procedimiento de limpieza de duplicados (DELETE requiere OK explícito por caso)
1. **Clasificar** (read-only): agrupar por `title` con `count(*)>1`; `count(distinct news_content)=1`
   → DUP-REAL (borrar copias); `>1` → noticias LEGÍTIMAS distintas mismo título (**NO tocar**).
2. **Respaldar** a `logs/_deleted_news_dupes_backup*.json`.
3. **Borrar en transacción** conservando 1 por `(title, news_content)`:
   `DELETE FROM news WHERE news_id IN (SELECT news_id FROM (SELECT news_id, row_number() OVER
   (PARTITION BY title, news_content ORDER BY news_id) rn FROM news) t WHERE rn>1)`.
4. **Verificar ANTES de commit**: rowcount == esperado, total disminuye lo borrado, 0 grupos
   title+content-dup, y grupos LEGÍTIMOS quedan IGUAL. Solo entonces commit; sino rollback.
   Histórico: 127 (clave vieja, 2026-06-18) + 115 near-dups (clave nueva, 2026-06-19). Total = 1487.

### Scheduler / operación
- Corre `scripts/run_news.py` (driver propio headless NO-lightweight + login + `main_extract_news` + quit).
- 1×/día (`EXTRACT_NEWS` en `check_points/CONFIG.json`, `EVERY_HOURS=24`). El scheduler NO relanza
  si `news_running=true`.
- **LECCIÓN (2026-06-20):** una corrida agendada lanzada con código viejo (sin reciclaje) quedó 39h
  girando en `Read timed out` y BLOQUEÓ las corridas diarias siguientes (no-overlap). Con el reciclaje
  ya no pasa. Síntoma: `news_running=true` mucho tiempo + sin noticias nuevas → buscar un `run_news.py`
  zombie (`ps -eo pid,etime,cmd | grep python.*run_news`) y detenerlo con SIGINT (ejecuta `finally:quit`).
  OJO: `pgrep -f run_news.py` se auto-matchea con el propio comando shell → usar `ps`/PID directo.

### Pendiente (próxima sesión)
- **Backfill dirigido de abril-mayo**: el watermark avanza hacia lo nuevo; los deportes que ya pasaron
  abril no lo llenan solos. Para completar: resetear su `last_date` en `last_saved_news.json` a ~25-mar
  y re-correr (ya seguro por la dedup). Decisión de Jorge.
