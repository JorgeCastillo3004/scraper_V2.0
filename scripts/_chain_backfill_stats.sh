#!/usr/bin/env bash
# Backfill de ESTADÍSTICAS (match.statistic vacío en COMPLETED con score real),
# liga por liga, secuencial (un driver). Reusa update_pending_matches --solo-sin-stats:
# fuerza modo 'completo' y escribe ÚNICAMENTE statistic (NO toca score ni status).
# Lee la lista de ligas de tmp/_backfill_leagues.txt (una "SPORT/KEY" por línea).
set -u
cd /home/jorge/work/scraper_V2.0 || exit 1
export DRIVER_MEM_LIMIT_MB="${DRIVER_MEM_LIMIT_MB:-4608}"   # umbral reciclaje driver
PY=sports_env/bin/python
LOG=logs/_chain_backfill_stats.out
LIST=tmp/_backfill_leagues.txt
: > "$LOG"
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

n=$(grep -c . "$LIST" 2>/dev/null || echo 0)
say "=== BACKFILL STATS inicio (${n} ligas, umbral driver ${DRIVER_MEM_LIMIT_MB} MB) ==="
i=0
while IFS= read -r lg; do
  [ -z "$lg" ] && continue
  i=$((i+1))
  say "--- [$i/$n] $lg ---"
  $PY scripts/update_pending_matches.py --league "$lg" --solo-sin-stats --apply >> "$LOG" 2>&1
  grep -E "TOTALIZACIÓN|Procesados OK|No encontrados|Reciclajes" "$LOG" | tail -3 | tee -a "$LOG"
done < "$LIST"
say "=== BACKFILL STATS fin ==="
