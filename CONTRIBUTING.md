# Contributing to Casefile

Thanks for looking. Casefile is a small project with a strong opinion about what it is —
a ledger your agents keep for each other, not an orchestrator — so the most useful thing
you can do before writing code is to open an issue and say what you are after.

## Sign your work

Casefile uses the [Developer Certificate of Origin](.github/DCO): a short statement that
you wrote the code, or otherwise have the right to submit it. You certify it by signing
each commit:

```bash
git commit -s -m "fix(tasks): ..."
```

That adds one line to the commit message:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and address must be your own and must match the commit author. Every commit in a
pull request needs one; merge commits do not. You can check a branch the way CI does:

```bash
scripts/check-dco.sh
```

If you forgot, `git rebase --signoff main` signs the whole branch and
`git commit --amend -s --no-edit` fixes the last commit.

## Your contribution is MIT

Casefile is MIT-licensed (see [LICENSE](LICENSE)), and contributions come in under the
same licence — nothing broader, nothing narrower. You keep the copyright to what you
wrote; the sign-off is a statement about provenance, not a transfer of rights.

## Before you open a pull request

Everything runs in Docker — installing Python on the host is not supported:

```bash
docker compose run --rm lint     # ruff
docker compose run --rm test     # pytest
```

For the web board, from `ui/`:

```bash
pnpm check                       # format, lint, types, FSD boundaries, tests
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org):
`feat(case): ...`, `fix(tasks): ...`, `docs(mcp): ...`. One commit is one meaningful
change — a task usually becomes several commits rather than one.

The full setup guide is [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## A note on language

Everything facing the outside world — this file, the README, the tool descriptions an
agent reads, error messages — is in English. The internal documents are in Russian: the
concept (`docs/CONCEPT.md`), the conventions (`docs/CONVENTIONS.md`) and the notes under
`docs/notes/`. They are the reasoning behind the design, written for the people building
it, and translating them is not planned. If something in there blocks you, ask in an
issue and it will be answered in English.

## Reporting a problem

Open an issue with what you did, what happened, and what you expected instead. Include
the output of `docker compose ps` and the relevant logs if the contour is involved — and
please redact your tokens: they grant full access to your installation.
