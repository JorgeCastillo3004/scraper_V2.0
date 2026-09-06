# Sesión 2026-09-06 — Estado al cerrar y por dónde seguir

> Punto de partida de la próxima sesión. Todo lo de aquí está **verificado**, no supuesto.

---

## 1. Qué quedó funcionando

| Área | Estado |
|---|---|
| **Live en el servidor** | `active` + `enabled`, `Restart=always` (15 s), **`Linger=yes`** → sobrevive a fallos del proceso y a reinicios del servidor. 10 h sin interrupción, **0 reinicios necesarios** |
| **Memoria del navegador** | Reciclaje arreglado (antes no reciclaba nunca en el servidor). Umbral 3 GB. RAM del server **8.289 → 2.812 MB** |
| **Sesión sin login** | El navegador nuevo abre ya logueado: **13,3 s → 1,5 s** |
| **Partidos pendientes** | **875 → 15**. Colgados en `LIVE`: **24 → 0** |
| **Disco** | **18 GB recuperados** + retención de 7 días + se deja de guardar el `page_source` |
| **Respaldo (SofaScore)** | 12 ligas y 202 equipos mapeados en 5 deportes; **139/144 partidos (97 %)**, **0 discrepancias**. Solo lectura |
| **Detector + conmutación** | Detector con 4 señales y simulador del ciclo completo. No escribe en la BD |
| **Avisos por Telegram** | Cableado listo: fallos + **resumen horario**. Inerte hasta que haya credenciales |

## 2. Lo primero al retomar

1. **Credenciales de Telegram** (las trae Jorge). Ponerlas en `config.py` —local y
   servidor— y comprobar con:
   `sports_env/bin/python scripts/_debug_probar_telegram.py`
2. **Desplegar `main2.py` al servidor**: lleva tres cosas sin desplegar —heartbeat por
   ciclo, avisos de fallo y resumen horario—. Requiere reiniciar `scraper-live.service`.
3. **Noticias: llevan 57 días sin ejecutarse** (última: 2026-07-11). La configuración
   dice `ENABLED: true, EVERY_HOURS: 24`, pero **quien las dispara es el scheduler del
   panel**, y en el servidor solo corre el live. Ver punto 4.

## 3. Bloqueado por una decisión

| Qué | Bloquea |
|---|---|
| ¿`scraper_v3` se rescata o se archiva? Lleva muerto desde marzo, 71 cambios sin commitear | SC1 |
| **P7 — un solo escritor** (local y servidor escriben en la misma BD) | Que el respaldo pueda escribir (SC11) |
| Acceso al repo `core-db` | SC3 (migración `CHECK`) y SC7 |
| Permisos en `wohhu/scrapper` (`main` protegida, rol Developer) | Integrar el trabajo en su rama principal |

## 4. Siguiente trabajo, por valor

1. **SC13 — monitorización**: Loki, Prometheus y Grafana **ya corren** en el servidor.
   Falta enviarles los logs y montar el panel de "cuándo escribió cada fuente".
2. **P3 — probar el engine en local** (`scripts/engine_runner.py`, escrito y nunca
   ejecutado). Es lo que resolvería las noticias *y* las inconsistencias en el servidor,
   en vez de parchear cada una por separado.
3. **SC12** — `MemoryMax` en la unidad systemd (~30 min).
4. **15 partidos** en `FOOTBALL/WORLD_World Cup` que son de baloncesto (AfroBasket /
   FIBA Asia Cup) creados en la liga equivocada: requieren `UPDATE` de `league_id`.
5. Ligas del respaldo sin mapear: 7 de hockey, tenis, boxeo y motor sport.

## 5. Comandos que hacen falta

```bash
# Drivers (se quedan vivos; los scripts se reenganchan)
./scripts/start_sofascore.sh                       # respaldo, visible
sports_env/bin/python scripts/start_driver.py \
    --session-file tmp/flashscore_probe.json --url https://www.flashscore.com \
    --sin-login --lightweight --headless --profile-dir tmp/profiles/fs_probe

# Comparar el respaldo con lo que escribió FlashScore
sports_env/bin/python scripts/comparar_sofascore_hoy.py
sports_env/bin/python scripts/live_sofascore_extract.py --deporte todos --loop 60

# ¿Está FlashScore actualizando?
sports_env/bin/python scripts/staleness_detector.py --con-sonda

# Ensayar la conmutación (no escribe nada)
sports_env/bin/python scripts/failover_simulator.py --reset --simular-caida --recuperar-en 5 --lecturas 11

# Estado del servidor
ssh scraper_server 'systemctl --user status scraper-live.service'
```

## 6. Hallazgos que conviene no olvidar

- **La hora de los partidos `SCHEDULED` es un placeholder**: toda la jornada con el mismo
  `start_time`. Solo tienen hora real los que el live ya tocó. Afecta a cualquier cosa
  que dependa de la hora de un partido futuro.
- **`run_status_live.json` no late**: conservaba la marca del arranque 8 h después. La
  señal de vida buena es el `mtime` de `live_persist.log` (arreglado, sin desplegar).
- **El nombre de una liga puede mentir**: lo que la BD llama `WORLD/World Cup` de
  baloncesto es la `FIBA World Cup Qualification, Europe`. Por eso el mapeo se **verifica
  por equipos**, no por nombre.
- **Pedir una fecha a SofaScore no devuelve solo esa fecha**, y en béisbol el mismo
  enfrentamiento se repite días seguidos: sin filtrar por la fecha real del evento se
  escribiría el marcador del juego equivocado.
- **`match_detail` se ordena por `home DESC`**, nunca por `match_detail_id` (es un UUID y
  ordena alfabéticamente, invirtiendo el marcador).
