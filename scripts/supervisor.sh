#!/bin/bash
# supervisor.sh — vigila watchdog_loop.sh y lo relanza si muere.
#
# Uso:
#   nohup ./scripts/supervisor.sh > logs/supervisor_stdout.log 2>&1 &
#   disown
#
# Para detenerlo:
#   pkill -f "supervisor.sh"
#
# Verifica cada 30s:
#   - watchdog_loop.sh vivo?  → si no, relanzar
#   - driver session viva?    → si no, NO mata nada; solo registra alerta
#   - memoria libre >300MB?   → si no, registra alerta
#
# NUNCA mata drivers ni elimina datos. Solo relanza el watchdog.

set -u
ROOT="/home/jorge/work/scraper_V2.0"
cd "$ROOT"

LOGFILE="$ROOT/logs/supervisor.log"
SLEEP_SECS=10
mkdir -p "$ROOT/logs"

log() {
    echo "[$(date '+%F %T')] $*" >> "$LOGFILE"
}

is_watchdog_alive() {
    # buscar bash watchdog_loop.sh propiamente dicho (no este supervisor)
    pgrep -f "bash.*watchdog_loop.sh" > /dev/null
}

is_driver_alive() {
    local port
    port=$(python3 -c "import json; print(json.load(open('tmp/driver_session.json'))['executor_url'].rsplit(':',1)[-1])" 2>/dev/null)
    [[ -z "$port" ]] && return 1
    curl -sf -o /dev/null --max-time 5 "http://localhost:$port/status"
}

mem_free_mb() {
    free -m | awk '/^Mem:/ {print $4}'
}

relaunch_watchdog() {
    log "WATCHDOG murió — relanzando..."
    nohup ./scripts/watchdog_loop.sh > logs/watchdog_stdout.log 2>&1 &
    disown
    sleep 3
    if is_watchdog_alive; then
        log "  → watchdog relanzado OK"
    else
        log "  → FALLO al relanzar watchdog (revisar manualmente)"
    fi
}

log "SUPERVISOR iniciado (pid=$$)"

while true; do
    if ! is_watchdog_alive; then
        relaunch_watchdog
    fi

    # Driver: solo alertar, no matar
    if ! is_driver_alive; then
        log "ALERTA: driver no responde (puerto en tmp/driver_session.json no contesta HTTP)"
    fi

    free=$(mem_free_mb)
    if [[ "$free" -lt 300 ]]; then
        log "ALERTA memoria baja: ${free}MB libres"
    fi

    sleep "$SLEEP_SECS"
done
