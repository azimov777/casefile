---
name: casefile
description: Connecting an agent harness (Claude Code, Codex, Hermes or another MCP client) to a Casefile task tracker installation over MCP, either one installed on the same machine or a shared one running on a server, recovering when the casefile MCP server refuses a call with 401, watching the tracker journal for news between agent sessions, and installing or updating this skill as a plugin. Applies when Casefile is being installed or connected, when an agent joins an installation that runs on a server, when the casefile server is missing from the harness or answers 401 unauthorized, when answers and remarks in the tracker have to reach an agent with no open session, and when this skill was read from the server and is not yet installed in the harness. The working rules of the tracker itself arrive with the MCP server, in its instructions and tool descriptions, and are not part of this skill.
---

# Casefile outside MCP

Casefile is a self-hosted task tracker for agents. Everything about working with tasks
arrives over the MCP connection itself: the server's instructions and the description of
each tool. This skill covers what the MCP connection cannot carry: how the connection is
made, what a refused token means, how news reaches an agent between sessions, and how
this skill gets into a harness and stays current.

## Connecting to an installation

### Address and token from the installer on this machine

The installer (`install.sh` on macOS and Linux, `install.ps1` on Windows) prints the board
URL, an `MCP:` line with the MCP address, and a connect command with a token. The MCP
address is the one on that `MCP:` line: an installation can run on another port or behind
a public URL, so no default port stands in for it.

The token is in the installer output. On an installation in `~/casefile` it is also read
without printing it anywhere else:

```bash
cd ~/casefile && docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token
```

The token belongs in the harness's MCP configuration only; it does not go into the chat,
into files of the project or into other configuration.

### Claude Code

```bash
claude mcp add --transport http --scope user casefile <MCP address> --header "Authorization: Bearer <token>"
```

`claude mcp list` then shows `casefile` as connected.

### Codex

Codex reads the server from `~/.codex/config.toml`:

```toml
[mcp_servers.casefile]
url = "<MCP address>"
http_headers = { Authorization = "Bearer <token>" }
```

The key is `http_headers`: a `headers` key in the Claude Code format is not applied by
Codex, and its requests then go out without `Authorization`.

### Hermes

Hermes reads the server from `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  casefile:
    url: "<MCP address>"
    headers:
      Authorization: "Bearer <token>"
```

### Other MCP clients

A streamable HTTP server at the MCP address, with the header
`Authorization: Bearer <token>`.

### After the server is added

A running session does not pick up a newly added MCP server. In Claude Code `/mcp`
reconnects the servers; in the other harnesses the server appears in the next session.
Until then the tracker's tools are absent from the session, which is a matter of the
session and not of the installation.

### An installation on a server, run by someone else

On a shared installation, where people sign in with an email and a password, there is no
installer output and no `agent-token` to read. The token is issued by the user in their
own signed-in session: in the board's access screen or with `POST /api/v1/tokens`. Any
person with an account issues tokens without the administrator. A token named after the
machine or harness stands apart in the user's token list. The MCP address
is the one the installation publishes; the board's connect screen shows it.

The installer of the service runs on the server, not on the machine where the agent
works: the agent's machine needs neither Docker nor an installation directory. The
access screen is the one named `Access` in the board's side panel; a token issued there
belongs to the user who issued it, who sees it with its last use and revokes it. The MCP
address is the installation's public address, reachable from the agent's machine: the
`localhost` address printed by the installer on the server points at the agent's own
machine instead. With that address and token the harness is configured as in the
sections above.

This skill reaches the agent's machine by the Casefile install line in skill-only mode.
It installs the skill into every harness it finds on the machine and prints where it
stands, without Docker, an installation directory or a token:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

The per-harness commands under "Installing and updating this skill" do the same one
harness at a time.

A token revoked by the user or by the administrator, and every token of an account the
administrator disabled, is refused with `401 unauthorized` and
`details.reason: token_revoked`, as described in the next section. Access comes back
only with a new token from the same access screen; enabling a disabled account again
does not revive its old tokens.

## 401 from the casefile server

A call refused with `401 unauthorized` carries the reason in `details.reason`:

- `token_revoked` — the token was revoked by its owner or by the administrator, or the
  account that issued it was disabled. A disabled account takes all of its tokens with
  it, and enabling the account again does not bring them back. Only a new token from
  the user restores access; repeating the call with the same token gets the same answer.
- a token that never reached the server — in Claude Code a header built from an unset
  environment variable is sent as the literal text, and in Codex a `headers` key is
  ignored. The server then sees no valid token at all, and the cause lies in the
  harness configuration above.

After the configuration is corrected, the new token reaches the tools only after a
reconnect (`/mcp` in Claude Code) or a new session.

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

Where it is missing, the install line in skill-only mode installs it into every harness
on the machine and leaves the running service as it is:

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
```

```powershell
$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

A session that was already running sees the new skill after a restart, or after
`/reload-plugins` in Claude Code.

Running the Casefile install line again installs the skill into every harness it finds
on the machine, including one that appeared after the first install. Each harness also
installs and updates it by itself:

### Claude Code

```bash
claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills
claude plugin install casefile@casefile --scope user
```

With auto-update on for the `casefile` marketplace, Claude Code updates the plugin
itself. A new version reaches a running session after a restart or `/reload-plugins`.

### Codex

```bash
codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse skills
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
