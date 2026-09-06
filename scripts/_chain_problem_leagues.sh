#!/usr/bin/env bash
# Encadena: espera el FIXTURES en curso -> corre RESULTS para las 9 ligas problema.
# Reusa el driver de corrección vivo. NO toca el driver ni Live.
set -u
cd /home/jorge/work/scraper_V2.0 || exit 1
PY=sports_env/bin/python
FIX_PID="${1:-}"
LOG=logs/_chain_problem.log
LEAGUES=(--leagues "ASIA_World Cup" "AUSTRALIA & OCEANIA_World Cup" "SOUTH AMERICA_World Cup" "EUROPE_World Cup" \
        "NORTH & CENTRAL AMERICA_World Cup" "AFRICA_World Cup" "COSTA RICA_Primera Division" "USA_MLS" "MEXICO_Liga MX")
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

say "=== CHAIN INICIO (fixtures_pid=$FIX_PID) ==="
if [ -n "$FIX_PID" ]; then
  while kill -0 "$FIX_PID" 2>/dev/null; do sleep 15; done
  say "FIXTURES terminó. RESUMEN:"
  sed -n '/^RESUMEN/,/####/p' logs/_extrae_problem_fixtures.out | tee -a "$LOG"
fi

say "--- RESULTS --apply (9 ligas) ---"
$PY crear_fixtures_ligas.py --sport FOOTBALL --results --apply "${LEAGUES[@]}" \
  >> logs/_extrae_problem_results.out 2>&1
say "RESULTS terminó. RESUMEN:"
sed -n '/^RESUMEN/,/####/p' logs/_extrae_problem_results.out | tail -12 | tee -a "$LOG"
say "=== CHAIN FIN ==="
