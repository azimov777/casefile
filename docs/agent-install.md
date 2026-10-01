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
and prints the board URL, the MCP URL and a ready-made connect command with the token. It
also installs the Casefile skill by itself into every agent it finds on the machine
(Claude Code, Codex, Hermes, other agents through `npx skills`) and prints one line per
harness: `installed <version>`, `not found` or `failed` with the command to repeat by hand.
`CASEFILE_SKILL=0` in front of the install line skips that step.

If port 8080 or 8100 is taken, put `CASEFILE_PORT=<free port>` and/or
`TRACKER_MCP_PORT=<free port>` into `~/casefile/.env` and run the install line again.

If Casefile already runs on this machine (`~/casefile` exists), it may have been installed
before v0.8.0 or kept current by its own hourly update: neither put the skill into your
harness. Go on with step 3 and do the check at the start of step 4 all the same.

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
- **Codex:** add this block to `~/.codex/config.toml`; it works in the terminal and in the
  Codex app (the app does not see shell variables, so the token goes in the header here):

  ```toml
  [mcp_servers.casefile]
  url = "<MCP address from the installer output>"
  http_headers = { Authorization = "Bearer <token>" }
  tool_timeout_sec = 90
  ```

  From a terminal only, the token can stay out of the file: `export CASEFILE_TOKEN=<token>`
  and write `bearer_token_env_var = "CASEFILE_TOKEN"` instead of the `http_headers` line.
- **Hermes:** add this block to `~/.hermes/config.yaml`:

  ```yaml
  mcp_servers:
    casefile:
      url: "<MCP address from the installer output>"
      headers:
        Authorization: "Bearer <token>"
  ```

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
above, using the MCP address the installation publishes. Then do step 4,
**Install the Casefile skill**, on your own machine, as it stands: no installer of the
service and no Docker are needed for it. One line on the machine where the agent runs
installs the skill into every agent it finds there and prints where it stands:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

It creates no installation directory and prints no token. The per-harness commands below
do the same one harness at a time.

What the user should know, in one line each:

- The token is theirs: they see it in their list with the time it was last used and can
  revoke it; other people see and revoke only their own, the administrator sees all.
- After a revoke your next call is refused with `401 unauthorized`
  (`details.reason: token_revoked`) — ask for a new token, do not retry.
- If their account is disabled, every token they issued stops working at once, yours
  included, and enabling the account again does not bring those tokens back.

## 4. Install the Casefile skill

Connecting gives you the tools; the skill teaches you how to use them — how to keep a
case, what to write before you stop, how to recover from a `401` and how to watch the
journal. Connecting is not finished until the skill is installed.

### Check whether the skill is installed

Check first, every time you connect, even to an installation that has run for a long
time. An installation made before v0.8.0 never installed the skill, and the hourly
self-update replaces only the service's images: it never installs the skill into a
harness. A running, up-to-date service says nothing about the skill in your harness.

- **Claude Code:** `claude plugin list` shows `casefile@casefile` with `Status: enabled`.
- **Codex:** `codex plugin list` shows `casefile@casefile` as installed.
- **Hermes:** `hermes skills list` shows `casefile`.
- **Any other agent** (`npx skills`): the file `~/.agents/skills/casefile/SKILL.md` exists.

If your harness has it, go on to step 5. If it is missing, one line installs it into every
harness on the machine without touching the running service — no Docker, no installation
directory, no token:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

It prints one line per harness, as in step 2. The commands below do the same for one
harness at a time.

### Install it by hand

A fresh install of step 2 already did it for every harness it found: read its
"Installing the Casefile skill" lines and run the commands below only for your harness if
it says `not found` or `failed`, or if the check above found no skill. The installer
prints the same commands; they read the skill from the `stable` channel of the Casefile
repository. Running the installer line again also installs the skill into a harness that
appeared later:

- **Claude Code:**

  ```bash
  claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills
  claude plugin install casefile@casefile --scope user
  ```

  The CLI has no flag for automatic updates. Add `"autoUpdate": true` next to `"source"`
  inside `extraKnownMarketplaces.casefile` in `~/.claude/settings.json`: from the next
  session on Claude Code updates the plugin by itself.
- **Codex:**

  ```bash
  codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills
  codex plugin add casefile@casefile
  ```

  To update: `codex plugin marketplace upgrade casefile`.
- **Hermes:** `hermes skills install azimov777/casefile/skills/casefile`; to update, run
  the same command again.
- **Any other agent:** `npx skills add azimov777/casefile#stable`; to update, run it again.

A running session does not see a new plugin: restart it, or run `/reload-plugins` in
Claude Code.

## 5. Verify

- `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/` prints `200`: the board is up.
- `claude mcp list` shows `casefile` as connected (other clients: list the MCP tools and
  look for `list_projects`).
- The skill is installed: `claude plugin list` shows `casefile@casefile` enabled
  (Codex: `codex plugin list`; Hermes and others: look for the `casefile` skill in
  your harness's list of skills). If it is missing, do step 4. A session that was already
  running does not see it: restart the session, or run `/reload-plugins` in Claude Code.

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
`wait_journal(task=key, after=<last seq>, types=["answer"], timeout=...)` a blocking
question already calls for. The gap this section is about is different —
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

In one short message: the board URL, that you are connected, that the Casefile skill is installed, and that Casefile updates
itself to each new release (it checks every hour). To remove it later: `docker compose down -v` in `~/casefile`.

Then tell the user what to say to their agent next — the same two phrases the installer
printed, and the same ones with copy buttons are on the board's `/start` page:

- Have work to hand over? Say: "File tasks in Casefile for my work: a project for it if
  there is none yet, and tasks with all their sections and checks, each small enough for
  one agent to finish in one go, each naming its environment in `context` — where the work
  lives and how to check it is done. Don't start the work itself; if I haven't described it
  yet, ask me."
- Then, in a new agent session, say: "Carry out the tasks for this work from the Casefile
  tracker. Hand them to agents, one task per agent, to save your own context, and give them
  cheaper models where those cope."
