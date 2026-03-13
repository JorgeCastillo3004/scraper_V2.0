#!/bin/bash
# cleanup_memory.sh
# Limpia procesos innecesarios preservando: Selenium Firefox, Jupyter kernel, Claude, gnome-shell, VSCode

echo "=== MEMORIA ANTES ==="
free -h | grep Mem
echo ""

# ── Identificar procesos esenciales ──────────────────────────────────────────
SELENIUM_PID=$(pgrep -f "firefox.*marionette" | head -1)
JUPYTER_BROWSER=$(pgrep -f "firefox.*nbserver" | head -1)
JUPYTER_KERNEL=$(pgrep -f "ipykernel_launcher" | head -1)

echo "Preservando:"
echo "  Selenium Firefox : $SELENIUM_PID"
echo "  Jupyter Browser  : $JUPYTER_BROWSER"
echo "  Jupyter Kernel   : $JUPYTER_KERNEL"
echo ""

KILLED=0

# ── Matar tabs extra del Jupyter browser (conservar solo el más grande) ───────
if [ -n "$JUPYTER_BROWSER" ]; then
    # Obtener todos los tabs del Jupyter browser ordenados por memoria desc
    JUPYTER_TABS=($(ps --ppid $JUPYTER_BROWSER -o pid= --sort=-rss 2>/dev/null))
    # Conservar solo el primero (más pesado = tab activo del notebook)
    KEEP_TAB=${JUPYTER_TABS[0]}
    echo "  Jupyter tab activo conservado: $KEEP_TAB"
    for pid in "${JUPYTER_TABS[@]:1}"; do
        kill $pid 2>/dev/null && echo "  [KILL] Jupyter tab extra PID $pid" && ((KILLED++))
    done
fi

# ── Matar procesos Chrome/zygote (no usados por el proyecto) ─────────────────
for pid in $(pgrep -f "/app/extra/chrome" 2>/dev/null); do
    kill $pid 2>/dev/null && echo "  [KILL] Chrome PID $pid" && ((KILLED++))
done

# ── Matar Firefox huérfanos (sin marionette ni nbserver) ─────────────────────
for pid in $(pgrep -x firefox-bin 2>/dev/null); do
    # Saltar procesos esenciales y sus hijos
    ppid=$(ps -o ppid= -p $pid 2>/dev/null | tr -d ' ')
    if [ "$pid" = "$SELENIUM_PID" ] || [ "$pid" = "$JUPYTER_BROWSER" ] || \
       [ "$ppid" = "$SELENIUM_PID" ] || [ "$ppid" = "$JUPYTER_BROWSER" ]; then
        continue
    fi
    echo "  [KILL] Firefox huérfano PID $pid"
    kill $pid 2>/dev/null && ((KILLED++))
done

sleep 2
echo ""
echo "Procesos eliminados : $KILLED"
echo ""
echo "=== MEMORIA DESPUÉS ==="
free -h | grep Mem
echo ""
echo "=== TOP 8 POR MEMORIA ==="
ps aux --sort=-%mem | head -9
