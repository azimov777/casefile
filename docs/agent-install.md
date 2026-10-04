# Install Casefile — instructions for an AI agent

You are setting up Casefile for the user: a local task tracker that agents use over MCP.
Run every step yourself, in order. Claude Code and Codex sign in with OAuth and need no
token. A harness without OAuth uses the agent key: never print it in the chat or write it
to any file other than that harness's MCP configuration.

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
and prints the board URL and the MCP URL. It also installs the Casefile plugin and skill
by itself into every agent it finds on the machine (Claude Code, Codex, Hermes, other
agents through `npx skills`) and prints one line per harness: `installed <version>`,
`not found` or `failed` with the command to repeat by hand. In Claude Code and Codex the
plugin carries the connection too, and the installer then signs them in with OAuth
(a browser page) — when it has a terminal; without one it prints the sign-in commands
instead. For Hermes it prints a config block with `auth: oauth` (no token); for other
clients without OAuth it prints the agent key.

That step changes files that belong to other programs: `~/.claude/settings.json` (it adds
`"autoUpdate": true` inside `extraKnownMarketplaces.casefile`), `~/.codex/config.toml`, the
manual MCP entries `casefile` and `tracker` that point at this installation, and
`~/.agents/skills`. The installer prints that list; on the user's terminal it asks `[y/N]`,
and `N` skips the whole step and leaves those files alone. Before the first change to a
file it saves a copy next to it (`settings.json.casefile-bak`, `config.toml.casefile-bak`;
kept, never overwritten; it holds whatever the file held, a token of a removed manual entry
included) and writes only the line it needs. An agent usually has no terminal
to answer on, and then the installer asks nothing: tell the user what it will change before
you run it. Variables, in front of `sh`:

- `CASEFILE_SKILL=0` skips the plugin step (the service is installed all the same);
  `CASEFILE_SKILL=1` answers the question in advance. Put `CASEFILE_SKILL=0` in front if the
  user does not want the step.
- `CASEFILE_PLUGIN_AUTOUPDATE=0` installs the Claude Code plugin without `autoUpdate`; update
  it with `claude plugin update casefile@casefile`.

If port 8080 or 8100 is taken, put `CASEFILE_PORT=<free port>` and/or
`TRACKER_MCP_PORT=<free port>` into `~/casefile/.env` and run the install line again.

If Casefile already runs on this machine (`~/casefile` exists), it may have been installed
before v0.8.0 or kept current by its own hourly update: neither put the skill into your
harness. Go on with step 3 and do the check at the start of step 4 all the same.

## 3. Connect yourself over MCP

Use the MCP address from the `MCP:` line the installer printed in step 2 — never assume a
default port. The installation may be using a different port, or a public URL it was
told to use.

- **Claude Code and Codex:** the plugin from step 2 already carries the connection to that
  address (Codex on another address than `http://127.0.0.1:8100/mcp` gets an
  `[mcp_servers.casefile]` entry with only `url` in `~/.codex/config.toml`); no token goes
  into any file. What is left is the sign-in, if the installer could not run it (its
  `Signing the agents in` lines say so). It needs the user's terminal or session, so ask
  the user to do it once:
  - Claude Code: `/mcp` in the session, then `casefile` → **Authenticate**; or, in a
    terminal, `claude mcp login plugin:casefile:casefile`.
  - Codex: `codex mcp login casefile` in a terminal.

  On a machine of the user's own a browser page opens and closes at once: the agent is
  signed in as `claude` or `codex` without a password. The same commands sign in again
  after the user disconnects this agent on the board's **Access** screen
  (in Claude Code, `/mcp` → **Re-authenticate**).
- **Hermes** signs in with OAuth too, no key: add this block to `~/.hermes/config.yaml`:

  ```yaml
  mcp_servers:
    casefile:
      url: "<MCP address from the installer output>"
      auth: oauth
  ```

  Hermes opens the sign-in page itself on the first connection (or `hermes mcp login
  casefile`); on the user's own machine the page closes at once and the agent is signed in
  as `agent`. On a host without a browser Hermes offers pasting the redirect URL back or
  an SSH tunnel to its callback port; its device-code flow (`oauth.flow: device`) does not
  work here, because Casefile does not offer that grant. Not yet checked against a real
  Hermes: the match with Casefile's OAuth metadata was checked from Hermes's documentation
  and source, and the key below stays as the fallback for a Hermes that cannot sign in.
