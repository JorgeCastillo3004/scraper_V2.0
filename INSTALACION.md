# Instalación — scraper_V2.0

Pasos **probados** para dejar el proyecto corriendo en un PC nuevo (o tras restaurar
desde respaldo). El panel son dos servicios: **API** FastAPI (`api.main:app`, puerto
**8009**) + **frontend** React/Vite (puerto **5174**, proxea `/api`,`/ws`,`/artifacts`
→ 8009). Para operar día a día ver `documentacion/RUNBOOK_PANEL.md`.

> Lo que NO viene en el respaldo (y hay que regenerar acá): los venvs
> `env_sports/` y `sports_env/`, `frontend/node_modules/` y `config.py` — todos en
> `.gitignore`.

> **Dos virtualenvs (separados a propósito):**
> - **`env_sports/`** → el panel/API (uvicorn `api.main`).
> - **`sports_env/`** → venv DEDICADO de los scripts del scraper que lanza el panel
>   (`update_pending_matches.py`, `fix_null_team_ids.py`, `start_driver.py`,
>   `paralel_*`, etc.). `api/services/process_manager.py` y `driver_manager.py`
>   resuelven `sports_env/bin/python` (fallback al de la API si no existe).
>   Ambos se instalan desde el mismo `requirements.txt`.

---

## 0. Requisitos del sistema

- **Python 3.10+** (probado en 3.14).
- **Node 18+** + npm (frontend).
- **Firefox + geckodriver** para el driver Selenium. En Ubuntu con Firefox snap ya
  viene el geckodriver del snap:
  ```bash
  command -v firefox            # /usr/bin/firefox (wrapper snap)
  command -v geckodriver        # /snap/bin/geckodriver  → firefox.geckodriver
  ```
  Si falta geckodriver: instalá Firefox por snap (`sudo snap install firefox`) o
  descargá geckodriver y dejalo en el PATH / `/usr/local/bin`. El proyecto lo
  resuelve dinámicamente (PATH → snap → rutas conocidas); ya **no** hay rutas
  hardcodeadas a `~/.cache/selenium`.
- (Opcional) Docker + Compose, solo si vas a levantar la **copia local** de la BD
  (`scripts/clonar_bd_local.sh`). La operación normal usa la BD remota.

---

## 1. config.py (credenciales — NO está en git)

Copiá el template y completá los valores:
```bash
cp config_model.py config.py
```
Editar `config.py`:
- **Base de datos** (`DB_HOST/DB_NAME/DB_USER/DB_PASS`): apunta a la BD remota
  `96.30.195.40 / sports_db`. Sin esto la API no levanta estado.
- **FlashScore** (`FS_EMAIL/FS_PASSWORD`): login que usa el driver.
- **SSH remoto** (`SERVER_*`): solo si vas a usar utilidades de despliegue/clonado.
- **`FIX_HEADLESS`**: `False` en local (Firefox **visible**, para ver la extracción);
  `True` en servidor sin entorno gráfico. **`LIVE_HEADLESS`** ídem para el scraper live.

Verificar que las credenciales de BD autentican:
```bash
env_sports/bin/python - <<'PY'
import config, psycopg2
c = psycopg2.connect(host=config.DB_HOST, dbname=config.DB_NAME,
                     user=config.DB_USER, password=config.DB_PASS, connect_timeout=10)
c.cursor().execute("SELECT 1"); print("DB OK")
PY
```

---

## 2. Backend — virtualenvs + dependencias

Crear **los dos** venvs (panel y scripts del scraper), ambos con `requirements.txt`:
```bash
cd /home/jorge/work/scraper_V2.0
python3 -m venv env_sports   && env_sports/bin/pip  install -r requirements.txt   # panel/API
python3 -m venv sports_env   && sports_env/bin/pip  install -r requirements.txt   # scripts scraper
```

**Si `python3 -m venv` falla con "ensurepip is not available"** (pasa con algunos
Python del sistema sin el paquete `venv`), dos opciones:

- Con sudo: `sudo apt install -y python3-venv python3-pip` y reintentar.
- Sin sudo (bootstrap de pip) — repetir para cada venv (`env_sports` y `sports_env`):
  ```bash
  python3 -m venv --without-pip env_sports
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  env_sports/bin/python /tmp/get-pip.py
  env_sports/bin/pip install -r requirements.txt
  ```

`requirements.txt` incluye `fastapi`, `uvicorn[standard]`, `selenium`,
`psycopg2-binary`, `paramiko`, etc.

---

## 3. Frontend — dependencias

```bash
cd frontend
npm install
```

---

## 4. Levantar el panel

```bash
cd /home/jorge/work/scraper_V2.0

# API (8009)
NO_RICH=1 PYTHONUNBUFFERED=1 \
  nohup env_sports/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8009 \
  > logs/_panel_api.log 2>&1 &

# Frontend (5174)
cd frontend && nohup npm run dev > ../logs/_panel_vite.log 2>&1 &
```

Abrir **http://localhost:5174/**. Detalle completo de operación en
`documentacion/RUNBOOK_PANEL.md`.

---

## 5. Driver Selenium (Inconsistencias)

El driver **no** se levanta con el panel. Se inicia desde la UI: pestaña
**Inconsistencias → "▶ Iniciar driver"** (lanza `scripts/start_driver.py`, abre su
propio Firefox visible, hace login en FlashScore y guarda la sesión en
`tmp/driver_session.json`). Tarda ~10-40 s (login).

Requiere firefox + geckodriver (paso 0). Reglas del driver en `docs/DRIVER_RULES.md`
(nunca `pkill firefox`/`geckodriver`: se cierra con el botón "■ Matar driver").

---

## 6. Verificación rápida

```bash
curl -s -o /dev/null -w "API  %{http_code}\n" http://localhost:8009/api/driver/status   # 200
curl -s -o /dev/null -w "Vite %{http_code}\n" http://localhost:5174/                     # 200
curl -s http://localhost:5174/api/driver/status   # JSON real vía proxy = OK
```

Tras "Iniciar driver", `…/api/driver/status` debe pasar a
`{"alive":true,"session_ready":true,...}` y aparecer un `firefox --marionette` visible.

---

## Más detalle
- Operación del panel: `documentacion/RUNBOOK_PANEL.md`
- Arquitectura del scraper: `PROJECT_CONTEXT.md` y `README.md`
- Reglas del driver: `docs/DRIVER_RULES.md`
