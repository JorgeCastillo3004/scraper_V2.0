# Verificación del ROADMAP_SCRAPER — estado real

> Verificado el **2026-09-06** contra el servidor `104.156.244.145` y la BD `sports_db`
> en producción. Cada afirmación de aquí sale de un comando ejecutado, no del roadmap.
> El roadmap se escribió el 2026-08-23; varias de sus premisas ya no se sostienen.

---

## 1. Correcciones a "Where things stand"

| El roadmap dice | Realidad verificada hoy |
|---|---|
| "The production scraper is `scraper_v3`" | **Falso hoy.** `scraper_v3` existe en el servidor pero su último log es del **25-mar-2026** y no tiene ningún proceso vivo: lleva ~5,5 meses muerto. Lo que corre en producción es **`live_v2`** (159 MB), desplegado el 30-ago. |
| "It is run by hand. No cron entry, no systemd unit" | **Ya no.** `scraper-live.service` (unidad de **usuario**, `Restart=always`, `linger` para sobrevivir al reboot) corre desde el 30-ago; hoy lleva 6 d sin reinicios. Además `scraper-logrotate.timer` cada 6 h. |
| "19 GB total, about 18 GB is `logs/`" | **Confirmado y sin resolver**, pero es de `scraper_v3`, no de `live_v2`: **18 GB en `logs/parallel/`** (workers de ejecución paralela) + 474 MB en `images/`. La rotación instalada cubre `live_v2` únicamente. Disco: 95 G usados de 244 G (41 %) — no urgente, sí desperdicio. |
| "Its database password may be stale" | **Resuelto.** La BD responde y hoy mismo se escribieron 860 partidos desde local. |
| "Git HEAD was `a249f51` with uncommitted changes" | **Sigue igual**: HEAD `a249f51`, **71 archivos sin commitear**. El remoto es `github.com/jorgecastillo3004/scraper_v3` (GitHub), no GitLab como pide SC1. |

**Consecuencia:** el track apunta a un scraper que ya no es el de producción. Antes de
ejecutar S1 hay que decidir si `scraper_v3` se rescata, se archiva o se declara
reemplazado por `live_v2` + `scraper_V2.0` (local).

---

## 2. Estado por item

### S1 — Secure what exists

**SC1 · `scraper_v3` a GitLab y confirmar que corre** — 🔴 pendiente, premisa a revisar
- Repo remoto actual = GitHub, no GitLab. 71 archivos sin commitear en el servidor.
- El objetivo "confirmar que corre" choca con que está muerto desde marzo y que su
  función la cubre hoy `live_v2`. **Decisión previa:** ¿rescatar o archivar?

**SC2 · Reclamar el disco** — ✅ **HECHO (2026-09-06)**
- Qué eran: **42.947 artefactos de captura de error** en `logs/parallel/screenshots/`
  (21.609 PNG = 3,03 GB + 21.338 volcados `page_source` HTML = **14,72 GB**), de marzo y
  abril de 2026. Los escribe `_save_screenshots` (`paralel_execution.py`) en cada fallo,
  **sin límite ni retención**.
- Por qué no servían: **nada los lee** (verificado en todo el repo: solo escritura), son de
  un scraper parado desde marzo, y capturan un DOM de FlashScore que después cambió
  (`event__time`→`event__stageTime`), así que ni como referencia de depuración valen.
- Qué se conservó: `failed_matches.log` (1,3 MB — liga, `league_id`, `season_id`, partido,
  ronda y URL de cada fallo: información accionable y no reproducible), los JSON de control,
  y un **índice destilado** de las capturas borradas en
  `logs/INDICE_capturas_2026-03_04.tsv.gz` (251 KB, los 42.947 registros con fecha y tamaño).
- Resultado: `scraper_v3` **19 GB → 497 MB**; disco del servidor **95 GB → 77 GB** usados
  (139 → 157 GB libres). `live_v2` no se tocó.
