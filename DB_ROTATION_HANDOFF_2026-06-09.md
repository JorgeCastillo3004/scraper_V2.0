# DB Password Rotation — Handoff to Angel + Jorge

**Date:** 2026-06-09
**Done by:** José (with Claude), on the DB server `96.30.195.40` (`wohhu-db` container, postgres:16-alpine).

> ⚠️ **This file contains a live credential. After Angel/Jorge have it, delete this file
> and store the password in the team password manager. Do NOT commit it anywhere.**

## What changed

- **Rotated the `wohhu` Postgres role password** (the role all apps + scraper use; it's also the DB superuser).
- **Port: UNCHANGED** — still `5432`. (Port change was deferred — it would require recreating the container, which also serves the Keycloak DB.)
- **Host: UNCHANGED** — `96.30.195.40`, still internet-accessible (per decision: José runs test queries from his machine).
- **Other roles untouched** — `db_admin`, `keycloak` passwords NOT changed.

## New credentials

| Field | Value |
|---|---|
| Host | `96.30.195.40` |
| Port | `5432` |
| User | `wohhu` |
| Database | `sports_db` |
| **New password** | `D#jpWA3bu9pyumzg!f5_zSLfxbV%qPX!` |

Password is 32 chars and deliberately avoids `@ : / " ' \` and space, so it's safe to paste
directly into TOML values and `postgres://` / connection-string forms without escaping.

## What Angel + Jorge need to do (the consumer side)

Update the password in **4 places**, then redeploy/re-run each:

1. **core-ms** — `cfg/settings.toml` → `[dev].database.password`
2. **backoffice-ms** — `cfg/settings.toml` → `[dev].database.password`
3. **bet-scoring-ms** — `cfg/settings.toml` (`/ms-bet-scoring/cfg`) → `[dev].database.password`
4. **scraper** — `config.py` → the DB password field (`FS_PASSWORD` / DB password var)

> Note on the running containers: their `settings.toml` is **baked into the image**. The durable
> fix is to rebuild the images with the new password and redeploy (matches how the live images
> were built — see deploy provenance notes). A temporary in-container edit + `docker restart`
> also works but is lost if a container is recreated.

## Verification done

- New password authenticates over TCP from a non-loopback path (the internet-facing
  `scram-sha-256` rule): confirmed `EXTERNAL_NEWPW_OK`.
- A wrong password is correctly rejected (`FATAL: password authentication failed`).
- `pg_hba.conf`: loopback/local = `trust` (no password, normal); `host all all all scram-sha-256`
  = every external connection requires the password.

## Still pending (not done here)

- Port change (deferred).
- RabbitMQ `guest:guest` rotation (deferred — UAT, no rush).
- NOWPayments keys (deferred — UAT, no rush).
- Keycloak role/admin rotation (deferred until José + Claude resolve SSO issues).