- **OpenCode** signs in with OAuth too, no key (it registers itself, RFC 7591): add this to
  `opencode.json` in the project, or to `~/.config/opencode/opencode.json`:

  ```json
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "casefile": {
        "type": "remote",
        "url": "<MCP address from the installer output>"
      }
    }
  }
  ```

  Then run `opencode mcp auth casefile` in a terminal: it opens the sign-in page, which on
  the user's own machine closes at once and signs the agent in as `agent`; `opencode mcp
  list` then shows `casefile` as connected. Do not add a `clientId`, and do not use
  `headers` with the key: the sign-in needs neither. OpenCode reads the skill from
  `~/.agents/skills/casefile` (step 4 puts it there), so it needs no extra step.
- **Any other client without OAuth** connects with the agent key. Take it from
  the installer output, or read it without printing it anywhere else:

  ```bash
  cd ~/casefile && docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token
  ```

  A streamable HTTP server — for Hermes too, if its sign-in fails — add to
  `~/.hermes/config.yaml` `headers: {Authorization: "Bearer <token>"}` in place of
  `auth: oauth`. Any other client: a streamable HTTP server at `<MCP address from the installer output>`
  with the header `Authorization: Bearer <token>`.

A running session does not pick up a new plugin or MCP server by itself: tell the user to
restart the session (in Claude Code, `/reload-plugins` and then `/mcp`).

### Joining an installation someone else runs

If the user does not own the installation but signs in to a shared one (a server where
people log in with an email and a password), skip steps 1 and 2: there is no installer of
the service to run and no `agent-token` to read. Ask the user for the installation's MCP
address — the board's **Connect an agent** screen shows it; it must be `https`. Then run
one line on the machine where you work: it installs the Casefile plugin connected to that
address into Claude Code and Codex, the skill into the other agents it finds, and starts
the sign-in. It needs no Docker, creates no installation directory and prints no token:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL='https://casefile.example.com/mcp'; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

The sign-in is OAuth: a browser page on the installation's MCP host, where the user signs
in with their email and password and picks the agent this client acts as. The default is
their own agent, `claude_<their name>` for Claude Code and `codex_<their name>` for Codex,
created on the first sign-in; your case entries are signed with that name. Without a
terminal the installer prints the sign-in commands of step 3 — ask the user to run them.
A harness without OAuth and a journal watcher running between sessions
(step 6) need an agent key instead: ask the user to issue one for their agent on the
board's **Access** screen and connect with it as in step 3. Then check the skill as in
step 4, **Install the Casefile skill**.

What the user should know, in one line each:

- The connection and the key are theirs: they see them on **Access** with the time of
  the last use and can disconnect or revoke them; other people see only their own, the
  administrator sees all.
- After a disconnect your next call is refused with `401 unauthorized` — sign in again
  with the commands of step 3. After a key is revoked
  (`details.reason: token_revoked`) — ask for a new key, do not retry.
- If their account is disabled, every connection and key they issued stops working at
  once, yours included, and enabling the account again does not bring them back.

### When the server answers 401

On a server someone else runs, the MCP address is the installation's public `https`
address from the board's **Connect an agent** screen; a `localhost` address printed on
that server points at your own machine instead. A connection made by the OAuth sign-in
lasts 30 days, and the harness renews it by itself.

A request refused with `401 unauthorized` names the reason in `details.reason`:

- `token_expired` on a connection — the harness renews it by itself; when it cannot,
  repeat the sign-in of step 3.
- `token_revoked` — the user or the administrator disconnected the connection or revoked
  the key, or disabled the account that issued it. A connection comes back with a new
  sign-in, a key only with a new key from the user; repeating the call with the same
  credentials gets the same answer.
- `account_disabled` — the account behind the connection is disabled; nothing gets in
  until the administrator enables it, and then only with a new sign-in or a new key.
- `missing_token` or `unknown_token` — no valid credentials reached the server. The cause
  is in the harness configuration: in Claude Code a header built from an unset environment
  variable is sent as literal text; in Codex only `http_headers` is applied and a `headers`
  key is ignored; a manual `casefile` entry with an old key shadows the plugin.

A corrected configuration reaches the tools only after a reconnect (`/mcp` in Claude Code)
or a new session.

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
directory, no token. Claude Code and Codex get the skill in the plugin that also carries
the connection: without an address it points at the default `http://127.0.0.1:8100/mcp`
(the skill works at once, no sign-in is started); for a server that is not on this machine
add its address in `CASEFILE_URL` (step 3 names it; `https` outside `localhost`).

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

