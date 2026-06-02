#!/usr/bin/env bash
# clonar_bd_local.sh — Copia la BD remota del scraper a la BD LOCAL (docker).
#
#   ⚠️ READ-ONLY en el servidor: solo ejecuta pg_dump (= SELECT). NO elimina ni
#   modifica NADA en el remoto. Lo destructivo (DROP/CREATE) es SOLO local.
#
# Origen : config.py (DB_HOST/DB_NAME/DB_USER/DB_PASS) — remoto 96.30.195.40
# Destino: contenedor docker `sports_container` (postgres, puerto 5432 local)
# Cliente: imagen postgres:16-alpine (pg_dump/pg_restore 16.x, compatible con server 16.14)
#
# Uso:  bash scripts/clonar_bd_local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── credenciales del remoto (config.py, fuera de git) ──────────────────────
py() { env_sports/bin/python -c "from config import $1; print($1)"; }
REMOTE_HOST="$(py DB_HOST)"; REMOTE_DB="$(py DB_NAME)"
REMOTE_USER="$(py DB_USER)"; REMOTE_PASS="$(py DB_PASS)"

# ── destino local ──────────────────────────────────────────────────────────
LOCAL_CONTAINER="sports_container"
LOCAL_USER="DB_USER"; LOCAL_PASS="DB_PASS"; LOCAL_DB="sports_db"
LOCAL_PORT="5432"
PG_IMAGE="postgres:16-alpine"

BACKDIR="$ROOT/backups"; mkdir -p "$BACKDIR"
TS="$(date +%Y%m%d_%H%M%S)"
DUMP_NAME="sports_db_${TS}.dump"

echo "[1/4] pg_dump del remoto (solo lectura) -> backups/${DUMP_NAME}"
PGPASSWORD="$REMOTE_PASS" docker run --rm -e PGPASSWORD \
  -v "$BACKDIR:/back" "$PG_IMAGE" \
  pg_dump -h "$REMOTE_HOST" -U "$REMOTE_USER" -d "$REMOTE_DB" \
          -Fc --no-owner --no-acl -f "/back/${DUMP_NAME}"

echo "[2/4] arrancar contenedor local y esperar a que acepte conexiones"
docker start "$LOCAL_CONTAINER" >/dev/null
until docker exec -e PGPASSWORD="$LOCAL_PASS" "$LOCAL_CONTAINER" \
      pg_isready -U "$LOCAL_USER" -q; do sleep 1; done

echo "[3/4] recrear BD local '${LOCAL_DB}' y restaurar (DROP/CREATE = SOLO local)"
docker exec -e PGPASSWORD="$LOCAL_PASS" "$LOCAL_CONTAINER" \
  psql -U "$LOCAL_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS ${LOCAL_DB} WITH (FORCE);" \
  -c "CREATE DATABASE ${LOCAL_DB};"
# restaurar con cliente 16.x (mismo del dump) vía red del host
PGPASSWORD="$LOCAL_PASS" docker run --rm --network host -e PGPASSWORD \
  -v "$BACKDIR:/back" "$PG_IMAGE" \
  pg_restore -h 127.0.0.1 -p "$LOCAL_PORT" -U "$LOCAL_USER" -d "$LOCAL_DB" \
             --no-owner --no-acl "/back/${DUMP_NAME}"

echo "[4/4] verificacion rapida (nº tablas)"
R=$(PGPASSWORD="$REMOTE_PASS" docker run --rm -e PGPASSWORD "$PG_IMAGE" \
     psql -h "$REMOTE_HOST" -U "$REMOTE_USER" -d "$REMOTE_DB" -tAc \
     "select count(*) from information_schema.tables where table_schema='public';" 2>/dev/null)
L=$(docker exec -e PGPASSWORD="$LOCAL_PASS" "$LOCAL_CONTAINER" \
     psql -U "$LOCAL_USER" -d "$LOCAL_DB" -tAc \
     "select count(*) from information_schema.tables where table_schema='public';" 2>/dev/null)
echo "    tablas remoto=$R  local=$L"
echo "OK -> copia local en ${LOCAL_CONTAINER}:${LOCAL_PORT}/${LOCAL_DB} (dump: backups/${DUMP_NAME})"
echo "Para diff detallado tabla por tabla: env_sports/bin/python scripts/_debug_verify_clon.py"
