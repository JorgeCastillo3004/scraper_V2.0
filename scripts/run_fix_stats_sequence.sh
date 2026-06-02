#!/bin/bash
# Runner secuencial: procesa todas las ligas de fútbol con --only-stats-past
# Mantiene el driver vivo entre ligas. Una liga termina → arranca la siguiente.
#
# Uso: bash scripts/run_fix_stats_sequence.sh
# Logs: tmp/logs/fix_FOOTBALL__<LEAGUE>.log + tmp/logs/sequence_summary.log
set -e
cd "$(dirname "$0")/.."

SUMMARY=tmp/logs/sequence_summary.log
mkdir -p tmp/logs
echo "=== SEQUENCE START $(date -Iseconds) ===" >> "$SUMMARY"

LEAGUES=(
  "ENGLAND_Premier League"
  "GERMANY_Bundesliga"
  "ITALY_Serie A"
  "TURKEY_Super Lig"
  "FRANCE_Ligue 1"
  "BELGIUM_Jupiler Pro League"
  "BRAZIL_Serie A Betano"
  "ARGENTINA_Liga Profesional"
  "COLOMBIA_Primera A"
  "WORLD_World Cup"
  "SPAIN_LaLiga"
  "MEXICO_Liga MX"
  "VENEZUELA_Liga FUTVE"
  "COSTA RICA_Primera Division"
  "CHINA_Super League"
)

for LEAGUE_KEY in "${LEAGUES[@]}"; do
  SAFE=$(echo "$LEAGUE_KEY" | tr ' /' '__')
  LOG="tmp/logs/fix_FOOTBALL__${SAFE}.log"
  T0=$(date +%s)
  echo "" >> "$SUMMARY"
  echo "[$(date -Iseconds)] START  FOOTBALL/${LEAGUE_KEY}" >> "$SUMMARY"
  echo "  log: ${LOG}" >> "$SUMMARY"

  DISPLAY=:1 env_sports/bin/python scripts/fix_null_team_ids.py \
      --apply --only-stats-past \
      --league "FOOTBALL/${LEAGUE_KEY}" \
      > "$LOG" 2>&1 || true

  T1=$(date +%s); DT=$((T1-T0))
  # Extraer linea RESUMEN del log
  RESUMEN=$(grep -A6 '^RESUMEN' "$LOG" | tail -7 | tr '\n' ' | ' || echo "no_summary")
  echo "[$(date -Iseconds)] DONE   FOOTBALL/${LEAGUE_KEY}  (${DT}s)" >> "$SUMMARY"
  echo "  ${RESUMEN}" >> "$SUMMARY"
done

echo "" >> "$SUMMARY"
echo "=== SEQUENCE END $(date -Iseconds) ===" >> "$SUMMARY"
