#!/bin/bash
# watchdog_loop.sh
# ----------------
# Loop autónomo que vigila scripts/fix_null_team_ids.py:
#   - Detecta hang (sin progreso 3+ min) → kill + relanzar misma liga (1ra)
#                                          o SKIP (2da hang) → siguiente queue
#   - Detecta RESUMEN → auto-lanzar siguiente liga de la queue
#   - Detecta memoria <500MB → reciclar driver canónico
#   - Escribe estado en tmp/watchdog_status.json cada 15s
#   - Escribe acciones tomadas en logs/watchdog_actions.log
#
# Uso:
#   nohup ./scripts/watchdog_loop.sh > logs/watchdog_stdout.log 2>&1 &
#   disown

set -u
ROOT=/home/jorge/work/scraper_V2.0
cd "$ROOT"
PY="$ROOT/env_sports/bin/python"
STATUS_FILE="$ROOT/tmp/watchdog_status.json"
ACTIONS_LOG="$ROOT/logs/watchdog_actions.log"
SKIPPED_LOG="$ROOT/logs/skipped_leagues.log"
SLEEP=15

mkdir -p "$ROOT/tmp" "$ROOT/logs"

# Queue de ligas pendientes (key|short_name|extra_flag). Se procesan en orden.
# Saltadas (problemáticas conocidas, revisión manual posterior):
#   - AM._FOOTBALL/CANADA_CFL (página solo temporada actual)
#   - FOOTBALL/COSTA RICA_Primera Division (igual)
#   - FOOTBALL/ECUADOR_Liga Pro (hangs sistemáticos)
QUEUE=(
    "FOOTBALL/ASIA_World Cup|asia_wc|"
    "FOOTBALL/EUROPE_Euro|euro|"
    "FOOTBALL/NORTH & CENTRAL AMERICA_World Cup|naca_wc|"
    "FOOTBALL/SOUTH AMERICA_World Cup|sam_wc|"
    "FOOTBALL/EUROPE_World Cup|europe_wc|"
    "FOOTBALL/AUSTRALIA & OCEANIA_World Cup|oceania_wc|"
    "FOOTBALL/WORLD_World Cup|world_wc|"
)

# Liga actual en curso (deducida del último log activo)
current_league=""
current_short=""
hang_count=0       # contadores por liga
last_processed=0
last_change_ts=$(date +%s)

log_action() {
    echo "[$(date '+%F %T')] $*" >> "$ACTIONS_LOG"
}

