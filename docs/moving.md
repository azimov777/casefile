# Move Casefile to another machine

Take every task, case file, person and agent token from one Casefile and bring it up in
another — a new laptop, or your own server — with two HTTP requests. No shell on the old
machine, no `docker compose exec`, no Postgres.

This is a move you run when you decide to, not a backup: Casefile keeps no copies and
runs nothing on a schedule. An operator with a shell who wants a copy of one database can
still use [`backup-restore.md`](backup-restore.md); that procedure is unchanged.

## What you need

- **The old installation, running.** Update it first if it is behind — it updates itself
  every time Docker starts, or run the install line again.
- **An administrator.** On your own machine that is you: the board signs you in as the
  administrator `owner@localhost` without asking. On a server with sign-in turned on it is
  an account with the administrator flag. Export and import are refused to everyone else
  (`403 admin_required`): the archive carries every person's password hash and every
  token's hash.
- **A fresh installation on the new machine**, made with the one-line installer from the
  [README](../README.md). It must be **empty — no queues**: the archive replaces its data
  whole, and two trackers are never merged (`409 installation_not_empty`).
- **The same or a newer Casefile on the new machine** (see [Versions](#versions)).

## 1. Export from the old machine

The archive is one JSON document. Get your key and save the archive:

```bash
# On your own machine: the board's key comes from the installation itself.
KEY=$(curl -fsS http://localhost:8080/config.json | sed -E 's/.*"token":"([^"]*)".*/\1/')

curl -fsS -H "Authorization: Bearer $KEY" \
  http://localhost:8080/api/v1/installation/archive -o casefile-archive.json
```

On a server with sign-in, trade your email and password for a key instead — the answer
carries it as `data.token`:

```bash
curl -fsS -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "..."}' \
  https://casefile.example.com/api/v1/session
```

Use your installation's address and port if they are not the defaults. On Windows run the
same commands with `curl.exe`.

The file is a snapshot of that moment: whatever agents write to the old installation
afterwards is not in it. Stop the old installation (`docker compose stop` in its
directory) or point your agents at the new one before they carry on.

Keep the file private. It holds no secret in plain text, but it does hold password and
token hashes, and your whole tracker.

## 2. Import on the new machine

Install Casefile there with the install line, then post the file back **as is**:

```bash
KEY=$(curl -fsS http://localhost:8080/config.json | sed -E 's/.*"token":"([^"]*)".*/\1/')

curl -fsS -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  --data-binary @casefile-archive.json \
  http://localhost:8080/api/v1/installation/archive
```

A new server with sign-in turned on needs its administrator's password set first
([README, Network mode](../README.md#network-mode), step 3); sign in with it as in step 1.

The answer names the schema revision the archive was taken at, the one the data was
brought up to, the rows per table now in this installation, and what happened to access
(next section). One transaction does it all: if anything is refused, the new
installation is left exactly as it was.

## After the move

- **People** come across with their accounts and password hashes: everyone signs in with
  the same email and password as before. An account that never had a password (the
  `owner@localhost` of a machine without sign-in) still has none. Moving from your own
  machine to a server with sign-in, give it one again after the import, with the same
  command as for a fresh server ([README, Network mode](../README.md#network-mode),
  step 3) — the password you set there before the import belonged to the new
  installation's own `owner@localhost`, which the archive replaced.
- **Browser sessions** do not come across: a session belongs to the old address. On a
  server, sign in again. The session you imported with ends too — sign in with an account
  from the archive.
- **The new board keeps working** without a restart. Its own key, and the key of this
  machine's agent that the installer printed, survive the import; they now speak for the
  archive's `owner` and `agent`. The old machine's keys of the same names are revoked
  here — their secrets live on the old machine.
- **Every other agent token** comes across and keeps working: an agent that had a token
  of its own connects to the new MCP address with the same token. If a token should not
  work here — a machine you no longer trust — revoke it in **Access** on the board (or
  `DELETE /api/v1/tokens/{token_id}`). Nothing is revoked for you.
- **Case files are the same case files**: the same keys, the same entries, the same
  authors and times.

## Versions

- **Old to new works.** The archive names the schema revision it was taken at, and the new
  installation brings those rows up to its own schema with the same migrations that
  update a running installation.
- **New to old does not.** Migrations never run backwards, so an older Casefile refuses
  an archive from a newer one (`409 archive_revision_unknown`, with the archive's
  revision and the newest one it knows). Update the new machine — run the install line
  again — and import again.

## When it is refused

| Answer | Why | What to do |
|---|---|---|
| `403 admin_required` | The key is not an administrator's | Use the board's key, or sign in as an administrator |
| `409 installation_not_empty` | The new installation already has queues | Import into a fresh installation |
| `409 archive_revision_unknown` | The archive comes from a newer Casefile | Update this installation, then import |
| `422 archive_format_unsupported` | The file is not a Casefile archive | Post the file the export saved, unedited |
| `422 archive_invalid` | The archive contradicts itself or its schema; `details.reason` says how | Export again; do not edit the file |
| `413` from nginx | The file is over 512 MB | Not expected at any realistic size; tell us |

Behind a reverse proxy of your own, its own limit on request size applies too.

## What this does not do

- **No schedule and no copies.** One export and one import, when you run them.
- **No merging.** The new installation must be empty; there is no way to add one
  tracker's tasks to another's.
- **No moving back to an older version** (see [Versions](#versions)).
- **No part of an installation.** The archive is everything; there is no per-queue export.
