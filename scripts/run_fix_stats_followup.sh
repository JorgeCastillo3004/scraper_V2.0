#!/bin/bash
# Runner focal: re-procesa solo las ligas con matches que quedaron <30 cats
# (excluye World Cup que tiene problemas separados).
set -e
cd "$(dirname "$0")/.."

SUMMARY=tmp/logs/sequence_summary.log
echo "" >> "$SUMMARY"
echo "=== FOLLOWUP SEQUENCE START $(date -Iseconds) ===" >> "$SUMMARY"

LEAGUES=(
  "ENGLAND_Premier League"
  "GERMANY_Bundesliga"
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
  echo "[$(date -Iseconds)] FOLLOWUP START  FOOTBALL/${LEAGUE_KEY}" >> "$SUMMARY"

  DISPLAY=:1 env_sports/bin/python scripts/fix_null_team_ids.py \
      --apply --only-stats-past \
      --league "FOOTBALL/${LEAGUE_KEY}" \
      > "$LOG" 2>&1 || true

  T1=$(date +%s); DT=$((T1-T0))
  RESUMEN=$(grep -A6 '^RESUMEN' "$LOG" | tail -7 | tr '\n' ' | ' || echo "no_summary")
  echo "[$(date -Iseconds)] FOLLOWUP DONE   FOOTBALL/${LEAGUE_KEY}  (${DT}s)" >> "$SUMMARY"
  echo "  ${RESUMEN}" >> "$SUMMARY"
done

echo "" >> "$SUMMARY"
echo "=== FOLLOWUP SEQUENCE END $(date -Iseconds) ===" >> "$SUMMARY"