- Qué falló en el diagnóstico del roadmap: decía "18 GB de `logs/`" dando a entender logs de
  texto; los `.log` reales pesan 0 MB. Todo el peso eran capturas.
- **Para que no se repita**: `prune_debug_artifacts()` en `common_functions.py` (retención
  configurable con `SCREENSHOTS_RETENTION_DAYS`, 7 días por defecto), llamada desde
  `paralel_execution.py`, `paralel_players.py` y `paralel_teams.py` (su `history/` tampoco
  se limpiaba; `latest/` ya se vaciaba). Probada: borra >7 días, conserva lo reciente,
  no toca otras extensiones y corre una sola vez por proceso.
- **Ya no se guarda el `page_source`** (2026-09-06, a petición de Jorge): era el 83% del
  disco consumido y nadie lo leía. Eliminado de `paralel_execution._save_screenshots` y
  `paralel_players._save_screenshot`; queda solo la captura PNG, que es lo que sirve para
  ver de un vistazo qué pasó. Los scripts `scripts/_debug_*` y `scripts/test_*` sí lo
  siguen guardando, y ahí es correcto: se ejecutan a mano y a propósito para inspeccionar.
  Verificado por AST (0 llamadas a `open()`, sin referencias a `page_source`) y ejecutando
  la función aislada: genera únicamente el `.png` y nunca pide `page_source`.
- Lo que en `scraper_v3` (servidor) sigue con el código viejo: si alguna vez se revive,
  hay que desplegarle también este cambio.

**SC3 · Convención de `match.status`** — 🟢 **datos ya levantados** (lo que pedía el item)
- Valores reales hoy: `COMPLETED` 9.331 · `SCHEDULED` 1.010 · `OLD_SEASON` 69 · `LIVE` 6.
- Columna `VARCHAR(17)`, **0 constraints**.
- **Ninguna de las dos convenciones documentadas coincide con la realidad:**
  no es `L/S/C` (migración `000001`) ni `SCHEDULED/IN_PROGRESS/COMPLETED/CANCELED/POSTPONE`
  (`Util.txt`). Lo que el scraper escribe es `LIVE` (no `IN_PROGRESS`), y existe un quinto
  valor, **`OLD_SEASON`**, que no está en ningún documento: lo introdujo el scraper para
  marcar temporadas viejas (ver `scores_negativos_y_temporadas.md`).
- 🔴 **Riesgo para el consumidor**: si `POST /bet-pools/check-finished-matches` busca
  `IN_PROGRESS` o `C`, no encuentra nada. Hay que confirmarlo del lado backend.
- Falta: migración con `CHECK` en `core-db` (revisa Angel) — **DDL en producción, requiere OK**.

### S2 — Segundo proveedor (arranca 7-sep)

**SC4 · Evaluar candidatos** — 🟡 adelantado hoy, incompleto
- **Cobertura a cubrir (dato duro para la evaluación):** 114 ligas en la BD, **77 con
  partidos**, 10.416 partidos. Football 49 ligas / 7.302 partidos; Baseball 8/1.040;
  Hockey 14/879; Basketball 14/755; Am. Football 2/372; Tennis 11/64; Boxing 6/2;
  Motor Sport 1/2; Golf 9/0.
- **ESPN** (probado): API JSON pública, sin auth, ~90 ms. Cubre Ecuador, Perú, Colombia,
  Chile, Bolivia, Argentina, Brasil, China, MLB, NBA, NHL, NFL, CFL, tenis, golf, F1.
  **88 % de los nombres de equipo cruzan** con la BD (136 evaluados). **No cubre NPB, KBO,
  LMB ni LIDOM** (HTTP 400) — 1.040 partidos de béisbol en riesgo. Gotcha: devuelve 403 con
  cabeceras de navegador y 200 con el cliente HTTP pelado.
