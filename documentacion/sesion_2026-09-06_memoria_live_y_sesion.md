# Sesión 2026-09-06 — Fuga de memoria del live + sesión sin login

## 1. Fuga de memoria del live del servidor (RESUELTO)

### Síntoma
Servicio `scraper-live` sano (6 d 13 h, 0 reinicios) pero el `Web Content` de Firefox
en **7,9 GB RSS**; el server (11,9 GB, compartido con grafana/prometheus/loki) quedaba
con 1,9 GB disponibles. Ritmo ≈ 1,2 GB/día → OOM a la vuelta de un par de días.

### Causa raíz
`main2.py`, primera línea de `_maybe_recycle_live()`:

```python
if _OWN_DRIVER:
    return driver          # ← el reciclaje solo corría con el driver del PANEL
```

- En local el live se **reengancha** al driver del panel (`_OWN_DRIVER=False`) → reciclaba.
- En el servidor **no hay panel**: el live crea su propio navegador (`_OWN_DRIVER=True`)
  → salía en la primera línea y **nunca reciclaba**. El log lo decía sin notarlo:
  `Reciclado de driver por memoria: ACTIVO` seguido de `lanzando navegador propio`.
- Refuerzo del mismo bug: `driver_tree_pss_mb()` mide a partir del `launcher_file` del
  panel, inexistente en modo propio → habría devuelto `0.0` y tampoco habría reciclado.

### Por qué crece la memoria (no es una fuga nuestra)
1. Sesión de navegador eterna: el mismo proceso navega FlashScore cada 60 s, 9 deportes.
2. FlashScore es una SPA con feed en vivo: reemplaza contenido por JS y recibe updates
   por WebSocket; deja nodos DOM, listeners y objetos que el GC no puede liberar porque
   la propia app los sigue referenciando.
3. Un solo proceso de contenido por origen, que nunca se cierra (no hay pestañas que cerrar).
4. El RSS es marca de agua: Firefox devuelve poco al SO por fragmentación del heap.

→ El remedio correcto es **reciclar el navegador**, no perseguir el leak del sitio.

### Fix aplicado
- `scripts/driver_session.py`: `tree_pss_mb(pid)` mide el árbol de procesos que cuelga de
  un PID; `driver_tree_pss_mb(launcher_file)` pasa a ser un envoltorio suyo.
- `main2.py`:
  - `MEM_LIMIT_MB` default **3000** (era 6000), env `DRIVER_MEM_LIMIT_MB`.
  - `_live_mem_mb()` mide según el modo: launcher del panel, o **PID propio** (standalone).
  - `_hotswap_own_driver()`: hot-swap del driver propio — levanta y **verifica** el
    navegador nuevo antes de cerrar el viejo; si el nuevo falla, conserva el viejo.
  - `_close_own_driver()`: cierra el driver vivo tras un hot-swap (antes la referencia
    del llamador apuntaba al viejo y el nuevo quedaba huérfano al salir del loop).

### Efecto medido en el servidor (2026-09-06)
RAM usada 8.289 MB → **2.812 MB**; disponible 1.976 MB → **9.142 MB**.

## 2. Abrir el navegador ya logueado (sin formulario)

Con umbral de 3 GB el reciclaje cae cada 1–2 ciclos, así que repetir el login sería caro
y arriesgado (FlashScore puede frenar reintentos seguidos).

### Dónde vive la sesión — verificado empíricamente
**No está en las cookies.** Las 9 cookies del dominio son de consentimiento y analítica
(OneTrust, `_ga`, `__gads`…). La sesión vive en **`localStorage`**, claves `lsid_*`
(LiveSport ID): `lsid_hash` (40 chars) + `lsid_id` son el token; también `lsid_email`,
`lsid_innerData` (preferencias: `myLeagues`, `lsSettins`). Sin caducidad declarada en
cliente — la valida el servidor.

### Solución: sesión en JSON, no perfil de Firefox
Se descartó el perfil persistente (`enable_profile` / `-profile`):
- un directorio de perfil admite **una sola instancia** (lock) y el hot-swap tiene los
  dos navegadores vivos a la vez → el nuevo no arrancaría;
- `enable_profile` usa `FirefoxProfile(ruta)`, que **copia** el perfil a un temporal y
  nunca escribe de vuelta (además la ruta estaba hardcodeada a `/home/jorge/...`).

Nuevas funciones en `src/common_functions.py` (`tmp/fs_session.json`, ya en .gitignore):
`is_logged_in` · `dump_fs_session` · `save_fs_session` · `load_fs_session` ·
`apply_fs_session` · `ensure_login`.

`ensure_login(driver, email, password, session=None)` resuelve en este orden:
1. **ya logueado** → refresca el JSON;
2. **sesión reutilizable** → la inyecta (cookies + localStorage) y recarga. En el
   hot-swap se pasa la del driver **viejo** (`session=`), más fresca que la de disco;
3. **login por formulario** → y guarda la sesión para la próxima.

Usada en `main2._launch_own_driver()` y en `scripts/start_driver.py` (driver del panel).

### Medido en local
| camino | tiempo |
|---|---|
| login por formulario | 13,3 s |
| restaurar sesión     | **1,5 s** |

Pruebas: `scripts/_debug_session_reuse.py` (login → guardar → driver nuevo restaurado) y
`scripts/_debug_hotswap_own.py` (hot-swap real: driver nuevo logueado sin formulario,
viejo cerrado, `_CURRENT_OWN_DRIVER` correcto, memoria 1.423 → 71 MB al cerrar).
En el servidor el primer arranque no tenía JSON → hizo un login y guardó su sesión.

## 3. Pendientes que deja esta sesión
- Observar el primer reciclaje real en el servidor: debe loguear
  `[RECICLAJE] CAUSA=MEMORIA … hot-swap` y luego `[Sesión] restaurada sin login`.
- Si reciclara demasiado seguido, subir `DRIVER_MEM_LIMIT_MB` a 3500–4000 en `run_live.sh`.
- Backups en el servidor: `main2.py.bak_20260906`, `scripts/driver_session.py.bak_20260906`,
  `src/common_functions.py.bak_20260906`.
- Sigue abierto: tenis en `[DB-SKIP]` (creación no cableada al live), 17 partidos colgados
  en `status=LIVE`, y el resto de `pendientes_puesta_en_marcha.md`.
