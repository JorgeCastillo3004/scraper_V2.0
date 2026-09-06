#!/bin/bash
# Rotación de logs del live (sin root). Se ejecuta desde scraper-logrotate.timer.
#
# IMPORTANTE: los logs se TRUNCAN, nunca se borran ni se mueven. geckodriver y el
# propio systemd mantienen el descriptor abierto en modo append; si se borrara o
# renombrara el archivo, seguirían escribiendo en el inode huérfano y el espacio
# NO se liberaría hasta reiniciar el servicio.
set -u
BASE=/home/scraper/live_v2

rotar() {
  local f="$1" max_mb="$2" keep_mb="$3"
  [ -f "$f" ] || return 0
  local size_mb=$(( $(stat -c %s "$f") / 1024 / 1024 ))
  if [ "$size_mb" -ge "$max_mb" ]; then
    local tmp="${f}.tail.$$"
    tail -c "${keep_mb}M" "$f" > "$tmp" 2>/dev/null
    cat "$tmp" > "$f"          # trunca a 0 y reescribe la cola: respeta el fd abierto
    rm -f "$tmp"
    echo "[$(date "+%F %T")] rotado $f: ${size_mb}MB -> $(( $(stat -c %s "$f") / 1024 / 1024 ))MB"
  fi
}

# archivo                        umbral  cola a conservar
rotar "$BASE/geckodriver.log"        50   2
rotar "$BASE/logs/live_persist.log"   50   10
