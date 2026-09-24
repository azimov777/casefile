# Back up and restore a Casefile installation

This is the manual, one-off procedure for two things: taking a backup of a running
installation, and standing up a separate, clean installation from that backup — on the
same machine or a different one. Nothing here runs on a schedule; Casefile is a ledger,
not an orchestrator, and there is no automation in core for this (`docs/CONCEPT.md`).
Scheduling backups, rotating them, and verifying restores automatically is a job for the
paid service panel, not the open core.

Moving to another machine without a shell or Postgres — including onto a newer Casefile —
is [`moving.md`](moving.md): an export and an import over HTTP. This page is the
operator's route with a shell, for a copy of one database.

Commands below assume the standard install layout (`~/casefile`, `docker-compose.prod.yml`
+ `.env`, as `install.sh`/`install.ps1` lay it out — see the root `README.md`). Run them
from that directory.

## What gets backed up

`pg_dump` captures everything that lives in the database: tasks, case entries, projects,
participants and **token hashes**. It does not capture the two secret files that live in
the `ui-key` and `agent-key` volumes (`.secrets/ui-token`, `.secrets/agent-token`) — those
never touch the database, by design (`app/services/setup.py`: a token's secret exists
exactly once, at issue time, and only its hash is stored). This matters for restoring on
a different machine — see "Tokens after a restore" below.

## Taking a backup

```bash
cd ~/casefile
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > casefile-$(date +%Y%m%d-%H%M%S).dump
```

The single quotes matter: `$POSTGRES_USER` and `$POSTGRES_DB` are expanded inside the `db`
container, where compose has already filled them in from this directory's `.env`. Your own
shell never reads that file, so writing them unquoted would silently fall back to whatever
your shell has — wrong the moment `.env` sets its own names.

`-Fc` is the custom pg_dump format: compressed, and restorable with `pg_restore --clean`
over an existing database without a separate `DROP SCHEMA` step. The dump holds only the
logical content of the tables — no write-ahead log, no index bloat, no free page space —
so it is much smaller than the `pgdata` volume for the same data; a measured example is in
`docs/notes/docker.md`.

Store the file off the machine it came from — a copy that lives next to the database it
backs up is not a backup.

## Restoring into a clean installation

Pick a target directory (a fresh `~/casefile` on another machine, or any other directory
with its own `docker-compose.prod.yml` + `.env` on the same one — give it its own
`CASEFILE_PORT`/`TRACKER_MCP_PORT` if it runs next to another installation). The target's
Postgres image must be the same major version as the source's, or newer (Casefile ships
`postgres:17-alpine`; `pg_restore` cannot go backwards across major versions). Running the
dump and the restore through the same `postgres:17-alpine` image, via `docker compose
exec`, keeps the tool version aligned automatically — that's what the commands below do.

```bash
cd ~/casefile          # the target installation directory
docker compose up -d db
```

Wait for `db` to become healthy (`docker compose ps`), then restore into it:

```bash
cat /path/to/casefile-*.dump | \
  docker compose exec -T db sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges'
```

This works the same way whether `db` was just created empty or already holds an older
copy of the same installation (`--clean --if-exists` drops what is there first). Now bring
up the rest:

```bash
docker compose up -d
```

`migrate` runs against a database that is already at the dump's schema version, so it is a
no-op. `local-token` and `agent-token` find the participants and tokens the dump brought
in and, if the secret files in this installation's own `ui-key`/`agent-key` volumes don't
hash-match anything in the restored database (the normal case — those volumes were never
part of the dump), they mint fresh tokens for the `owner` and `agent` participants and
revoke the old ones with the same name. Read the fresh secrets the same way `install.sh`
does, and connect the board and your agent with them:

```bash
docker compose run --rm --no-deps -T local-token cat .secrets/ui-token
docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token
```

The board opens at the port this directory's `.env` sets for `CASEFILE_PORT`, and reads
its own key from `/config.json` — no manual step needed there once `ui` has (re)started
with the fresh volume.

## Tokens after a restore

Every token row travels with the dump, hash and all — a token that worked against the
source installation works against the restored one too, immediately, because the check is
purely "does some row's hash match this secret", with no notion of which machine issued
it. Bringing up the full stack (previous section) only fixes the two tokens with fixed
names, `local-ui` and `local-agent`, because those are the ones `local-token`/`agent-token`
look after — any other token issued from the **Access** screen (a per-agent token with its
own name) rides along unchanged and stays valid on the restored copy, exactly as it was on
the source.

This is not a bug to work around; it is what "restore my data" means. But it does mean a
restore onto a different machine, or into someone else's hands, is not itself an access
boundary. If you don't want a token to keep working on the restored copy — someone who
should not have this new installation, or a machine you no longer trust — revoke it there
explicitly:

- from the board's **Access** screen, or
- `DELETE /api/v1/tokens/{token_id}` over REST.

The installation's own `local-ui`/`local-agent` need no manual revocation: standing up the
full stack (previous section) already replaces them.

## What this procedure does not do

- **No volumes.** `ui-key` and `agent-key` (the token secret files) are not part of the
  dump and are not covered by this procedure. A restore always mints fresh `local-ui`/
  `local-agent` secrets on the target; anyone who needs to log in gets the new ones from
  the commands above, not the source installation's old ones.
- **No automatic access review.** As described above, every other token in the dump
  stays valid on the restored copy. Deciding what to revoke is a manual step, on purpose.
- **No scheduling, no retention, no off-site copy.** This document covers one dump and one
  restore, run by hand. Keeping daily copies, expiring old ones, and shipping them off the
  server they were taken on is the paid service panel's job, not core's.
- **No integrity check beyond row counts.** The procedure does not checksum the dump or
  diff two installations for you; verifying a restore worked is up to whoever runs it.
- **No downgrade path.** Restoring a dump taken on a newer Postgres major version onto an
  older one is not supported by `pg_restore` and is not attempted here.