write_status() {
    cat > "$STATUS_FILE" <<EOF
{
  "updated":         "$(date '+%F %T')",
  "current_league":  "$current_league",
  "current_short":   "$current_short",
  "current_log":     "$1",
  "procesados":      $2,
  "ok":              $3,
  "errors":          $4,
  "problems":        $5,
  "mem_available_mb": $6,
  "script_alive":    $7,
  "hang_count":      $hang_count,
  "queue_remaining": ${#QUEUE[@]}
}
EOF
}

mem_available_mb() {
    free -m | awk '/^Mem:/ {print $7}'
}

driver_pids() {
    # PIDs del start_driver actual + sus hijos
    ps -ef | awk '/[s]tart_driver\.py/ {print $2}'
}

driver_alive() {
    [ -n "$(driver_pids)" ]
}

recycle_driver() {
    log_action "RECICLANDO DRIVER (mem antes: $(mem_available_mb) MB)"
    # Matar PIDs de start_driver + sus hijos transitivamente
    for pid in $(driver_pids); do
        kill -9 -- -"$pid" 2>/dev/null || true
        kill -9 "$pid" 2>/dev/null || true
        pkill -9 -P "$pid" 2>/dev/null || true
    done
    pkill -9 -f "rust_mozprofile" 2>/dev/null || true
    sleep 3
    nohup "$PY" -u "$ROOT/scripts/start_driver.py" \
        > "$ROOT/logs/start_driver_$(date +%F_%H%M).log" 2>&1 &
    disown
    # esperar login (max 90s)
    for i in $(seq 1 30); do
        sleep 3
        NLOG=$(ls -t "$ROOT"/logs/start_driver_*.log | head -1)
        if grep -q "Sesión guardada" "$NLOG" 2>/dev/null; then
            log_action "  driver fresco listo en $((i*3))s — session: $(cat $ROOT/tmp/driver_session.json | tr -d '\n')"
            return 0
        fi
    done
    log_action "  ERROR: driver no logueó en 90s"
    return 1
}

launch_league() {
    local key="$1"
    local short="$2"
    local extra_flag="${3:-}"
    current_league="$key"
    current_short="$short"
    current_extra="$extra_flag"
    hang_count=0
    last_processed=0
    last_change_ts=$(date +%s)
    log_action "LANZAR liga: $key $extra_flag (log: fix_null_${short}_*.log)"
    nohup "$PY" -u "$ROOT/scripts/fix_null_team_ids.py" \
        --league "$key" $extra_flag --apply \
        > "$ROOT/logs/fix_null_${short}_$(date +%F_%H%M).log" 2>&1 &
    disown
    sleep 5
}

next_from_queue() {
    if [ ${#QUEUE[@]} -eq 0 ]; then
        log_action "QUEUE VACÍA — watchdog termina"
        write_status "" 0 0 0 0 "$(mem_available_mb)" "false"
        exit 0
    fi
    local entry="${QUEUE[0]}"
    QUEUE=("${QUEUE[@]:1}")
    # Parse: KEY|short|extra_flag (extra_flag puede contener espacios)
    IFS='|' read -r key short extra <<< "$entry"
    launch_league "$key" "$short" "$extra"
}

# Detectar liga actualmente en proceso (si la hay)
detect_current() {
    LATEST=$(ls -t "$ROOT"/logs/fix_null_*.log 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then return; fi
    if ! grep -q 'RESUMEN (dry_run=False)' "$LATEST" 2>/dev/null; then
        # En curso — extraer liga del log
        LINE=$(grep -oE "MATCHES CON team_id NULL.*" "$LATEST" | head -1 || true)
        LIGA=$(grep -oE "Ligas: \[\([^]]+\)\]" "$LATEST" | head -1 | sed "s/.*('\\([^']*\\)', '\\([^']*\\)').*/\\1\\/\\2/" || true)
        if [ -n "$LIGA" ]; then
            current_league="$LIGA"
            current_short=$(echo "$LIGA" | tr '/' '_' | tr ' ' '_')
            log_action "DETECTADO en curso: $LIGA (log: $LATEST)"
        fi
    fi
}

detect_current
log_action "WATCHDOG iniciado. queue restante: ${#QUEUE[@]}"

# === LOOP PRINCIPAL ===
while true; do
    LOG=$(ls -t "$ROOT"/logs/fix_null_*.log 2>/dev/null | head -1)
    if [ -z "$LOG" ]; then
        next_from_queue
        sleep "$SLEEP"
        continue
    fi

    proc=$(grep -c '^  >>>' "$LOG" 2>/dev/null) || proc=0
    ok=$(grep -c '\[OK\] match_detail' "$LOG" 2>/dev/null) || ok=0
    err=$(grep -c '\[ERROR\]' "$LOG" 2>/dev/null) || err=0
    prob=$(grep -c '\[PROBLEM RECORDED\]' "$LOG" 2>/dev/null) || prob=0
    finished=$(grep -c 'RESUMEN (dry_run=False)' "$LOG" 2>/dev/null) || finished=0
    mem=$(mem_available_mb)
    script_pid=$(ps -ef | awk '/[f]ix_null_team_ids\.py/ {print $2}' | head -1)
    if [ -n "$script_pid" ]; then alive="true"; else alive="false"; fi

    write_status "$LOG" "$proc" "$ok" "$err" "$prob" "$mem" "$alive"

    # === Acciones automáticas ===
    if [ "$finished" -ge 1 ]; then
        # Liga terminada → siguiente queue
        log_action "RESUMEN detectado en $LOG (proc=$proc ok=$ok err=$err prob=$prob) — paso al siguiente"
        next_from_queue
        sleep "$SLEEP"
        continue
    fi

    # Mem baja → reciclar driver (umbral 200MB porque sistema solo tiene 7.6GB total)
    if [ "$mem" -lt 200 ]; then
        log_action "MEMORIA CRÍTICA: ${mem} MB → reciclo driver"
        # No matar el script python en curso; solo el driver. El script reusa nuevo session
        recycle_driver
        sleep "$SLEEP"
        continue
    fi

    # Hang? compare proc vs last
    if [ "$proc" -gt "$last_processed" ]; then
        last_processed="$proc"
        last_change_ts=$(date +%s)
    fi
    now=$(date +%s)
    stalled=$((now - last_change_ts))

    if [ "$alive" = "false" ] && [ "$finished" -eq 0 ]; then
        # Script murió sin RESUMEN — re-lanzar misma liga
        hang_count=$((hang_count + 1))
        if [ "$hang_count" -ge 2 ]; then
            log_action "SKIP $current_league tras 2 muertes sin RESUMEN"
            echo "[$(date '+%F %T')] $current_league" >> "$SKIPPED_LOG"
            next_from_queue
        else
            log_action "Script $current_league murió sin RESUMEN — re-lanzar (intento $hang_count)"
            launch_league "$current_league" "$current_short"
        fi
    elif [ "$stalled" -gt 180 ] && [ "$alive" = "true" ]; then
        # Hung 3 min sin progreso
        hang_count=$((hang_count + 1))
        log_action "HANG ${stalled}s en $current_league — kill PID $script_pid (hang #$hang_count)"
        kill -9 "$script_pid" 2>/dev/null || true
        sleep 2
        if [ "$hang_count" -ge 2 ]; then
            log_action "SKIP $current_league tras 2 hangs"
            echo "[$(date '+%F %T')] $current_league (hang 2x)" >> "$SKIPPED_LOG"
            next_from_queue
        else
            launch_league "$current_league" "$current_short"
        fi
    fi

    sleep "$SLEEP"
done
