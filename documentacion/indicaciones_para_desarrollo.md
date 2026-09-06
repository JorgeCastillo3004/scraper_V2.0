# Indicaciones generales de desarrollo y testing

Guía para cualquier prueba o desarrollo sobre el scraper. Aplica tanto a
exploración rápida ("ver qué devuelve este XPath") como a scripts de
producción largos (cientos o miles de items procesados desatendidamente).

**Principio fundamental:** ahorrar tiempo de desarrollo. Cada login a
FlashScore + navegación cuesta 30–60 segundos. Multiplicado por iteraciones
de prueba, se vuelve el cuello de botella. El flujo entero está diseñado
para evitar esos costos fijos.

---

## 1. Resumen del flujo

```
┌──────────────────────────────────────────────────────────────────┐
│ Paso 0 — UNA sola vez por sesión de trabajo                      │
│   python scripts/start_driver.py                                 │
│   → abre Firefox, login, guarda tmp/driver_session.json,         │
│     queda activo en su terminal con while True                   │
└──────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌───────────────────────────┐         ┌───────────────────────────┐
│ Scratchpad (test rápido)  │         │ Script definitivo         │
│ scripts/_debug_<tema>.py  │         │ scripts/<funcionalidad>.py│
│                           │         │                           │
│ from driver_session       │         │ from driver_session       │
│   import get_driver       │         │   import get_driver       │
│ d = get_driver()          │         │ d = get_driver()          │
│ # probar lineas sueltas   │         │ # logica completa con     │
│ # iterar sin reiniciar    │         │ # logs + heartbeat +      │
│                           │         │ # checkpoints + idempotencia │
└───────────────────────────┘         └───────────────────────────┘
              │                                     ▲
              │   funciones validadas → migrar      │
              └─────────────────────────────────────┘
```

Cualquier script (scratchpad o definitivo) **se conecta al mismo driver**
vía `get_driver()`. Nadie abre un Firefox nuevo. Nadie cierra el browser.

---

## 2. Reglas obligatorias del driver

📖 **Referencia completa:** `docs/DRIVER_RULES.md` (autoridad central).

Resumen no negociable:

| Acción | Por qué no |
|---|---|
| `driver.quit()` / `driver.close()` del browser | Cierra la sesión que el usuario u otro script están usando |
| `pkill` / `kill -9` sobre geckodriver/firefox | Mata sesiones activas — re-crearlas cuesta minutos + login |
| Lanzar otro browser "para empezar limpio" | Compite por RAM, deja huérfano al original |
| `webdriver.Remote(...)` directo sin `get_driver()` | Crea sesión nueva, no se adjunta a la existente |

Antes de cualquier `kill`, `quit`, `close` o relaunch sobre geckodriver/firefox:
**pedir confirmación explícita al usuario.**

---

## 3. Crear el driver — `scripts/start_driver.py`

Se ejecuta UNA vez al empezar a trabajar (idealmente en una terminal
dedicada que dejas abierta todo el día):

```bash
cd /home/jorge/work/scraper_V2.0
python scripts/start_driver.py
```

Qué hace:

1. Lanza Firefox (no headless) vía `launch_navigator`.
2. Hace login en FlashScore con credenciales de `config.py`.
3. Guarda `tmp/driver_session.json` con:
   ```json
   { "session_id": "...", "executor_url": "http://localhost:NNNN" }
   ```
4. Queda activo con `while True: time.sleep(5)`.
5. Ctrl+C → cierra el browser y borra el JSON limpiamente.

> Para corridas desatendidas: lanzar con `nohup python scripts/start_driver.py
> > logs/start_driver_$(date +%F).log 2>&1 &` y seguir con `disown`.

---

## 4. Conectarse al driver — `scripts/driver_session.py`

Cualquier script que necesite Selenium importa `get_driver`:

```python
import sys, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By

driver = get_driver()                    # se adjunta al driver vivo
print('estoy en:', driver.current_url)   # confirmar conexión
# ... usar driver normalmente ...
# NUNCA driver.quit() al terminar
```

`get_driver()`:

- Lee `tmp/driver_session.json`.
- Usa un patch temporal de `WebDriver.execute` para interceptar
  `newSession` y forzar el `session_id` existente.
- Si el archivo no existe → `FileNotFoundError` con mensaje claro:
  "Ejecuta primero `python scripts/start_driver.py`".

---

## 5. Patrón scratchpad → definitivo

Trabajar como en un notebook pero con scripts persistidos.

### 5.1 Scratchpad

Crear `scripts/_debug_<tema>.py` (prefijo `_debug_` = scratchpad, fácil de
ignorar en limpieza). Plantilla mínima:

