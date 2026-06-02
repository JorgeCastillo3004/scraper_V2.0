# Desarrollo Local

Guía para levantar todos los servicios localmente y realizar pruebas.

---

## Levantar servicios

```bash
# 1. PostgreSQL
docker start sports_container

# 2. FastAPI  (puerto 8000)
cd /home/jorge/work/scraper_V2.0
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Frontend  (puerto 5173 — en otra terminal)
cd /home/jorge/work/scraper_V2.0/frontend
npm run dev
```

> No usar `env` virtual — las dependencias están en el Python del sistema.
> Verificar que solo corre **una** instancia de cada proceso; duplicados causan freezes en la API.

---

## Requisitos previos

```bash
# Python 3.10+
python3 --version

# Node.js 18+
node --version
npm --version

# Firefox + geckodriver (para Selenium)
firefox --version
geckodriver --version

# PostgreSQL client
psql --version
```

---

## 1. Base de datos PostgreSQL

### Opción A — Docker (recomendado para dev local)

```bash
cd scraper_V2.0/postgress_init

# Levantar contenedor
docker compose -f docker-compose_original.yml up -d

# Verificar que está corriendo
docker ps | grep postgres

# Conectarse para verificar
psql -h localhost -U db_admin -d scraper_db
```

**Credenciales del contenedor** (ver `docker-compose_original.yml`):
```
host:     localhost
port:     5432
user:     db_admin
password: (ver docker-compose)
dbname:   scraper_db
```

### Opción B — PostgreSQL local instalado

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib

# Crear DB y usuario
sudo -u postgres psql -c "CREATE ROLE db_admin WITH LOGIN PASSWORD 'tu_password' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE scraper_db OWNER db_admin;"

# Aplicar schema
psql -h localhost -U db_admin -d scraper_db -f postgress_init/console_8.sql
```

### Verificar conexión

```bash
python3 -c "
import sys; sys.path.insert(0,'src')
from data_base import getdb
con = getdb()
print('Conexión OK:', con.status)
con.close()
"
```

---

## 2. Dependencias Python

El proyecto usa el **Python del sistema** (no venv).
Las dependencias están instaladas globalmente con `pip3`.

```bash
# Verificar que están disponibles
python3 -c "import selenium, fastapi, psycopg2, uvicorn; print('OK')"

# Si falta alguna
pip3 install -r requirements.txt
pip3 install uvicorn[standard] fastapi
```

---

## 3. Archivo `config.py`

```bash
# Copiar la plantilla y completar credenciales
cp config_model.py config.py
```

Editar `config.py`:
```python
# Base de datos
DB_HOST = 'localhost'
DB_NAME = 'scraper_db'
DB_USER = 'db_admin'
DB_PASS = 'tu_password'

# FlashScore
FS_EMAIL    = 'tu@email.com'
FS_PASSWORD = 'tu_password'

# Servidor remoto (solo para deploy scripts)
SERVER_HOST = '104.156.244.145'
SERVER_USER = 'root'
SERVER_PATH = '/path/en/servidor'
```

---

## 4. API FastAPI

```bash
cd scraper_V2.0
source env/sports_env/bin/activate

# Desarrollo con auto-reload
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Verificar
curl http://localhost:8000/api/status/all
curl http://localhost:8000/api/leagues/sports
```

Swagger UI disponible en: `http://localhost:8000/docs`

---

## 5. Frontend React + Vite

```bash
cd scraper_V2.0/frontend

# Instalar dependencias (primera vez)
npm install

# Servidor de desarrollo
npm run dev
# → http://localhost:5173

# Build para producción
npm run build
# → genera frontend/dist/  (servido automáticamente por FastAPI)
```

El proxy de Vite redirige `/api`, `/ws` y `/artifacts` al puerto 8000 automáticamente en desarrollo.
`/artifacts` sirve screenshots e imágenes generadas por los scrapers.

---

## 6. Geckodriver (Selenium headless)

```bash
# Verificar que geckodriver está en PATH
geckodriver --version

# Si no está instalado (Ubuntu)
wget https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-linux64.tar.gz
tar -xzf geckodriver-*.tar.gz
sudo mv geckodriver /usr/local/bin/
geckodriver --version

# Verificar que Firefox está instalado
firefox --version
# Si no:
sudo apt install firefox
```

---

## 7. Pruebas rápidas sin browser

Para probar la API y el frontend sin Selenium, se puede mockear el proceso:

```bash
# Probar el endpoint de status
curl -X GET http://localhost:8000/api/results/status

# Probar inicio (lanzará el proceso real — tener geckodriver activo)
curl -X POST http://localhost:8000/api/news/start \
  -H "Content-Type: application/json" \
  -d '{"sports": ["FOOTBALL"], "days": 7}'

# Probar WebSocket con wscat
npm install -g wscat
wscat -c ws://localhost:8000/ws/news/logs
```

---

## 8. Flujo completo de prueba local

```bash
# Terminal 1 — PostgreSQL (Docker)
docker compose -f postgress_init/docker-compose_original.yml up

# Terminal 2 — FastAPI
source env/sports_env/bin/activate
uvicorn api.main:app --reload --port 8000

# Terminal 3 — Frontend
cd frontend && npm run dev

# Abrir navegador
xdg-open http://localhost:5173
```

---

## 9. Recuperación cuando los servicios se cuelgan

### API no responde / uvicorn congelado

```bash
# Identificar el proceso
ps aux | grep uvicorn | grep -v grep

# Matar y reiniciar
kill -9 <PID>
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

> `kill -9` en uvicorn puede dejar workers huérfanos. Verificar y limpiarlos:

```bash
# Workers huérfanos (PPID = 1 o PID de init)
ps aux | grep uvicorn | grep -v grep
kill -9 <PIDs huérfanos>
```

### Dos instancias de Vite o uvicorn

Duplicados causan freezes en la API y peticiones dobles.

```bash
# Verificar instancias
ps aux | grep -E "uvicorn|vite" | grep -v grep

# Matar todas y reiniciar una sola
pkill -f "uvicorn api.main"
pkill -f "vite"
```

### Geckodriver huérfano tras crash del scraper

```bash
ps aux | grep geckodriver | grep -v grep
kill -9 <PID>
```

---

## 10. Variables de entorno útiles para dev  

```bash
# Desactivar Rich UI en procesos lanzados por la API (ya lo hace la API)
export NO_RICH=1

# Output sin buffer (la API lo setea automáticamente)
export PYTHONUNBUFFERED=1

# Para debug de psycopg2
export PGSSLMODE=disable
```

---

## 11. Conexión al servidor remoto

```bash
# SSH directo (usa clave ~/.ssh/id_ed25519)
ssh server               # → root@104.156.244.145

# Tunnel SSH para acceder a la API del servidor localmente
ssh -L 8000:localhost:8000 server
# Luego abrir: http://localhost:8000/docs

# Deploy de código
source env/sports_env/bin/activate
python scripts/update_server.py py

# Sincronizar checkpoints
python scripts/sync_checkpoints.py
```

---

## Puertos usados

| Servicio | Puerto | Descripción |
|---|---|---|
| FastAPI | 8000 | API REST + WebSocket |
| Vite dev | 5173 | Frontend en desarrollo |
| Vite preview | 4173 | Build preview |
| PostgreSQL | 5432 | Base de datos |
| Dashboard viejo | 8502 | Flet (deprecado) |
