---
name: casefile-setup
description: Use only when the Casefile MCP tools are missing from your tool list or answer 401 — never while they work. Finds where you run (Claude Code, Codex, Cursor, the Claude Desktop chat, claude.ai) and gives the person the one step that connects Casefile there, with the link. Once the tools answer, use the casefile skill instead.
---

# Connecting Casefile where you work

Casefile is a task tracker that agents reach over MCP. You are reading this because its
tools (`get_task`, `add_summary`, `close_task` and the rest) are not in your tool list, or
they answer `401`. The plugin that brought this file carries the instructions, not the
tools: the tools come from a Casefile **server** that the person runs and your harness
connects to. Your job now is small: find out where you run, tell the person the single
next step with its link, and stop. Do not try to work a task, and do not invent a tracker
of your own in the meantime.

Say one step at a time, in the person's language, and wait until they have done it.

## 1. Which tools do you have?

- **Casefile tools are listed but every call answers `401`:** the server is there and
  you are signed out (or the sign-in expired or was revoked). Go to the sign-in step of
  your harness below, not to an install.
- **No Casefile tools at all:** either there is no connection yet, or the session started
  before it was made. Find your harness below.

## 2. Where do you run?

Look at what you know about yourself. If you cannot tell, ask the person one question:
"Where are you talking to me — Claude Code, Codex, Cursor, the Claude desktop app chat,
or claude.ai in a browser or on the phone?"

### Claude Code

This plugin already carries the connection, to `http://127.0.0.1:8100/mcp` unless the
person set another address when installing it.

1. If you can run commands, check whether a server answers on that address. If you cannot, ask the person.
2. **No server yet:** the person installs Casefile with the one-line install in the README
   (macOS, Linux and Windows): https://github.com/azimov777/casefile — section "Install".
   You can also offer to follow the agent guide yourself, with their consent:
   https://github.com/azimov777/casefile/blob/main/docs/agent-install.md
3. **Server runs:** the person signs in once, in this session: `/mcp`, choose `casefile`,
   then **Authenticate** (or in a terminal `claude mcp login plugin:casefile:casefile`).
   A browser page opens and closes by itself on their own machine.
4. A running session does not pick up a new connection: the person runs `/reload-plugins`
   and then `/mcp`, or starts a new session.

### Codex

The plugin carries the connection to `http://127.0.0.1:8100/mcp`.

- **No server yet:** the install line in the README, as above.
- **Server runs:** the person signs in once in a terminal: `codex mcp login casefile`.
  A server on another address needs two lines in `~/.codex/config.toml`; the exact form is
  in step 3 of the agent guide:
  https://github.com/azimov777/casefile/blob/main/docs/agent-install.md#3-connect-yourself-over-mcp

### Cursor

The Cursor plugin points at `http://127.0.0.1:8100/mcp`. Sign-in to Casefile from Cursor
has not been verified here, so do not promise it. Send the person to step 3 of the agent
guide, which says how a client without a verified sign-in connects, and to the install
line in the README if no server runs yet:
https://github.com/azimov777/casefile/blob/main/docs/agent-install.md#3-connect-yourself-over-mcp

### The Claude desktop app chat

The chat does not use the plugin's connection. It needs its own extension, one file from
the latest release, installed by double-click:
https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb

Tell the person: download it, open it, keep the address `http://127.0.0.1:8100/mcp` for a
server on this machine (or the address of the server they use), click **Install**, and
sign in on the page that opens. It works only while the server runs and only in the
desktop app. Details:
https://github.com/azimov777/casefile/blob/main/docs/agent-install.md#claude-desktop-casefile-in-the-chat-app

### claude.ai in a browser, or the Claude app on a phone

These chats call connectors from Anthropic's cloud, which cannot reach a server on the
person's machine, and they do not load this plugin's connection at all. Say so plainly,
and do not suggest a workaround that is not documented. Two honest options:

- use Casefile from Claude Code, Codex or the Claude desktop app on the machine where the
  server runs;
- the server is run for them by someone else, or on a public `https` address: then
  the person needs that server's MCP address from its board ("Connect an agent" screen).
  Whether claude.ai accepts such a server as a custom connector has not been verified; say
  that too instead of promising it.

### Some other agent

Any client that speaks MCP over streamable HTTP can connect. Send the person to step 3 of
the agent guide:
https://github.com/azimov777/casefile/blob/main/docs/agent-install.md#3-connect-yourself-over-mcp

## 3. There is no server at all, or it belongs to someone else

- **Nobody has installed Casefile:** the install line in the README
  (https://github.com/azimov777/casefile) puts the whole thing on the person's machine and
  prints the board address and the MCP address. They need to run it themselves; tell them
  what it will change before they do, as the guide does.
- **A colleague or a company runs it:** you need that server's `https` MCP address (on
  the board, "Connect an agent"). The guide's section "Joining an installation someone
  else runs" covers the connection:
  https://github.com/azimov777/casefile/blob/main/docs/agent-install.md#joining-an-installation-someone-else-runs

## 4. Check, then hand over

The connection works when a Casefile tool is in your tool list and answers — for example
`list_projects` returns the projects instead of an error. A new connection often shows up
only in a new session: if the person did every step and the tools are still missing, ask
them to restart the session (in Claude Code `/reload-plugins`, then `/mcp`) and look
again.

When the tools answer, this skill has done its work. From here on follow the `casefile`
skill: it is the order of the steps for working a task. If you had a task to do before the
connection failed, return to it now.
