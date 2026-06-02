#!/bin/bash
# Runner secuencial: ataca match_detail.team_id NULL en las 12 ligas afectadas.
# Recicla el driver Selenium automaticamente entre ligas cuando la memoria
# disponible cae por debajo del umbral, evitando OOM kills por acumulacion
# de tabs/DOM en Firefox.
#
# Uso: bash scripts/run_fix_team_ids_sequence.sh
# Logs: tmp/logs/fix_team_<SPORT>_<LEAGUE>.log + tmp/logs/team_sequence_summary.log
set -e
cd "$(dirname "$0")/.."

SUMMARY=tmp/logs/team_sequence_summary.log
mkdir -p tmp/logs logs

# === Umbrales de reciclo de driver ===
# Si memoria disponible (MemAvailable de /proc/meminfo) < MEM_MIN_MB, reciclar
# Si el driver lleva mas de MAX_DRIVER_MIN minutos, tambien reciclar
MEM_MIN_MB=500
MAX_DRIVER_MIN=60

# ---------------------------------------------------------------------------
# get_avail_mb — memoria disponible en MB (mas confiable que "free" para checks)
# ---------------------------------------------------------------------------
get_avail_mb() {
  awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo
}

# ---------------------------------------------------------------------------
# get_driver_age_min — minutos desde que start_driver.py arranco, 0 si no vive
# ---------------------------------------------------------------------------
get_driver_age_min() {
  local pid
  pid=$(pgrep -f "scripts/start_driver.py" 2>/dev/null | head -1)
  [ -z "$pid" ] && { echo 0; return; }
  ps -p "$pid" -o etimes= 2>/dev/null | awk '{print int($1/60)}'
}

# ---------------------------------------------------------------------------
# kill_driver — mata start_driver.py + geckodriver + Firefox del scraper +
# content procs. NO toca otros Firefox del usuario (distinguido por perfil
# /tmp/rust_mozprofile*).
# ---------------------------------------------------------------------------
kill_driver() {
  echo "  [RECYCLE] matando driver actual..." >> "$SUMMARY"

  # start_driver.py python parent
  pkill -9 -f "scripts/start_driver.py" 2>/dev/null || true

  # geckodriver(s)
  pkill -9 -x geckodriver 2>/dev/null || true

  # Firefox del scraper (perfil rust_mozprofile*) + sus content procs
  local ff_pids
  ff_pids=$(pgrep -f "rust_mozprofile" 2>/dev/null || true)
  if [ -n "$ff_pids" ]; then
    # content procs (parentPid <ff>)
    for pid in $ff_pids; do
      local children
      children=$(ps auxww | grep "parentPid $pid" | grep -v grep | awk '{print $2}')
      [ -n "$children" ] && kill -9 $children 2>/dev/null || true
    done
    # firefox parents
    kill -9 $ff_pids 2>/dev/null || true
  fi

  sleep 3
  rm -f tmp/driver_session.json
}

# ---------------------------------------------------------------------------
# launch_driver — lanza start_driver.py en background, espera login OK
# (driver_session.json escrito). Retorna 0 si OK, 1 si timeout.
# ---------------------------------------------------------------------------
launch_driver() {
  local log="logs/start_driver_$(date +%Y-%m-%d_%H%M%S).log"
  echo "  [RECYCLE] lanzando driver nuevo (log: $log)..." >> "$SUMMARY"
  DISPLAY=:1 nohup env_sports/bin/python scripts/start_driver.py > "$log" 2>&1 &
  disown

  # Esperar driver_session.json (hasta 120s)
  for i in $(seq 1 24); do
    [ -f tmp/driver_session.json ] && {
      local sid
      sid=$(awk -F'"' '/session_id/ {print $4}' tmp/driver_session.json)
      echo "  [RECYCLE] driver listo tras $((i*5))s (session_id=${sid:0:8}...)" >> "$SUMMARY"
      return 0
    }
    if grep -qE "RuntimeError|Login fallido" "$log" 2>/dev/null; then
      echo "  [RECYCLE] FAIL login (ver $log)" >> "$SUMMARY"
      return 1
    fi
    sleep 5
  done
  echo "  [RECYCLE] TIMEOUT 120s esperando login (ver $log)" >> "$SUMMARY"
  return 1
}

