<div align="center">

# Casefile

**The task tracker your AI agents keep for each other.**

Every task carries a case file — decisions, failed attempts, findings, open questions — so the next agent,<br>
with a fresh context and zero memory, picks up exactly where the last one stopped. You watch it all on a live board.

[![CI](https://github.com/azimov777/casefile/actions/workflows/images.yml/badge.svg)](https://github.com/azimov777/casefile/actions/workflows/images.yml)
![MCP server](https://img.shields.io/badge/MCP-server-8A2BE2)
![Self-hosted](https://img.shields.io/badge/self--hosted-Docker-2496ED)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

**Install on macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | sh
```

**Install on Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
```

All you need is Docker. The board opens at **http://localhost:8080**, and the installer prints the one command that connects your agent. Casefile updates itself every time Docker starts.

**Or let your agent do it.** Paste this into Claude Code, Codex or Cursor:

> Install Casefile for me by following https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/demo-dark.gif">
  <img alt="An agent creates a task and works it over MCP — the board picks up the new card, follows it across statuses, and the task page shows the agent's own case entries, live and without a reload" src="docs/assets/demo-light.gif" width="900">
</picture>
</div>

## Why

Agents are smart, but they forget. A session ends or the context fills up, and the next one starts from scratch: re-reading the code, re-trying what already failed, re-asking what you already answered.

Casefile gives every task a **case file** — an append-only log the agent writes as it works.

- **Hand-offs that survive a fresh context.** The next agent reads the latest summary, the open questions and an index of the case, then carries on. No re-discovery.
- **Built for agents, over MCP.** Agents create and split tasks, record decisions and dead ends, ask you questions, and close with a verdict on every check.
- **You stay in the loop.** A live board and task pages show what every agent is doing. Answer questions, leave remarks and hand each agent its own access — right from the browser.
- **Guardrails, not bureaucracy.** No closing without a summary and a passed verdict per check; no starting a blocked task. Nothing else — no sprints, no estimates, no automation.
- **Yours, on your machine.** Runs locally in Docker and listens on localhost only. Nothing leaves your computer — unless you turn on sign-in and put it on your own server for your team ([Network mode](#network-mode)).

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/question-dark.png">
  <img alt="A task waiting on a blocking question the agent asked the human" src="docs/assets/question-light.png" width="900">
</picture>
</div>

## Connect your agent

The installer prints a ready-made command with your token and its actual MCP address
filled in — by default:

```bash
claude mcp add --transport http --scope user casefile http://localhost:8100/mcp \
  --header "Authorization: Bearer <token>"
```

Any other MCP client works the same way: streamable HTTP at the MCP address the installer
printed (`http://localhost:8100/mcp` by default) with that header.

**A second agent, without the terminal.** The board carries the same snippets.
**Connect an agent** shows this installation's MCP address and ready-made snippets for
Claude Code, Codex and any client that takes an `mcpServers` JSON — no secret on the
screen, a placeholder where the token goes. **Access** lists every token the installation
has: who it speaks for, what it opens, who issued it and when it was last used. From there
you register an agent, issue its own token, copy the snippet with the secret already in
it — shown once — and revoke it when that agent is done. Give each agent a token of its
own and its case entries are signed with its name instead of one shared `agent`.

For the best case files, also give your agent the [skill](skill/tracker-agent/SKILL.md) that teaches the discipline (Claude Code: `~/.claude/skills/tracker-agent/SKILL.md`).

## Everyday

| | |
|---|---|
| Update right now | run the install line again |
| Turn auto-update off | `CASEFILE_AUTO_UPDATE=false` in `~/casefile/.env` |
| Stop / start | `docker compose stop` / `docker compose start` in `~/casefile` |
| Remove everything, data included | `docker compose down -v` in `~/casefile` |
| Move to another machine or your own server | [`docs/moving.md`](docs/moving.md) |
| Back up your data / restore into a clean install | [`docs/backup-restore.md`](docs/backup-restore.md) |

Ports and other settings live in `~/casefile/.env` — see [`.env.example`](.env.example).

## Network mode

Out of the box Casefile listens on localhost only, and you type nothing: the installation
creates an administrator account for you (`owner@localhost`) and the board signs into it
by itself. To reach it from other machines, turn on **sign-in**: then everyone signs in
with their own email and password, and every entry is signed by the person who made it.
It is one team per installation — everyone signed in sees every task. The only role is
the **administrator** flag, and all it opens is managing people.

1. Add to `~/casefile/.env`:

   ```bash
   CASEFILE_LOGIN=password            # everyone signs in with email and password
   CASEFILE_BIND=0.0.0.0              # publish the board and MCP beyond localhost
   TRACKER_MCP_PUBLIC_URL=http://<server>:8100/mcp   # what agents on other machines use
   ```

2. Run `docker compose up -d` in `~/casefile`.

3. Give yourself a password. The administrator account the installation made has none;
   this prints a generated one, once:

   ```bash
   docker compose run --rm api python -m app.cli account-password --email owner@localhost
   ```

   Add `--set-password` to type your own instead (12 characters at least, asked twice,
   no echo). Your email can be changed too:
   `account-update --email owner@localhost --new-email you@example.com`.

4. Add your teammates — on the board, or on the server:

   ```bash
   docker compose run --rm api python -m app.cli account-create --email alice@example.com --name alice
   ```

   It prints Alice's password once; hand it to her. `--admin` makes her an administrator
   too. `account-list` shows everyone, `account-update --disable` locks a person out and
   revokes every token they hold (their past entries stay signed with their name), and
   `account-password` resets a forgotten password. Casefile sends no mail: there is no
   address confirmation and no reset link.

The board at `http://<server>:8080` now opens with a sign-in screen. Agents keep
connecting to MCP with their tokens — sign-in is for people in the browser. Issue each
agent its own token on the **Access** screen; **Connect an agent** shows the address from
`TRACKER_MCP_PUBLIC_URL`.

**Coming from the owner password.** An installation locked with `TRACKER_PASSWORD_HASH`
before accounts existed keeps working after the update: sign-in turns on by itself, and
the old password becomes the password of the administrator account `owner@localhost` —
sign in with that email and the same password. The hash in `.env` is no lock any more; it
is only carried over once, and a password you set later is never overwritten by it.

**Plain HTTP is a hole.** Without TLS the passwords, the session cookies, the keys and
the agents' tokens cross the network in clear text for anyone on the path to read. Casefile
does not do TLS itself. Anywhere beyond a network you trust, keep `CASEFILE_BIND=127.0.0.1`
and put a reverse proxy with TLS in front of both ports — for example Caddy, which gets the
certificates and sends `X-Forwarded-Proto` by itself:

```
casefile.example.com {
    reverse_proxy 127.0.0.1:8080
}
mcp.casefile.example.com {
    reverse_proxy 127.0.0.1:8100
}
```

with `TRACKER_MCP_PUBLIC_URL=https://mcp.casefile.example.com/mcp`. A proxy that sends
`X-Forwarded-Proto: https` gets the session cookie marked `Secure`.

**Name your proxy.** Sign-in tells guessers apart by address (see **Guessing** below). Behind
a proxy every request arrives from the proxy, so the board must be told which address is
the proxy; only then does it take the browser's address from the proxy's
`X-Forwarded-For`. From anyone else that header is ignored — anybody can write it. Add to
`~/casefile/.env`:

```bash
CASEFILE_TRUSTED_PROXIES=172.18.0.1   # the address the board sees the proxy come from
```

and run `docker compose up -d`. That address is not the proxy's own: it is whatever
Docker shows the board. With the proxy on the same machine and `CASEFILE_BIND=127.0.0.1`,
it is the gateway of the installation's network, on Linux and Docker Desktop alike:

```bash
docker network inspect casefile_default -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

To check, run `docker compose logs ui`: each request line starts with the address it came
from — with the proxy named, the browser's; without, the proxy's. Several proxies or a
network go comma-separated (`172.18.0.1,10.0.0.0/8`). The network gets its address when it
is created, so after `docker compose down` check the gateway again. Keep
`CASEFILE_BIND=127.0.0.1` behind a proxy: Docker Desktop shows **every** connection to a
port published to the network as `192.168.65.1`, so naming that address would let anyone
claim any address. Without this line nothing breaks, but everyone behind the proxy shares
one address — and one guesser holds everybody at "try again later" again.

What else to know:

- **No sign-in, no network.** With `CASEFILE_BIND` beyond localhost and sign-in off, the
  board refuses to start instead of handing the administrator key to the whole network;
  `docker compose logs ui` says why.
- **Sessions.** A sign-in lasts 7 days (`TRACKER_SESSION_HOURS`). A session is a token
  with a deadline, kept in the database: restarting the installation does not end it.
  **Sign out** revokes it at once, a changed or reset password ends the person's other
  sessions, and disabling an account revokes all its tokens.
- **Guessing.** Wrong passwords are counted per address and per email, within a minute.
  After 5 from one address, sign-in answers "try again later" to that address — the right
  password included — until the minute has passed; after 5 for one email, from wherever
  they come, that email waits the same way. Other people sign in as usual. On top of that
  the whole installation takes at most 100 wrong passwords a minute, to keep guessing
  from burning the processor; guessing spread over many addresses and many emails that
  reaches it keeps everyone at "try again later" for as long as it goes on (an IPv6
  client counts as its whole `/64`). Open sessions and the agents, which use tokens, are
  not affected. A client is the address that opened the connection, or the one your
  named proxy reports (above). Docker Desktop hides the address of every connection from
  the network behind one of its own, so there the board tells clients apart only behind
  a proxy on the same machine.

## Under the hood

Python 3.14 · FastAPI · PostgreSQL · MCP over streamable HTTP · React 19 · Vite · Tailwind. The backend sits at the repository root, the web UI in [`ui/`](ui). The web UI speaks English and Russian; the design docs, the [developer guide](docs/DEVELOPMENT.md) and the agent-facing texts are in Russian for now.

## Contributing

Issues and pull requests are welcome — start with [CONTRIBUTING.md](CONTRIBUTING.md). Commits need a sign-off (`git commit -s`): it certifies you have the right to submit the code, and CI checks it.

## License

[MIT](LICENSE)

---

**Hiring?** I built Casefile and would be glad to hear about roles at **Anthropic** or **OpenAI** — reach me through [GitHub](https://github.com/azimov777).
