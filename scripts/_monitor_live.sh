#!/usr/bin/env bash
# Monitor liviano del Live runner + drivers del scraper.
# Imprime una línea de salud y la anexa a logs/_monitor_live.log.
# NO mata ni reinicia nada — solo observa.
cd /home/jorge/work/scraper_V2.0 || exit 1
TS=$(date '+%F %T')
LIVELOG=$(ls -t logs/live_*.log 2>/dev/null | head -1)

# main2.py (live runner) vivo?
M2=$(pgrep -f "main2.py" | head -1)
if [ -n "$M2" ]; then
  read -r ET CPU RSS STAT < <(ps -o etime=,%cpu=,rss=,stat= -p "$M2")
  M2STR="main2 PID=$M2 up=$ET cpu=${CPU}% rss=$((RSS/1024))MB stat=$STAT"
else
  M2STR="main2 CAIDO!!"
fi

# Último ciclo en el log live
CICLO=$(grep -oE "\[CICLO [0-9]+\]" "$LIVELOG" 2>/dev/null | tail -1)
LASTLINE=$(tail -1 "$LIVELOG" 2>/dev/null | cut -c1-80)
# ¿avanzó el log en los últimos 5 min?
AGE=$(( $(date +%s) - $(stat -c %Y "$LIVELOG" 2>/dev/null || echo 0) ))

# Drivers (FF marionette del scraper)
DRV=$(pgrep -fc "marionette")
# RSS del driver de corrección y live (sumando árbol por geckodriver)
GECKO=$(pgrep -fc geckodriver)

# Memoria del sistema
MEMFREE=$(free -m | awk '/Mem:/{print $7}')

# Errores recientes en el log live (últimas 200 líneas)
ERRS=$(tail -200 "$LIVELOG" 2>/dev/null | grep -ciE "traceback|exception|error|session deleted|connection refused")

LINE="[$TS] $M2STR | $CICLO log_age=${AGE}s | drivers=$DRV gecko=$GECKO | mem_disp=${MEMFREE}MB | errs(200)=$ERRS | last='$LASTLINE'"
echo "$LINE"
echo "$LINE" >> logs/_monitor_live.log