# ---------------------------------------------------------------------------
# maybe_recycle — decide si reciclar driver basado en memoria/edad.
# Imprime en summary el motivo si recicla. Asume driver vivo a la entrada.
# ---------------------------------------------------------------------------
maybe_recycle() {
  local avail age reason=""
  avail=$(get_avail_mb)
  age=$(get_driver_age_min)

  if [ "$avail" -lt "$MEM_MIN_MB" ]; then
    reason="memoria=${avail}MB < ${MEM_MIN_MB}MB"
  elif [ "$age" -gt "$MAX_DRIVER_MIN" ]; then
    reason="driver age=${age}min > ${MAX_DRIVER_MIN}min"
  fi

  if [ -n "$reason" ]; then
    echo "" >> "$SUMMARY"
    echo "[$(date -Iseconds)] RECYCLE driver — $reason" >> "$SUMMARY"
    kill_driver
    launch_driver || {
      echo "[$(date -Iseconds)] ABORT — no se pudo relanzar driver" >> "$SUMMARY"
      exit 1
    }
    avail=$(get_avail_mb)
    echo "  [RECYCLE] memoria post-reciclo: ${avail}MB available" >> "$SUMMARY"
  fi
}

# ---------------------------------------------------------------------------
# Inicio
# ---------------------------------------------------------------------------
echo "" >> "$SUMMARY"
echo "=== TEAM_IDS SEQUENCE START $(date -Iseconds) (MEM_MIN_MB=${MEM_MIN_MB}, MAX_DRIVER_MIN=${MAX_DRIVER_MIN}) ===" >> "$SUMMARY"

# Verificar driver vivo al arranque; si no, lanzar
if ! pgrep -f "scripts/start_driver.py" >/dev/null 2>&1; then
  echo "[$(date -Iseconds)] driver no vivo al arranque — lanzando..." >> "$SUMMARY"
  launch_driver || { echo "[$(date -Iseconds)] ABORT — driver no arranco" >> "$SUMMARY"; exit 1; }
fi

# Orden 2026-05-28: solo football con team_id NULL pendiente.
# Pequeños primero, World Cup ultimo (bug estructural, 29 partidos)
LEAGUES=(
  "FOOTBALL/NETHERLANDS_Eredivisie"
  "FOOTBALL/USA_MLS"
  "FOOTBALL/MEXICO_Liga MX"
  "FOOTBALL/ECUADOR_Liga Pro"
  "FOOTBALL/WORLD_World Cup"
)

for LEAGUE_KEY in "${LEAGUES[@]}"; do
  # Antes de cada liga, evaluar si reciclar driver
  maybe_recycle

  SAFE=$(echo "$LEAGUE_KEY" | tr ' /' '__')
  LOG="tmp/logs/fix_team_${SAFE}.log"
  T0=$(date +%s)
  AVAIL_PRE=$(get_avail_mb)
  echo "" >> "$SUMMARY"
  echo "[$(date -Iseconds)] START  ${LEAGUE_KEY}  (mem=${AVAIL_PRE}MB)" >> "$SUMMARY"
  echo "  log: ${LOG}" >> "$SUMMARY"

  DISPLAY=:1 env_sports/bin/python scripts/fix_null_team_ids.py \
      --apply \
      --league "${LEAGUE_KEY}" \
      > "$LOG" 2>&1 || true

  T1=$(date +%s); DT=$((T1-T0))
  AVAIL_POST=$(get_avail_mb)
  RESUMEN=$(grep -A6 '^RESUMEN' "$LOG" | tail -7 | tr '\n' ' | ' || echo "no_summary")
  echo "[$(date -Iseconds)] DONE   ${LEAGUE_KEY}  (${DT}s, mem ${AVAIL_PRE}→${AVAIL_POST}MB)" >> "$SUMMARY"
  echo "  ${RESUMEN}" >> "$SUMMARY"
done

echo "" >> "$SUMMARY"
echo "=== TEAM_IDS SEQUENCE END $(date -Iseconds) ===" >> "$SUMMARY"