```python
"""
_debug_<tema>.py — pruebas iterativas para <tema>.
NO toca nada en DB ni hace cambios destructivos.
"""
import sys, os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from driver_session import get_driver
from selenium.webdriver.common.by import By

d = get_driver()
print('current_url:', d.current_url)

# === Bloque de prueba 1 — ejemplo: extraer team URLs de un match ===
d.get('https://www.flashscore.com/match/<id>/#/match-summary/match-summary')
links = d.find_elements(By.XPATH, "//a[contains(@class,'participant__participantName')]")
print('encontrados:', [l.get_attribute('href') for l in links])

# === Bloque de prueba 2 — siguiente cosa que quiero validar ===
# ...
```

Ejecutar tantas veces como hagan falta:
```bash
python scripts/_debug_<tema>.py
```

Cada corrida reusa el mismo driver; cambios al código son re-cargados
automáticamente.

### 5.2 Script definitivo

Cuando los bloques del scratchpad funcionan:

1. Crear `scripts/<funcionalidad>.py` con la lógica completa.
2. Copiar las funciones validadas desde el scratchpad.
3. Añadir: argparse, logs estructurados, heartbeat, checkpoint,
   manejo de errores (ver §6, §7, §8).
4. Probar con un subset pequeño primero (e.g., `--limit 5` o
   `--match-id <uno>`), luego escalar.

### 5.3 Cuando algo falla en el script definitivo

```
Script definitivo falla en item X stage Y
        ↓
Mirar logs / tmp/run_status_<script>.json
        ↓
Reproducir el caso en scratchpad:
  - cambiar el item de ejemplo a X
  - copiar las líneas que fallaron
  - ejecutar contra el driver vivo
        ↓
Iterar hasta entender el problema
        ↓
Aplicar fix al script definitivo
        ↓
Re-lanzar — el checkpoint hace que continúe desde X
sin reprocesar lo anterior
```

---

## 6. Logs estructurados (registrar punto de fallo)

Para poder ubicar dónde falló un script desatendido, los logs deben ser
**parseables**.

### 6.1 Opción simple — prefijos consistentes

```python
print(f'[OK]     item={item_id} stage=extract')
print(f'[ERROR]  item={item_id} stage=team_lookup err={e}')
print(f'[CREATED] team={name}')
```

Contar con `grep -c`:
```bash
grep -c '\[OK\]'    logs/run.log
grep -c '\[ERROR\]' logs/run.log
grep '\[ERROR\]'    logs/run.log | head
```

### 6.2 Opción robusta — JSONL

Cada línea es un JSON con campos fijos:

```python
import json, datetime
def jlog(level, stage, **fields):
    print(json.dumps({
        'ts':    datetime.datetime.utcnow().isoformat(timespec='seconds'),
        'level': level,
        'stage': stage,
        **fields,
    }))

jlog('INFO',  'scan',    league='AFRICA', found=42)
jlog('ERROR', 'extract', item=match_id, err=str(e))
```

Filtrar con `jq`:
```bash
cat logs/run.jsonl | jq 'select(.level=="ERROR")'
cat logs/run.jsonl | jq -r 'select(.stage=="extract") | .item' | sort -u | wc -l
```

---

## 7. Heartbeat (estado en vivo del script)

Aparte del log completo, un archivo de 1 línea sobreescrito cada N items.
Permite chequear el estado al instante sin grep al log de varios MB.

```python
HEARTBEAT_PATH = f'tmp/run_status_{SCRIPT_NAME}.json'

def update_status(stage, current_item, processed, ok, err, remaining):
    with open(HEARTBEAT_PATH, 'w') as f:
        json.dump({
            'updated':      datetime.datetime.utcnow().isoformat(timespec='seconds'),
            'stage':        stage,
            'current_item': current_item,
            'processed':    processed,
            'ok':           ok,
            'err':          err,
            'remaining':    remaining,
        }, f, indent=2)
```

Llamar `update_status(...)` después de cada item procesado.

Monitor desde otra terminal:
```bash
watch -n 5 'cat tmp/run_status_<script>.json | jq .'
```

Detectar "stuck" (no avanza en 10 min):
```bash
while sleep 60; do
  age=$(( $(date +%s) - $(date +%s -d "$(jq -r .updated tmp/run_status_<script>.json)") ))
  [ $age -gt 600 ] && echo "STUCK ${age}s — current_item: $(jq -r .current_item tmp/run_status_<script>.json)" && break
done
```

---

## 8. Checkpoints (resumibilidad)

Para no reprocesar items ya completados al reiniciar.

