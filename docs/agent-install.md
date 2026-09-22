# Install Casefile — instructions for an AI agent

You are setting up Casefile for the user: a local task tracker that agents use over MCP.
Run every step yourself, in order. Never print the token in the chat or write it to any
file other than your own MCP configuration.

## 1. Check Docker

```bash
docker info
```

If Docker is missing or not running, stop and ask the user to install or start Docker
Desktop (https://docs.docker.com/get-docker/). Nothing else is required.

## 2. Install

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | sh
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

It installs into `~/casefile` (`%USERPROFILE%\casefile` on Windows), starts the services
and prints the board URL, the MCP URL and a ready-made connect command with the token.

If port 8080 or 8100 is taken, put `CASEFILE_PORT=<free port>` and/or
`TRACKER_MCP_PORT=<free port>` into `~/casefile/.env` and run the install line again.

## 3. Connect yourself over MCP

Use the MCP address from the `MCP:` line the installer printed in step 2 — never assume a
default port. The installation may be using a different port, or a public URL it was
told to use. Take the token from the installer output too, or read it without printing
it anywhere else:

```bash
cd ~/casefile && docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token
```

- **Claude Code:**
  `claude mcp add --transport http --scope user casefile <MCP address from the installer output> --header "Authorization: Bearer <token>"`
- **Any other MCP client:** add a streamable HTTP server at `<MCP address from the
  installer output>` with the header `Authorization: Bearer <token>`.

A running session does not pick up a new MCP server by itself: tell the user to restart
the session (in Claude Code, `/mcp` reconnects).

### Joining an installation someone else runs

If the user does not own the installation but signs in to a shared one (a server where
people log in with an email and a password), skip steps 1 and 2: there is no installer
output and no `agent-token` to read. Ask the user to issue a token for you themselves, in
the board's access screen or with `POST /api/v1/tokens` from their own signed-in session,
and to name it after this machine or harness so they can tell it apart later. Any person
with an account can do this without the administrator. Then connect with that token as
above, using the MCP address the installation publishes.

What the user should know, in one line each:

- The token is theirs: they see it in their list with the time it was last used and can
  revoke it; other people see and revoke only their own, the administrator sees all.
- After a revoke your next call is refused with `401 unauthorized`
  (`details.reason: token_revoked`) — ask for a new token, do not retry.
- If their account is disabled, every token they issued stops working at once, yours
  included, and enabling the account again does not bring those tokens back.

## 4. Install the skill (recommended)

The skill teaches how to keep a good case file. For Claude Code:

```bash
mkdir -p ~/.claude/skills/tracker-agent
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/skill/tracker-agent/SKILL.md \
  -o ~/.claude/skills/tracker-agent/SKILL.md
```

Other agents: put the same file wherever your harness keeps skills or instructions.

## 5. Verify

- `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/` prints `200`: the board is up.
- `claude mcp list` shows `casefile` as connected (other clients: list the MCP tools and
  look for `list_queues`).

## 6. Learn about news in your tasks

Casefile never pushes anything to you. If the owner answers a question or leaves a
remark while you are not reading the case, that answer just sits in the journal until
something asks for it — deliberately: delivery is a rejected design (`docs/CONCEPT.md`,
"Отвергнутые варианты"), because the tracker is a ledger, not an orchestrator. Asking is
the client's job, always.

The tracker gives you one long-polling primitive for this: `wait_journal` in MCP,
`GET /api/v1/journal?after=<seq>&wait=<seconds>` in REST (`wait` up to 60s). A call
blocks until either a matching entry lands or the timeout passes, then returns. Journal
entries are permanent — no expiry, no outbox — so you can always resume from the last
`seq` you actually saw: there is no "too old a cursor" error, and no risk of a gap if
you resume from exactly that number.

While your session is open on a task, this is nothing new: it is the same
`wait_journal(task=key, after=<last seq>, types=["answer"], timeout=...)` the skill
already covers ("Вопросы", "Ждать живым"). The gap this section is about is different —
**between one harness run and the next**, when no session is open at all. Nothing in
Casefile starts a harness or writes into a closed session; some outside process has to
do that, and Casefile does not ship one:

- **A harness with its own way to learn about news** (for example, a background watcher
  or a hook Claude Code keeps running) needs no script at all: point it at the same
  `wait_journal`/`GET /api/v1/journal` call and let it feed matches into a new or
  resumed session by whatever means it already has.
- **Nothing built in**: a minimal, temporary example that long-polls a fixed list of
  tasks and prints one line per new entry to stdout lives at
  [`scripts/watch-journal.sh`](../scripts/watch-journal.sh) — read its header before
  using it. It is not a supported tool: not wired into any `docker-compose*.yml`, it
  writes nothing to the tracker, and it does not know whether the agent it is watching
  for is alive. Running it is one command; what happens to a printed line (read it
  yourself, redirect it into a prompt, pipe it into whatever your harness accepts) is
  entirely up to you — Casefile has no opinion there.

Either way, the recipe is the same three things: which tasks to watch, which `seq` to
resume from, and how long a poll may wait before it comes back empty. The script's
header names the exact variables.

## 7. Report to the user

In one short message: the board URL, that you are connected, and that Casefile updates
itself every time Docker starts. To remove it later: `docker compose down -v` in `~/casefile`.