It prints one line per harness, as in step 2. With an address it signs Claude Code and
Codex in as in step 3; without one it starts no sign-in. The commands below do the same for one harness at a time.

### Install it by hand

A fresh install of step 2 already did it for every harness it found: read its
"Installing the Casefile skill" lines and run the commands below only for your harness if
it says `not found` or `failed`, or if the check above found no skill. The installer
prints the same commands. Claude Code and Codex read the plugin from the `plugin` branch of
the Casefile repository, which holds only the plugin files and moves with each release;
`npx skills` reads the skill from the `stable` branch. Running the installer line again also installs the skill into a harness that
appeared later:

- **Claude Code:**

  ```bash
  claude plugin marketplace add azimov777/casefile#plugin
  claude plugin install casefile@casefile --scope user --config casefile_url=<MCP address>
  ```

  `casefile_url` is the MCP address of step 3; left out, it is `http://127.0.0.1:8100/mcp`.

  The CLI has no flag for automatic updates. Add `"autoUpdate": true` next to `"source"`
  inside `extraKnownMarketplaces.casefile` in `~/.claude/settings.json`: from the next
  session on Claude Code updates the plugin by itself.
- **Codex:**

  ```bash
  codex plugin marketplace add azimov777/casefile --ref plugin
  codex plugin add casefile@casefile
  ```

  The plugin connects Codex to `http://127.0.0.1:8100/mcp`. Another address goes into
  `~/.codex/config.toml` as two lines, without a token:

  ```toml
  [mcp_servers.casefile]
  url = "<MCP address>"
  ```

  To update: `codex plugin marketplace upgrade casefile`.
- **Hermes:** `hermes skills install azimov777/casefile/skills/casefile`; to update, run
  the same command again.
- **Any other agent:** `npx skills add azimov777/casefile#stable`; to update, run it again.

A plugin added earlier from `#stable` keeps working and updating. To move it to `plugin`,
run the installer line again, or by hand: Claude Code refuses the new `marketplace add`
with "differs from the one declared"; delete `casefile` from `extraKnownMarketplaces` in
`~/.claude/settings.json` and repeat it (`marketplace remove` would also uninstall the
plugin). Codex refuses with "already added from a different source": run
`codex plugin marketplace remove casefile` and repeat both Codex lines.

A running session does not see a new plugin: restart it, or run `/reload-plugins` in
Claude Code. Then sign in as in step 3.

The MCP server also serves the skill itself, as the resource `skill://casefile/SKILL.md`,
always of the same version as the server; a copy installed in the harness is there before
any connection exists. The `plugin` and `stable` branches move to a release only after
that release's images are published, so an installed skill never runs ahead of the server.

## 5. Verify

- `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/` prints `200`: the board is up.
- `claude mcp list` shows `plugin:casefile:casefile` as connected, `codex mcp list` shows
  `casefile` (other clients: list the MCP tools and look for `list_projects`). A server
  that needs authentication is not signed in yet: do the sign-in of step 3.
- The skill is installed: `claude plugin list` shows `casefile@casefile` enabled
  (Codex: `codex plugin list`; Hermes and others: look for the `casefile` skill in
  your harness's list of skills; OpenCode: `opencode debug skill`). If it is missing, do step 4. A session that was already
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
They are `WATCH_TASKS`, `TRACKER_URL`, `TRACKER_TOKEN_FILE` and `WAIT_SECONDS`.

A watcher outside the session needs a key of its own: the OAuth sign-in of Claude Code
and Codex stays inside the harness, and no outside process can use it. On a machine with
the installation it is the agent key of step 3 (`agent-token`); on an installation
someone else runs, the user issues a key for their agent on the board's **Access**
screen. Inside a session no key is needed: `wait_journal` goes over the connection you
already have.

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