### 8.1 En DB (recomendado para producción)

Tabla `script_checkpoint`:
```sql
CREATE TABLE script_checkpoint (
    script_name  VARCHAR NOT NULL,
    item_id      VARCHAR NOT NULL,
    stage        VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,  -- 'in_progress' | 'completed' | 'error'
    last_error   TEXT,
    updated_at   TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (script_name, item_id)
);
```

Al iniciar el script:
```python
cur.execute("""
    SELECT item_id, stage, status FROM script_checkpoint
    WHERE script_name = %s AND status != 'completed'
    ORDER BY updated_at
""", (SCRIPT_NAME,))
resume_from = cur.fetchall()  # items pendientes / con error / in_progress
```

Después de cada stage exitoso del item:
```python
cur.execute("""
    INSERT INTO script_checkpoint (script_name, item_id, stage, status)
    VALUES (%s, %s, %s, 'in_progress')
    ON CONFLICT (script_name, item_id) DO UPDATE
      SET stage = EXCLUDED.stage, status = 'in_progress',
          updated_at = NOW()
""", (SCRIPT_NAME, item_id, stage))
```

Al completar el item:
```python
cur.execute("""
    UPDATE script_checkpoint SET status = 'completed', updated_at = NOW()
    WHERE script_name = %s AND item_id = %s
""", (SCRIPT_NAME, item_id))
```

### 8.2 En JSON (recomendado para scripts puntuales)

`check_points/<script_name>_checkpoint.json`:
```json
{
  "completed": ["item_1", "item_2", ...],
  "last_failed": { "item": "item_42", "stage": "team_lookup", "error": "..." }
}
```

Más simple, menos atómico (no resiste crashes mid-write).

---

## 9. Idempotencia

Cada operación debe ser **segura de repetir**. Antes de cualquier escritura
en DB o JSON, verificar "ya existe":

```python
# MAL — duplica al re-correr
cur.execute("INSERT INTO team (...) VALUES (...)", (...))

# BIEN — UPSERT
cur.execute("""
    INSERT INTO team (team_id, team_name, ...) VALUES (%s, %s, ...)
    ON CONFLICT (team_id) DO NOTHING
""", (...))

# o consulta + condicional
cur.execute("SELECT 1 FROM team WHERE team_name=%s AND sport_id=%s", (name, sport_id))
if not cur.fetchone():
    cur.execute("INSERT INTO team (...) VALUES (...)", (...))
```

Lo mismo aplica a archivos JSON: leer antes, mergear, escribir; nunca
sobreescribir asumiendo "está vacío".

Beneficio: tras un crash, re-correr el script no duplica datos. Combinado
con checkpoint (§8) y heartbeat (§7), un fallo nunca obliga a empezar de
cero.

---

## 10. Failure modes generales

| Tipo de error | Causa común | Acción del script |
|---|---|---|
| `TimeoutException` (Selenium) | Página lenta o caída transitoria | retry 1 vez con `WebDriverWait` el doble; si falla → log + skip + checkpoint |
| `NoSuchElementException` | HTML del sitio cambió | log con snapshot HTML (`driver.page_source[:5000]`) + skip + alerta |
| `ConnectionError` o `OperationalError` (DB) | Postgres reinició / red intermitente | `ensure_connection()` + retry hasta 3 veces con backoff |
| Driver no responde (`Message: ` vacío) | geckodriver colgado | log + halt + alerta al usuario — **NO matar driver sin confirmación** |
| Item ya procesado | Re-corrida tras crash | skip silencioso + log INFO |
| Cualquier otra excepción | No anticipada | log con traceback completo + halt + alerta |

Cualquier `[ERROR]` que no encaje en la tabla debe interrumpir el lote y
notificar (no continuar a ciegas).

---

## 11. Operación desatendida (correr horas)

```bash
# Lanzar en background con log JSONL y heartbeat
nohup ./env_sports/bin/python -u scripts/<funcionalidad>.py --apply \
      > logs/<script>_$(date +%F_%H%M).jsonl 2>&1 &
disown

# Monitor del heartbeat
watch -n 30 'cat tmp/run_status_<script>.json | jq .'

# Tail del log
tail -f logs/<script>_*.jsonl | jq -c .
```

Si el heartbeat se detiene (stuck):
1. NO matar el driver. NO matar el script todavía.
2. Verificar `current_item` y `stage` en el heartbeat.
3. Abrir scratchpad con ese item → reproducir → encontrar fix.
4. Si el script principal sigue stuck pasados X minutos, decidir con
   confirmación del usuario: pausar / interrumpir / matar.

---