- **SofaScore** (probado): 403 a todo cliente HTTP; **funciona desde el navegador** del
  scraper, y sí cubre NPB. Pero **incumple el criterio 4 del propio roadmap** ("HTTP API
  rather than another site to scrape"): al depender del navegador comparte modo de fallo
  con el primario.
- Faltan por evaluar los cuatro que el roadmap nombra: **API-Football, SportMonks,
  TheSportsDB, football-data.org**.

#### Proveedores evaluados (2026-09-06, verificado contra su documentación y su API)

| Proveedor | Deportes | Plan gratuito | Veredicto |
|---|---|---|---|
| **ESPN** (API no oficial) | los 9 del scraper | sin key, sin límite publicado | 🟢 **candidato**: 88 % de cruce de nombres; **le faltan NPB, KBO, LMB, LIDOM** (1.040 partidos de béisbol) |
| **API-Sports** (api-football.com) | football, baseball, basketball, hockey, NFL, F1, MMA… | **100 req/día por API**, sin tarjeta; pagos desde ~10-19 USD/mes | 🟡 **el más prometedor**: es el único con una API por deporte que cubre los 9. Falta medir su cobertura real de ligas → `scripts/_debug_evaluar_proveedor_apisports.py` (necesita key) |
| **SofaScore** | todos | — | 🔴 403 a todo cliente HTTP; solo funciona desde navegador → **incumple el criterio 4** del roadmap (API HTTP, no otro sitio a scrapear): compartiría modo de fallo con el primario |
| **TheSportsDB** | varios | key pública "3" → **5 ligas en total** | 🔴 su cobertura real está tras pago; con la key libre no sirve |
| **football-data.org** | solo fútbol | 12 competiciones, 10 req/min, **"scores delayed"** | 🔴 doble descarte: de tus ligas solo tendría Brasil Serie A, y el retraso de resultados **incumple el criterio 2** (cierre el mismo día) |
| **SportMonks** | fútbol, cricket, F1 | 2 ligas (Danesa y Escocesa) | 🔴 **no cubre béisbol, baloncesto, hockey ni am. football**: 5 de tus 9 deportes fuera. Desde 29 €/mes |

**Nota sobre el volumen:** 100 req/día no alcanzan para un live cada 60 s (serían ~1.440),
pero el roadmap plantea el segundo scraper **en espera**, con volumen casi nulo hasta que
active — para ese uso el plan gratuito basta, y solo al promocionarse haría falta pagar.

**Siguiente paso concreto:** registrar una key gratuita en
`dashboard.api-football.com/register` y correr el script de cobertura; decide si
API-Sports cubre el hueco de béisbol que ESPN deja.

**SC5 · Escribir la decisión** — ⚪ no empezado (depende de cerrar SC4).

### S3 a S7 — 🔴 no empezados
SC6/SC7 (mapping + migración), SC8/SC9 (ingesta), SC10/SC11 (staleness + failover),
SC12/SC13 (scheduler + monitoring), SC14 (runbook).

**Nota sobre SC12:** parcialmente hecho sin saberlo — `live_v2` ya está bajo systemd con
`Restart=always`. Falta el **límite de memoria** que pide el item; hoy el control de RAM lo
hace el propio scraper (reciclaje del navegador con umbral de 3 GB, arreglado el 6-sep),
no una directiva `MemoryMax` de systemd.

**Nota sobre SC13:** el servidor **ya corre Loki, Prometheus y Grafana** (verificado entre
los procesos), así que la infraestructura del item existe; falta enviar los logs y el panel.

---

## 3. Estado de cada item (actualizado 2026-09-06, fin de sesión)

| Item | Estado | Qué falta |
|---|---|---|
| **SC1** subir `scraper_v3` y confirmar que corre | 🟡 parcial | GitLab ya es accesible (clave registrada) y `scraper_V2.0` está subido a `wohhu/scrapper`. Pero `scraper_v3` sigue solo en el servidor: 71 cambios sin commitear, HEAD de **oct-2025**, muerto desde marzo. **Decisión pendiente: rescatarlo o archivarlo** |
| **SC2** reclamar el disco | ✅ **hecho** | — (19 GB → 497 MB; retención de 7 días + sin `page_source`) |
| **SC3** convención de `match.status` | 🟡 parcial | Diagnóstico hecho: `COMPLETED/SCHEDULED/OLD_SEASON/LIVE`, sin `CHECK`, y **ninguna** de las dos convenciones documentadas coincide. Falta **confirmar qué valor lee el backend** y la migración con `CHECK` — no hay repo `core-db` en esta máquina |
| **SC4** evaluar proveedores | ✅ **hecho** | — (6 evaluados con datos reales; SofaScore elegido) |
| **SC5** escribir la decisión | ✅ **hecho** | `documentacion/proveedor_respaldo_evaluacion.md`. Falta presentarlo y que lo firme quien corresponda |
| **SC6** diseñar la capa de mapeo | 🟢 funcionando | Implementada con **archivos** (`sofascore_map.json`, `sofascore_teams_map.json`, `sofascore_overrides.json`): 12 ligas y 202 equipos, verificados por equipos. El roadmap pedía una **tabla `source_entity_map`**: decidir si se migra a BD o se queda en archivos |
| **SC7** migración de mapeo y heartbeat | 🔴 pendiente | Depende de `core-db` y de la revisión de Angel |
| **SC8** ingesta de datos de referencia | 🔴 pendiente | No hace falta para el respaldo del Live (solo actualiza partidos existentes); sí para cubrir competiciones nuevas |
| **SC9** ingesta de partidos y resultados | 🟡 parcial | El **modo comparación** que pedía el item ya existe y funciona (`comparar_sofascore_hoy.py`, `validar_sofascore.py`): 139/144 partidos, 0 discrepancias. Falta **la escritura real** |
| **SC10** detector de obsolescencia | ✅ **hecho** | 4 señales (sonda activa de FlashScore, latido, colgados, atraso), umbrales calibrados con el ciclo real |
| **SC11** conmutación | 🟡 parcial | Simulador completo: conmuta, enumera lo que escribiría y devuelve el mando. Falta **permiso de escritura** y el **candado de escritor único** (P7) |
| **SC12** scheduler | 🟡 parcial | systemd con `Restart=always` + linger ya está. Falta el **límite de memoria** (`MemoryMax`) que pide el item |
| **SC13** monitorización | 🔴 pendiente | Loki, Prometheus y Grafana **ya corren** en el servidor: falta enviar los logs y el panel "cuándo escribió cada fuente por última vez" + alerta |
| **SC14** runbook y traspaso | 🔴 pendiente | Hay mucha documentación técnica, pero falta el runbook de operación de **ambos** scrapers y la sesión en vivo |

### Pendientes propios que deja esta sesión

- **Desplegar el arreglo del heartbeat** (`main2.py`) al servidor: hoy `run_status_live.json`
  conserva la marca del arranque y no sirve como señal de vida.
- **Cerrar P7 (un solo escritor)**: bloquea que la conmutación pueda escribir de verdad.
- **15 partidos** en `FOOTBALL/WORLD_World Cup` que en realidad son de baloncesto
  (AfroBasket / FIBA Asia Cup) creados en la liga equivocada: requieren reclasificación.
- **Merge request en `wohhu/scrapper`**: `main` está protegida y el push directo se rechaza;
  el trabajo está en la rama `fix/live-memoria-y-sesion`.
- Ligas sin mapear: 7 de hockey, y tenis / boxeo / motor sport (sin actividad o estructura
  distinta).

## 3. Orden propuesto

1. **Decidir el destino de `scraper_v3`** (bloquea SC1 y SC2, y aclara de qué habla el track).
2. **SC2**: recuperar los 18 GB (requiere OK para borrar).
3. **SC3**: cerrar la convención de `status` — verificar qué lee el backend, luego la
   migración con `CHECK` (revisa Angel).
4. **SC4**: completar la evaluación con los cuatro proveedores del roadmap y decidir con
   el criterio "API HTTP" por delante, que hoy favorece a ESPN sobre SofaScore.
