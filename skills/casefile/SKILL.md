---
name: casefile
description: Applies when a Casefile task tracker is being installed, or an agent harness (Claude Code, Codex, Hermes or another MCP client) is connected to an installation on the same machine or on a server; when the casefile MCP server is missing, needs a sign-in or answers 401; when answers and remarks have to reach an agent between sessions through a journal watcher; and when this skill, read from the server, is not yet installed as a plugin or needs an update. Rules for tasks arrive with the MCP server.
---

# Casefile outside MCP

Casefile is a self-hosted task tracker for agents. Everything about working with tasks
arrives over the MCP connection itself: the server's instructions and the description of
each tool. This skill covers what the MCP connection cannot carry: how the connection is
made and signed in, what a `401` means, how news reaches an agent between sessions, and
how this skill gets into a harness and stays current.

## Connecting to an installation

There is one path: the Casefile plugin carries the skill and the MCP connection, and the
agent signs in with OAuth. No token goes into any file of Claude Code or Codex. An agent
key is only for a harness without OAuth and for a journal watcher between sessions.

### The MCP address

On the machine of the installation the installer (`install.sh` on macOS and Linux,
`install.ps1` on Windows) prints it on its `MCP:` line; an installation can run on
another port or behind a public URL, so no default port stands in for it. On a server
run by someone else it is the installation's public `https` address, shown on the
board's **Connect an agent** screen; the `localhost` address printed on the server points
at the agent's own machine instead.

### Claude Code and Codex: the plugin and the sign-in

The full install line installs the plugin connected to the installation's address. A
machine that only connects to a server gets it from the same line in skill-only mode,
with the address; it needs no Docker and creates no installation directory:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL='https://casefile.example.com/mcp'; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

Outside `localhost` the address is `https`: over plain `http` the service offers no
OAuth. Without `CASEFILE_URL` the line installs no plugin.

The installer starts the sign-in when it has a terminal. Otherwise, and after the user
disconnects the agent on the board's **Access** screen, the sign-in is repeated by hand:

- Claude Code: `/mcp` in the session, `casefile` → **Authenticate** (or
  **Re-authenticate**); in a terminal, `claude mcp login plugin:casefile:casefile`.
- Codex: `codex mcp login casefile`.

On the user's own machine the sign-in passes without a page: Claude Code acts as
`claude`, Codex as `codex`. On a server the browser shows the installation's sign-in
page; the user signs in with email and password and picks the agent, by default their
own `claude_<name>` or `codex_<name>`, created on the first sign-in. The connection lasts
30 days and the harness renews it by itself.

Codex keeps the plugin's address fixed at `http://127.0.0.1:8100/mcp`; another address
is an `[mcp_servers.casefile]` entry in `~/.codex/config.toml` with `url` alone, which
the installer writes.

### Hermes and other clients without OAuth: the agent key

On the machine of the installation the key is in the installer output, or read without
printing it anywhere else:

```bash
cd ~/casefile && docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token
```

On a server the user issues a key for their agent on the **Access** screen; an agent
issues no keys to itself. The key belongs in the harness's MCP configuration only, not
in the chat or in files of the project. Hermes reads it from `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  casefile:
    url: "<MCP address>"
    headers:
      Authorization: "Bearer <token>"
```

Any other client: a streamable HTTP server at the MCP address with the header
`Authorization: Bearer <token>`.

### After the connection is added

A running session does not pick up a new plugin or MCP server: in Claude Code
`/reload-plugins` and `/mcp` bring them in; in the other harnesses they appear in the
next session. Until then the tracker's tools are absent from the session, which is a
matter of the session and not of the installation.

## 401 from the casefile server

A request refused with `401 unauthorized` carries the reason in `details.reason`:

- `token_expired` on a connection — the harness renews it by itself; when it cannot,
  the sign-in above is repeated.
- `token_revoked` — the user or the administrator disconnected the connection or revoked
  the key, or disabled the account that issued it. A disabled account takes all of its
  connections and keys with it, and enabling it again does not bring them back. A
  connection comes back with a new sign-in, a key only with a new key from the user;
  repeating the call with the same token gets the same answer.
