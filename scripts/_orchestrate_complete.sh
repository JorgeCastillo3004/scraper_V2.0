#!/usr/bin/env bash
# Orquestador secuencial sobre el driver de CORRECCIÓN (uno solo, compartido).
# Encadena: [espera FOOTBALL apply ya en curso] -> NFL apply -> update_pending apply.
# NO toca el driver de Live ni Firefox/gecko. Solo lanza scripts Python en serie.
set -u
cd /home/jorge/work/scraper_V2.0 || exit 1
PY=sports_env/bin/python
FB_PID="${1:-}"
LOG=logs/_orchestrate_complete.log
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

say "=== ORQUESTADOR INICIO (football_apply_pid=$FB_PID) ==="

# 1) Esperar a que termine el FOOTBALL apply ya en curso
if [ -n "$FB_PID" ]; then
  while kill -0 "$FB_PID" 2>/dev/null; do sleep 15; done
  say "FOOTBALL apply terminó. RESUMEN:"
  sed -n '/^RESUMEN/,/####/p' logs/_crear_fix_football_apply.out | tee -a "$LOG"
fi

# 2) NFL apply (AM._FOOTBALL)
say "--- NFL apply ---"
$PY crear_fixtures_ligas.py --sport AM._FOOTBALL --apply --leagues "USA_NFL" \
  >> logs/_crear_fix_nfl_apply.out 2>&1
say "NFL apply terminó. RESUMEN:"
sed -n '/^RESUMEN/,/####/p' logs/_crear_fix_nfl_apply.out | tee -a "$LOG"

# 3) update_pending apply (results + equipos faltantes) sobre las 11 ligas
say "--- update_pending --mode completo --apply ---"
$PY scripts/update_pending_matches.py --mode completo --apply \
  --league "FOOTBALL/WORLD_World Cup" \
  --league "FOOTBALL/BRAZIL_Serie A Betano" \
  --league "FOOTBALL/BOLIVIA_Division Profesional" \
  --league "AM._FOOTBALL/USA_NFL" \
  --league "FOOTBALL/COLOMBIA_Primera A" \
  --league "FOOTBALL/ECUADOR_Liga Pro" \
  --league "FOOTBALL/EUROPE_Conference League" \
  --league "FOOTBALL/PERU_Liga 1" \
  --league "FOOTBALL/PARAGUAY_Copa de Primera" \
  --league "BASEBALL/MEXICO_LMB" \
  --league "FOOTBALL/CHILE_Liga de Primera" \
  >> logs/_update_pending_apply.out 2>&1
say "update_pending terminó. TOTALIZACIÓN:"
sed -n '/TOTALIZACIÓN/,/====/p' logs/_update_pending_apply.out | tail -20 | tee -a "$LOG"

say "=== ORQUESTADOR FIN ==="
