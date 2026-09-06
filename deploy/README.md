# deploy/ — unidades de servicio

Copia de lo que está **instalado en el servidor** (`104.156.244.145`), para poder
reinstalarlo si se pierde. Operación: [`../documentacion/RUNBOOK_LIVE_SERVIDOR.md`](../documentacion/RUNBOOK_LIVE_SERVIDOR.md).

## Instalado y corriendo (unidades de **usuario**)

| Archivo | Destino en el server | Estado |
|---|---|---|
| `scraper-live.service` | `~/.config/systemd/user/` | ✅ enabled + active |
| `scraper-logrotate.service` | `~/.config/systemd/user/` | ✅ (oneshot, lo dispara el timer) |
| `scraper-logrotate.timer` | `~/.config/systemd/user/` | ✅ enabled, cada 6 h |
| `rotate_logs.sh` | `/home/scraper/live_v2/` | ✅ (chmod +x) |

Son de **usuario**, no de sistema: `scraper` no tiene sudo sin password, así que no se
puede escribir en `/etc/systemd/system`.

### Reinstalar desde cero

```bash
scp deploy/scraper-live.service deploy/scraper-logrotate.{service,timer} \
    scraper_server:~/.config/systemd/user/
scp deploy/rotate_logs.sh scraper_server:/home/scraper/live_v2/

ssh scraper_server '
  chmod +x /home/scraper/live_v2/rotate_logs.sh
  loginctl enable-linger scraper          # ← IMPRESCINDIBLE: sin esto no arranca al boot
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user daemon-reload
  systemctl --user enable --now scraper-live.service
  systemctl --user enable --now scraper-logrotate.timer
'
```

## Aún NO instalado (de la spec de ejecución permanente)

| Archivo | Nota |
|---|---|
| `scraper-engine.service` | Diseñado 2026-06-26 como unidad **de sistema** (root). Para usarlo hay que **adaptarlo a unidad de usuario** como las de arriba |
| `scraper-panel.service` | Ídem |

Ver [`../documentacion/especificacion_ejecucion_permanente.md`](../documentacion/especificacion_ejecucion_permanente.md)
y P8 en [`../documentacion/pendientes_puesta_en_marcha.md`](../documentacion/pendientes_puesta_en_marcha.md).