- `account_disabled` — the account behind the token is disabled; nothing gets in until
  the administrator enables it, and then only with a new sign-in or a new key.
- `missing_token` or `unknown_token` — no valid token reached the server. In Claude Code a header built from
  an unset environment variable is sent as the literal text; in Codex only
  `http_headers` is applied, a `headers` key is ignored; a manual `casefile` entry with an
  old key shadows the plugin. The cause lies in the harness configuration.

A corrected configuration reaches the tools only after a reconnect (`/mcp` in Claude
Code) or a new session.

## News between sessions

Casefile delivers nothing on its own. An answer from the user or a remark on a task stays
in the journal until someone asks for it. Inside a session the tracker's own long-poll
covers this; between sessions, when no agent is running at all, a process outside
Casefile does the asking.

The primitive is the same on both sides: `wait_journal` over MCP and
`GET /api/v1/journal?after=<seq>&wait=<seconds>` over REST (`wait` up to 60 seconds).
A call returns when a matching entry lands or when the wait runs out. Journal entries
never expire, so resuming from the last `seq` seen leaves no gap.

A watcher is set up with three things: which tasks it watches, which `seq` it resumes
from, and how long one poll waits before it comes back empty.

- A harness with its own background watcher or hook points it at the same journal call
  and feeds matches into a new or resumed session by its own means.
- A harness without one has a minimal, unsupported sample in the Casefile repository,
  `scripts/watch-journal.sh`: it long-polls a fixed list of tasks and prints one line
  per new entry to stdout. Its header names the variables (`WATCH_TASKS`,
  `TRACKER_URL`, `TRACKER_TOKEN_FILE`, `WAIT_SECONDS`). What happens to a printed line
  is up to the harness.

Inside a session `wait_journal` goes over the connection the agent already has and needs
no secret. A watcher between sessions reads a key from a file, since the OAuth sign-in
stays inside the harness: on the machine of the installation the agent key
(`agent-token`, read as above); on a server, a key the user issues for their agent on
the **Access** screen.

## Installing and updating this skill

The MCP server also serves this skill as the resource `skill://casefile/SKILL.md`, always
of the same version as the server. A copy installed in the harness is available before
any MCP connection exists; the plugin below installs it.

### Whether the skill is installed

Reading this text from the server does not mean the skill is installed in the harness.
An installation made before v0.8.0 never installed it, and the installation's hourly
self-update replaces only the service's images: it installs nothing into a harness. Each
harness shows whether the skill is there:

- Claude Code: `claude plugin list` lists `casefile@casefile` with `Status: enabled`.
- Codex: `codex plugin list` lists `casefile@casefile` as installed.
- Hermes: `hermes skills list` lists `casefile`.
- Other agents (`npx skills`): the file `~/.agents/skills/casefile/SKILL.md` exists.

Where it is missing, the install line in skill-only mode with the MCP address in
`CASEFILE_URL`, as under "Claude Code and Codex" above, installs it into every harness on
the machine and leaves the running service as it is. For an installation on the same
machine the address is its `MCP:` line, `http://127.0.0.1:8100/mcp` by default.

A session that was already running sees the new skill after a restart, or after
`/reload-plugins` in Claude Code.

Running the Casefile install line again installs the skill into every harness it finds
on the machine, including one that appeared after the first install. Each harness also
installs and updates it by itself:

### Claude Code

```bash
claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills
claude plugin install casefile@casefile --scope user --config casefile_url=<MCP address>
```

With auto-update on for the `casefile` marketplace, Claude Code updates the plugin
itself. A new version reaches a running session after a restart or `/reload-plugins`.

### Codex

```bash
codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills
codex plugin add casefile@casefile
```

Update: `codex plugin marketplace upgrade`.

### Hermes

```bash
hermes skills install azimov777/casefile/skills/casefile
```

Update: `hermes skills update`.

### Other agents

```bash
npx skills add azimov777/casefile#stable
```

Update: `npx skills update`.

All of these follow the `stable` branch, which moves to a release only after that
release's images are published, so the installed skill does not run ahead of the server.
