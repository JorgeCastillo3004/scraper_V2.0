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
| `click_show_more_news` | Scroll + click "Show more" hasta `max_click_more` veces |
| `make_scroll_to_bottom` | Scroll con rebote para activar lazy-load |
| `update_recent_news_found` | Actualiza fecha checkpoint solo en primer batch |
| `get_news_info_part2` | Extrae cuerpo, resumen, imagen y menciones de la noticia abierta |
| `extract_news_info` | Loop sobre archivos JSON generados en FASE 1, persiste en DB |
| `check_enable_add_news` | Verifica duplicados por título antes de guardar |

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
│     { "FOOTBALL": { "last_date": "2024-03-15 10:00:00", "phase2": {...} } }
│
└── news/
      └── FOOTBALL/
            ├── 0_12.json      ← batch: noticias del índice 0 al 12
            └── 13_24.json
```

- `last_date` — frontera temporal: solo se procesan noticias más recientes
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
