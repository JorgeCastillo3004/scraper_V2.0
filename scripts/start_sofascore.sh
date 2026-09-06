#!/bin/bash
# Abre el driver de SofaScore y LO DEJA VIVO, igual que el de FlashScore.
# Mantén esta terminal abierta: mientras viva el proceso, los scripts de prueba se
# reenganchan a este mismo navegador (tmp/sofascore_driver.json) y no abren otro.
#
#   ./scripts/start_sofascore.sh              # visible (por defecto)
#   HEADLESS=1 ./scripts/start_sofascore.sh   # sin ventana
cd "$(dirname "$0")/.." || exit 1
MODO="--no-headless"
[ -n "$HEADLESS" ] && MODO="--headless"
exec sports_env/bin/python scripts/start_driver.py \
    --session-file tmp/sofascore_driver.json \
    --label sofascore \
    --url https://www.sofascore.com \
    --sin-login \
    --lightweight \
    --profile-dir tmp/profiles/sofascore \
    $MODO
