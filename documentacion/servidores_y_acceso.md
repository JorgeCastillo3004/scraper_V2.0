# Servidores y acceso — scraper_V2.0

Los dos servidores del proyecto están definidos en `config.py` (`SERVER_*` y `DB_*`).
**No** se guardan contraseñas en este archivo; ver notas de dónde viven.

## 1. App / deploy server — `104.156.244.145` (SSH)

| Campo | Valor |
|---|---|
| Acceso | **SSH** |
| Alias | `ssh scraper_server` (definido en `~/.ssh/config`) |
| User | `scraper` · Puerto 22 |
| Key | `/home/jorge/work/scraper_V2.0/ssh_key/jorge_scraper_key` |
| Hostname remoto | `DevOps` · **live en `/home/scraper/live_v2`** (deploy vigente); `/home/scraper/scraper_v3` = código viejo mar/abr, no se usa |

Entrada en `~/.ssh/config`:
```
Host scraper_server
    HostName 104.156.244.145
    User scraper
    Port 22
    IdentityFile /home/jorge/work/scraper_V2.0/ssh_key/jorge_scraper_key
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
```

Notas:
- `IdentitiesOnly yes` es **necesario**: sin él el agente ofrece otras keys primero y da
  `Too many authentication failures`.
- La clave pública ya está instalada en `~scraper/.ssh/authorized_keys` del server
  (fingerprint `SHA256:aDpt…VX7w`, coincide con la privada local). Por eso alcanzó con
  crear el alias local; no hubo que instalar nada del lado servidor.
- ⚠️ Existe un `Host server` **viejo** en `~/.ssh/config` que apunta a
  `root@104.156.244.145` con `~/.ssh/id_ed25519` (otro user/otra key). No confundir con
  `scraper_server`.

### Qué corre hoy en este server

El **live** (`main2.py`, 9 deportes) corriendo permanente bajo **systemd de usuario**
(`scraper-live.service` + `scraper-logrotate.timer`, con `loginctl enable-linger scraper`).
Arranca solo tras un reboot.

👉 **Operación completa en [`RUNBOOK_LIVE_SERVIDOR.md`](RUNBOOK_LIVE_SERVIDOR.md)**
(comandos, logs, rotación, diagnóstico).

Notas:
- El usuario `scraper` **no tiene sudo sin password** → nada de unidades en
  `/etc/systemd/system`; todo va por `systemctl --user` (requiere
  `export XDG_RUNTIME_DIR=/run/user/$(id -u)` en SSH no interactivo).
- El server **no tiene** los scripts de Inconsistencias/fixtures: solo lo que el live usa.

## 2. DB server — `96.30.195.40` (solo Postgres)

| Campo | Valor |
|---|---|
| Acceso | **Postgres TCP** (puerto 5432). **No** hay SSH nuestro a este server. |
| Base | `sports_db` · User `wohhu` |
| Password | en `config.py` (`DB_PASS`); rotado 2026-06-09 (ver `ssh_key/DB_ROTATION_HANDOFF_2026-06-09.md`) |

Conexión (sin exponer el password):
```bash
cd /home/jorge/work/scraper_V2.0
PGPASSWORD=$(env_sports/bin/python -c "import config; print(config.DB_PASS)") \
  psql -h 96.30.195.40 -p 5432 -U wohhu -d sports_db
```

Notas:
- Es la BD contra la que corren el panel y el live (operación normal del scraper).
- ⚠️ **Un solo escritor:** el live del servidor y cualquier script local escriben en
  ESTA misma BD. Antes de correr algo pesado en local, verificar qué hace el live
  del servidor (y viceversa). Decisión P7 de `pendientes_puesta_en_marcha.md`.
- Es **infra compartida de José** (contenedores `wohhu-db` postgres:16-alpine, Keycloak,
  core-ms, backoffice-ms, bet-scoring-ms). El puerto 22 está abierto pero **no** tenemos
  key/alias/known_hosts para SSH a este host desde esta máquina: el SSH lo hacía José desde
  su equipo. Si aparece una key para él, agregar aquí el alias correspondiente.
- Regla dura del proyecto: NUNCA `DELETE/DROP/TRUNCATE` en `sports_db` (ver `CLAUDE.md`).
