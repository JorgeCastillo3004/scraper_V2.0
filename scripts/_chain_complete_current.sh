#!/usr/bin/env bash
# Completa score + status=COMPLETED de los partidos ACTUALES con score -1,
# liga por liga (secuencial, un solo driver). Reusa update_pending_matches.
# NO toca las viejas (ya etiquetadas OLD_SEASON) ni borra nada.
set -u
cd /home/jorge/work/scraper_V2.0 || exit 1
export DRIVER_MEM_LIMIT_MB="${DRIVER_MEM_LIMIT_MB:-4608}"   # umbral reciclaje driver (Jorge: 3072)
PY=sports_env/bin/python
LOG=logs/_chain_complete_current.out
: > "$LOG"

LEAGUES=(
  "FOOTBALL/WORLD_World Cup"
  "FOOTBALL/AFRICA_World Cup"
  "FOOTBALL/ASIA_World Cup"
  "FOOTBALL/EUROPE_World Cup"
  "FOOTBALL/SOUTH AMERICA_World Cup"
  "FOOTBALL/NORTH & CENTRAL AMERICA_World Cup"
  "FOOTBALL/AUSTRALIA & OCEANIA_World Cup"
  "BASEBALL/USA_MLB"
  "BASKETBALL/SPAIN_ACB"
  "FOOTBALL/CHILE_Liga de Primera"
  "BASEBALL/SOUTH KOREA_KBO"
)

say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
say "=== CHAIN COMPLETE CURRENT inicio (${#LEAGUES[@]} ligas) ==="
for lg in "${LEAGUES[@]}"; do
  sport="${lg%%/*}"
  say "--- $lg ---"
  $PY scripts/update_pending_matches.py --league "$lg" --mode rapido --apply \
      >> "$LOG" 2>&1
  grep -E "TOTALIZACIÓN|Procesados OK|No encontrados" "$LOG" | tail -3 | tee -a "$LOG"
done
say "=== CHAIN FIN ==="
