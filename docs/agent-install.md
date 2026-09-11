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

## 6. Report to the user

In one short message: the board URL, that you are connected, and that Casefile updates
itself every time Docker starts. To remove it later: `docker compose down -v` in `~/casefile`.
