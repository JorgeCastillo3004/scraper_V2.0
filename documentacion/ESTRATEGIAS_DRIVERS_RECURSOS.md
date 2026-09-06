# Estrategias de drivers y recursos — minimizar RAM, crear/cerrar bien, no abrir de más

> Creado 2026-06-13. Complementa [AGENTE_MEMORIA.md](AGENTE_MEMORIA.md) (que es la spec del
> agente de medición/reducción). Este documento es el **diseño**: por qué queda un driver
> ocioso, cómo se crean/cierran hoy, y estrategias concretas. A revisar juntos antes de codear.
> Reglas del driver: [../docs/DRIVER_RULES.md](../docs/DRIVER_RULES.md) (no negociables).

## 1. Por qué quedó un driver OCIOSO (diagnóstico medido)

Estado 2026-06-13: 2 drivers del scraper vivos — **corrección** (`:46755`, **3.45 GB, idle 10h**)
y **live** (`:40741`, 1.9 GB, en uso). (Hubo un 3er geckodriver efímero colgando de `claude`
que se limpió solo — ver §5 huérfanos.)

**Causa raíz:** el driver de corrección se lanza desde el panel (Inconsistencias → "Iniciar
driver") vía `driver_manager.DriverManager.start()` → `start_driver.py` **detached**
(`start_new_session=True`, reparenta a systemd → sobrevive reinicios de la API). Se diseñó para
**reusarse** entre correcciones (fix_results, update_matches, crear_fixtures todos lo reusan),
pero **NO existe ninguna lógica que lo cierre cuando deja de usarse**: queda vivo hasta que el
usuario aprieta "Matar driver". Sin operación activa → 10h ocioso ocupando 3.45 GB.

**Agravante:** el de corrección se crea con `lightweight=False` (en `DriverManager.__init__`;
solo el live usa `lightweight=True`). Sin las prefs de bajo consumo carga imágenes y abre más
procesos `contentproc` (21 en el árbol) → 3.45 GB vs 1.9 GB del live.

## 2. Cómo se crean/cierran los drivers HOY

| Mecanismo | Crear | Cerrar |
|---|---|---|
| **DriverManager** (panel: corrección + live) | `start()` = Popen `start_driver.py` detached. **Guard anti-doble**: si el launcher ya corre, no abre otro. | `stop()` = **SIGTERM al launcher** → `start_driver.on_exit` hace `driver.quit()` de SU Firefox + borra session file. Limpio, **sin pkill**. |
| **hotswap()** (reciclado por memoria) | abre nuevo, valida sesión, recién ahí | SIGTERM al viejo |
| **Reuso** (fix/update/crear_fixtures) | `ensure_logged_driver` / `get_or_launch_driver(reuse=True)` → **adjunta** al de corrección | no lo cierran (es compartido) |
| **Scripts standalone** (run_news, run_leagues, paralel_*) | `launch_navigator()` headless propio | `driver.quit()` al terminar el script |

Hechos clave:
- El **live** ya tiene reciclado por memoria + prefs lightweight + hotswap. **Sano.**
- El de **corrección NO** tiene: ni idle-stop, ni reciclado por memoria, ni lightweight.
- Cierre correcto = **SIGTERM al `start_driver.py`** (él hace `quit()`); jamás `pkill`/`kill -9`.

## 3. Estrategias para minimizar el consumo (priorizadas)

**A. Auto-stop por inactividad del driver de corrección (mayor impacto, -3.45 GB).**
   Marcar "último uso" cada vez que un flujo lo usa (fix/update/extract). Un watchdog ligero
   (scheduler ya existente) lo **detiene** (vía `stop()` limpio) si lleva > N min idle. Se
   re-levanta on-demand cuando el panel inicia la próxima corrección (~10-40s de login).

**B. Prefs lightweight también en corrección.** Pasar `lightweight=True` a su instancia de
   `DriverManager` (o un flag en el panel). Baja imágenes/procesos como el live.

**C. Reciclado por memoria en corrección** (reusar el mecanismo del live: umbral PSS → hotswap).
   Útil si se prefiere mantenerlo vivo en vez de auto-stop.

**D. On-demand real:** no dejar el driver de corrección "por las dudas". Levantarlo al iniciar
   una operación de fix/extract y bajarlo al terminar (con un *grace* de unos min por si encadena
   varias correcciones). Es la versión fuerte de (A).

**E. Headless cuando no se necesita ver.** Headless ahorra RAM/GPU. Dejar visible solo cuando el
   usuario está mirando; default headless para corridas desatendidas.

**F. Un solo driver compartido** para todos los flujos de fix/extract (ya es así; reforzar que
   ninguno haga fallback a "driver propio" si hay uno gestionado vivo — ver §6).

## 4. Creación correcta de drivers (qué garantizar)

- **Punto único gestionado:** todo lo del panel pasa por `DriverManager.start()` (guard
  anti-doble ya presente). Mantenerlo como única puerta.
- **Idempotencia:** chequear `status()` antes de crear; si hay sesión viva, **adjuntar**
  (`get_driver()` / `_reuse_driver_session()`), nunca lanzar otro.
- **Login una vez:** `start_driver.py` hace login y guarda session file; los flujos adjuntan a
  esa sesión (no re-login, no re-lanzar).
- **Lightweight por defecto** salvo que se necesite ver imágenes.

## 5. Cierre correcto de drivers (qué garantizar)

- **Siempre** SIGTERM al `start_driver.py` (él hace `driver.quit()` + borra session). Nunca
  `pkill`/`kill -9` de firefox/geckodriver, nunca `driver.quit()` directo desde otro proceso,
  **sin confirmación explícita** (regla del proyecto).
- Tras cerrar: limpiar `tmp/*_session.json` y `tmp/*_launcher.json`.
- **Reaper de huérfanos:** geckodriver/firefox que NO tengan un `start_driver.py` padre vivo
  NI estén referenciados por un session file (ej. el 3er driver efímero colgando de `claude`).
  Detectar y **reportar**; cerrar solo con confirmación. Lógica de detección ya bosquejada en
  `scripts/auto_repair_matches.py` (busca `start_driver.py` huérfanos).

## 6. Evitar abrir drivers innecesarios

- **Reforzar el reuse-first:** los flujos que hoy pueden hacer fallback a "driver propio"
  (`get_or_launch_driver(reuse=False)`, `--no-reuse`, `own_driver=True`) deben **primero**
  verificar si hay un driver gestionado vivo y adjuntarse. Lanzar propio solo si el gestionado
  está realmente ocupado/muerto.
- **Nunca relanzar "para empezar limpio"** (anti-patrón de DRIVER_RULES).
- **No duplicar entre corrección y live:** son 2 a propósito (uno corrige, otro vive). No crear
  un tercero para tareas puntuales: usar el de corrección (attach).
- **Scripts standalone:** que cierren su driver (`quit()`) al terminar — verificar que no quede
  ninguno colgado tras corridas de run_news/run_leagues/paralel_*.
- **Guard anti-doble** ya existe en `start()`; mantenerlo y replicarlo en cualquier launcher nuevo.

## 7. Reglas no negociables (recordatorio)
- Jamás `pkill`/`kill -9` geckodriver/firefox sin confirmación EXPLÍCITA.
- Jamás `driver.quit()`/`close()` sin confirmación; el cierre va por SIGTERM al `start_driver.py`.
- Jamás matar el **Firefox de escritorio del usuario** (no es del scraper; ppid = sesión del user).
- Jamás DELETE/DROP/TRUNCATE en la BD.

## 8. Acciones concretas propuestas (mapean a la Tarea del agente de memoria)
1. `idle_since` por driver gestionado + **auto-stop del de corrección** por idle (estrategia A) —
   el de mayor impacto (-3.45 GB).
2. `lightweight=True` en la instancia de corrección (B).
3. (Opción) reciclado por memoria en corrección reusando el del live (C).
4. Reaper de huérfanos read-only + reporte en el panel (§5).
5. Endurecer reuse-first en los fallbacks `--no-reuse`/`own_driver` (§6).
6. `scripts/mem_report.py` (de [AGENTE_MEMORIA.md](AGENTE_MEMORIA.md)) para medir antes/después.

## 9. Pendiente próxima sesión
- Decidir política del driver de corrección: **auto-stop por idle (A/D)** vs **reciclado por
  memoria (C)**. Recomendación: A + B (auto-stop idle + lightweight) = simple y libera 3.45 GB.
- Definir umbrales: minutos de idle, PSS por driver.
- Confirmar reaper de huérfanos (siempre con confirmación para cerrar).