## 12. Anti-patrones (perder tiempo garantizado)

| Anti-patrón | Por qué es malo | Alternativa |
|---|---|---|
| `launch_navigator()` "para no molestar al driver del usuario" | 30–60 s + login degradado | `get_driver()` |
| Matar driver "para empezar limpio" | Pierdes minutos relanzando | Refrescar página con `driver.refresh()` |
| `webdriver.Remote(...)` directo sin `get_driver()` | Crea sesión nueva en el geckodriver, deja huérfana la vieja | `get_driver()` con su patch |
| Inventar otro mecanismo de session (subclase `_AttachRemote`, etc.) | Duplica `scripts/driver_session.py` | Importar `driver_session.py` y listo |
| `print()` libre sin prefijos | Imposible parsear logs después | `[OK]`/`[ERROR]` o JSONL |
| `time.sleep(N)` fijo | Flakiness garantizado | `WebDriverWait(d, N).until(EC...)` |
| Asumir "está vacío" antes de INSERT | Duplica datos al re-correr | UPSERT / SELECT-then-INSERT |
| Ejecutar todo el script desde cero al fallar | Pierdes el progreso | Checkpoint + idempotencia |

---

## 13. Ejemplo end-to-end

Caso real: desarrollar un script `scripts/fix_<algo>.py` que procesa una
lista de items en FlashScore + escribe en DB.

```bash
# Terminal 1 — driver vivo (dejar abierta todo el día)
python scripts/start_driver.py

# Terminal 2 — desarrollo en scratchpad
nano scripts/_debug_fix_algo.py
python scripts/_debug_fix_algo.py        # iterar hasta que funcione

# Cuando los bloques funcionan → copiar al definitivo
nano scripts/fix_algo.py                  # agregar logs/heartbeat/checkpoint

# Probar con 1 item
python scripts/fix_algo.py --item-id <uno> --apply

# Si OK, escalar
nohup ./env_sports/bin/python -u scripts/fix_algo.py --apply \
      > logs/fix_algo_$(date +%F_%H%M).jsonl 2>&1 &
disown

# Terminal 3 — monitor
watch -n 30 'cat tmp/run_status_fix_algo.json | jq .'

# Si falla en item X → volver a Terminal 2, modificar scratchpad con item X,
# encontrar fix, migrar, re-lanzar.
```

---

## 14. Referencias

| Tema | Documento / código |
|---|---|
| Reglas estrictas del driver (autoridad) | `docs/DRIVER_RULES.md` |
| Lifecycle del driver | `scripts/start_driver.py`, `scripts/driver_session.py` |
| Patrón de reparación con driver compartido | `scripts/run_fix_live.py` |
| Ejemplo definitivo (idempotente) | `scripts/fix_null_team_ids.py` |
| Recuperación de procesos colgados | `documentacion/desarrollo_local.md` §9 |
| Mejoras de performance + validaciones DB | `documentacion/mejoras_performance.md` |
| Coordinación multi-worker (referencia avanzada) | `paralel_execution.py`, `paralel_teams.py` |
| Ejecución paralela multi-driver (ESPEC, en diseño) | `documentacion/especificacion_parallel_panel.md` |

---

## 15. Ejecución paralela multi-driver (modelo aparte — en diseño)

Todo lo anterior (secciones 1–4) asume **UN** driver compartido vía `get_driver()`
(`tmp/driver_session.json`): nadie abre un Firefox nuevo, nadie lo cierra. Ese es el
modo para **desarrollo, debug y corridas single** (`update_pending_matches.py`,
`fix_null_team_ids.py`, etc.).

Existe un **segundo modelo** para producción masiva: **N drivers en paralelo**, cada
worker con su **propio** driver (no el compartido) y su subconjunto de ligas. Base:
`paralel_execution.py` (`ThreadPoolExecutor`, `launch_navigator` por worker, status/control
por sección). En diseño está la versión que corre `update_pending_matches` por shard con
**control independiente por worker desde el panel** (start/pause/stop/cerrar-driver por cada
driver), sharding por deporte+país+liga, visible configurable en `config.py`, y reciclaje por
memoria por worker.

**Distinción clave para no confundir modelos:**
- Un worker paralelo **SÍ** posee y cierra/recicla **su** driver (PID propio) — eso es legítimo.
- Lo prohibido sigue igual: **nunca** tocar el driver de OTRO worker ni el Firefox del usuario,
  y **nunca `pkill firefox`**. Cada quien solo su propio PID. Ver `docs/DRIVER_RULES.md`.

→ Spec completa y plan: **`documentacion/especificacion_parallel_panel.md`**.
