#!/usr/bin/env bash
#
# Живая проверка шага «скил» установщика (TRK-408) на своём стенде, без GitHub:
#
#   scripts/check-skill-install.sh [каталог-для-улик]
#
# Поднимает локальный git по http (`git http-backend` за крошечным CGI-сервером на
# python3: `dumb http` не годится — у него нет shallow) с маркетплейсом из рабочего дерева
# на ветке `stable`, версия скила — стендовая. Установщик запускается только с временными
# `HOME`/`CLAUDE_CONFIG_DIR`/`CODEX_HOME`/`HERMES_HOME`, `CASEFILE_SKILL_SOURCE` на стенд и
# `CASEFILE_DIR` во временном каталоге. Настоящие `~/.claude`, `~/.codex`, `~/.agents` и
# установка `~/casefile` не читаются и не меняются; их отпечаток до и после — последняя
# проверка. Нужны `claude`, `codex`, `npx`, `git`, `python3` на хосте: набор бэкенда идёт
# в контейнере, а харнессов там нет.
#
# Фазы (первая неудача останавливает скрипт с кодом 1):
#   A. `CASEFILE_SKILL_ONLY=1`: `claude plugin list` и `codex plugin list` показывают
#      casefile со стендовой версией, у маркетплейса Claude Code `autoUpdate: true`,
#      `npx skills` положил SKILL.md в HOME стенда, заглушка `hermes` получила команду;
#      каталог установки не создан.
#   B. второй прогон подряд (идемпотентность), затем ветка `stable` сдвинута на коммит с
#      новой версией и прогон ещё раз: версия в обоих харнессах новая.
#   C. `CASEFILE_SKILL_ONLY=1` при PATH без `docker` ставит скил и не создаёт каталог
#      установки; при PATH без `claude`/`codex`/`hermes`/`npx` не падает и печатает not
#      found по каждому и ничего не ставит.
#   D. полная установка с подставным `docker`: шаг скила идёт после поднятия контура и
#      печатает строку с `CASEFILE_SKILL_ONLY=1`; с `CASEFILE_SKILL=0` шага нет вовсе.
#   E. отпечаток `~/.claude/settings.json`, `~/.codex/config.toml` и `ls -la ~/.agents`
#      совпадает с отпечатком до всех фаз.
#
# Переменные: CHECK_PORT — порт стенда (по умолчанию 18409).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${CHECK_PORT:-18409}
EVIDENCE=$(mkdir -p "${1:-/tmp/check-skill-install-evidence}" && cd "${1:-/tmp/check-skill-install-evidence}" && pwd)
WORK=$(mktemp -d)
REAL_HOME=$HOME
V1=9.9.1
V2=9.9.2
URL=http://127.0.0.1:$PORT/casefile.git
SERVER_PID=

say() { printf '\n=== %s\n' "$*" | tee -a "$EVIDENCE/run.log"; }
note() { printf '%s\n' "$*" | tee -a "$EVIDENCE/run.log"; }
fail() { note "FAIL: $*"; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "$1 is required on the host"; }

for tool in git python3 claude codex npx node; do need "$tool"; done
[ "${CLAUDE_CONFIG_DIR:-}" = "" ] || fail "unset CLAUDE_CONFIG_DIR: the check sets its own"

cleanup() {
  set +e
  [ -z "$SERVER_PID" ] || kill "$SERVER_PID" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- Отпечаток настоящих настроек владельца: читаются, не меняются ----------------------
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo absent; }
fingerprint() {
  for f in "$REAL_HOME/.claude/settings.json" "$REAL_HOME/.codex/config.toml"; do
    if [ -f "$f" ]; then echo "$f $(mtime "$f") $(shasum "$f" | cut -d' ' -f1)"; else echo "$f absent"; fi
  done
  # Без строки `..`: её mtime — это mtime домашней папки, а она меняется от чего угодно.
  echo "ls -la ~/.agents:"
  ls -la "$REAL_HOME/.agents" 2>&1 | grep -v ' \.\.$' | sed 's/^total .*//'
}
fingerprint >"$EVIDENCE/fingerprint-before.txt"

# --- Стенд: репозиторий с маркетплейсом на ветке stable и git по http -------------------
mkdir -p "$WORK/srv" "$WORK/repo"
git init -q -b stable "$WORK/repo"
publish_version() { # версия → коммит в ветке stable и в bare-репозитории
  cp -R "$ROOT/.claude-plugin" "$ROOT/skills" "$WORK/repo/"
  sed -i.bak "s/\"version\": \"[^\"]*\"/\"version\": \"$1\"/" "$WORK/repo/.claude-plugin/"*.json
  rm -f "$WORK/repo/.claude-plugin/"*.bak
  git -C "$WORK/repo" add -A
  git -C "$WORK/repo" -c user.email=check@example.com -c user.name=check commit -q -m "stand $1"
  if [ -d "$WORK/srv/casefile.git" ]; then
    git -C "$WORK/repo" push -q "$WORK/srv/casefile.git" stable:next
    git -C "$WORK/srv/casefile.git" update-ref refs/heads/stable refs/heads/next
  else
    git clone -q --bare "$WORK/repo" "$WORK/srv/casefile.git"
  fi
}
publish_version "$V1"

cat >"$WORK/cgi.py" <<PY
import http.server, os, subprocess
ROOT = "$WORK/srv"
class H(http.server.BaseHTTPRequestHandler):
    def do(self):
        path, _, qs = self.path.partition("?")
        env = dict(os.environ, GIT_PROJECT_ROOT=ROOT, GIT_HTTP_EXPORT_ALL="1", PATH_INFO=path,
                   QUERY_STRING=qs, REQUEST_METHOD=self.command, REMOTE_USER="x",
                   CONTENT_TYPE=self.headers.get("Content-Type", ""), REMOTE_ADDR="127.0.0.1")
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        if self.headers.get("Content-Encoding") == "gzip":
            env["HTTP_CONTENT_ENCODING"] = "gzip"
        env["CONTENT_LENGTH"] = str(len(body))
        p = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True)
        head, _, out = p.stdout.partition(b"\r\n\r\n")
        status, hs = 200, []
        for line in head.split(b"\r\n"):
            k, _, v = line.partition(b": ")
            if k.lower() == b"status":
                status = int(v.split()[0])
            else:
                hs.append((k.decode(), v.decode()))
        self.send_response(status)
        for k, v in hs:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    do_GET = do_POST = do
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(("127.0.0.1", $PORT), H).serve_forever()
PY
python3 "$WORK/cgi.py" >"$WORK/http.log" 2>&1 &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true
for _ in $(seq 20); do
  curl -fs "$URL/info/refs?service=git-upload-pack" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fs "$URL/info/refs?service=git-upload-pack" >/dev/null || fail "the stand git server did not start on port $PORT"

# --- Изолированное окружение и запуск установщика ---------------------------------------
new_env() { # $1 — имя окружения: свои HOME и конфиги на каждую фазу
  E=$WORK/$1
  mkdir -p "$E/home" "$E/claude" "$E/codex" "$E/hermes"
}

# Заглушка `hermes`: настоящего Hermes на машине нет, проверяется только то, что
# установщик зовёт его команду и потом видит результат.
mkdir -p "$WORK/stubs"
cat >"$WORK/stubs/hermes" <<'SH'
#!/bin/sh
echo "$*" >>"$HERMES_HOME/calls"
if [ "$1 $2" = "skills install" ]; then
  mkdir -p "$HERMES_HOME/skills/casefile"
  echo stub >"$HERMES_HOME/skills/casefile/SKILL.md"
fi
SH
chmod +x "$WORK/stubs/hermes"

# PATH без перечисленных программ: ссылки на всё из /usr/bin и /bin, кроме них.
lean_path() { # $1 — каталог, остальные — что исключить; добавлять нужное отдельно
  d=$1; shift
  mkdir -p "$d"
  for f in /usr/bin/* /bin/*; do
    name=${f##*/}
    skip=0
    for x in "$@"; do [ "$x" = "$name" ] && skip=1; done
    [ $skip = 1 ] || ln -sf "$f" "$d/$name" 2>/dev/null || true
  done
}
is_empty() { [ -z "$(find "$@" -mindepth 1 2>/dev/null | head -n 1)" ]; }
link() { ln -sf "$(command -v "$2")" "$1/$2"; }

run_installer() { # $1 — окружение, $2 — файл вывода, $3 — PATH, остальное — переменные
  local e=$1 out=$2 p=$3
  shift 3
  env -i PATH="$p" HOME="$WORK/$e/home" CLAUDE_CONFIG_DIR="$WORK/$e/claude" \
    CODEX_HOME="$WORK/$e/codex" HERMES_HOME="$WORK/$e/hermes" \
    CASEFILE_DIR="$WORK/$e/casefile-dir" CASEFILE_SKILL_SOURCE="$URL" "$@" \
    sh "$ROOT/install.sh" </dev/null >"$EVIDENCE/$out" 2>&1
}

harness() { # $1 — окружение: команда харнесса в его изолированных конфигах
  local e=$1
  shift
  env HOME="$WORK/$e/home" CLAUDE_CONFIG_DIR="$WORK/$e/claude" CODEX_HOME="$WORK/$e/codex" "$@" </dev/null
}

assert_versions() { # $1 — окружение, $2 — версия
  local e=$1 v=$2 claude codex
  claude=$(harness "$e" claude plugin list)
  echo "$claude" | grep -q "casefile@casefile" || fail "$e: claude plugin list has no casefile"
  echo "$claude" | grep -q "Version: $v" || fail "$e: claude plugin list is not at $v: $claude"
  echo "$claude" | grep -q "enabled" || fail "$e: the Claude Code plugin is not enabled"
  codex=$(harness "$e" codex plugin list)
  echo "$codex" | grep -E "^casefile@casefile +installed" | grep -q " $v " ||
    fail "$e: codex plugin list is not at $v: $codex"
  grep -Eq '"autoUpdate": *true' "$WORK/$e/claude/settings.json" ||
    fail "$e: extraKnownMarketplaces.casefile has no autoUpdate: true"
  note "$e: claude plugin list -> $(echo "$claude" | grep 'Version:' | xargs), codex plugin list -> $(echo "$codex" | grep '^casefile@casefile' | tr -s ' ' | cut -d' ' -f1-4)"
  note "$e: settings.json autoUpdate: $(grep -E '"autoUpdate"' "$WORK/$e/claude/settings.json" | xargs)"
}

full_path="$WORK/stubs:$PATH"

say "A. CASEFILE_SKILL_ONLY=1 on a clean machine"
new_env a
run_installer a a1.out "$full_path" CASEFILE_SKILL_ONLY=1 || fail "A: the installer exited non-zero: $(tail -5 "$EVIDENCE/a1.out")"
cat "$EVIDENCE/a1.out" | tee -a "$EVIDENCE/run.log"
assert_versions a "$V1"
[ -f "$WORK/a/home/.agents/skills/casefile/SKILL.md" ] || fail "A: npx skills left no SKILL.md in the stand HOME"
grep -q 'skills install' "$WORK/a/hermes/calls" || fail "A: the hermes stub was not called"
[ -f "$WORK/a/hermes/skills/casefile/SKILL.md" ] || fail "A: the hermes stub has no skill"
grep -q 'Hermes .*installed' "$EVIDENCE/a1.out" || fail "A: the output has no installed line for Hermes"
[ ! -e "$WORK/a/casefile-dir" ] || fail "A: the installation directory was created"
! grep -Eq 'Bearer|agent-token' "$EVIDENCE/a1.out" || fail "A: the output carries a token or connect command"
note "A ok: skill installed, no installation directory, no token"

say "B. second run in a row, then a shifted stable with a new version"
run_installer a a2.out "$full_path" CASEFILE_SKILL_ONLY=1 || fail "B: the second run exited non-zero: $(tail -5 "$EVIDENCE/a2.out")"
assert_versions a "$V1"
publish_version "$V2"
[ "$(git -C "$WORK/srv/casefile.git" rev-parse stable)" = "$(git -C "$WORK/repo" rev-parse HEAD)" ] ||
  fail "B: the stand branch stable did not move"
run_installer a a3.out "$full_path" CASEFILE_SKILL_ONLY=1 || fail "B: the run after the shift exited non-zero: $(tail -5 "$EVIDENCE/a3.out")"
cat "$EVIDENCE/a3.out" | tee -a "$EVIDENCE/run.log"
assert_versions a "$V2"
note "B ok: idempotent, and both harnesses moved to $V2"

say "C. PATH without docker; PATH without claude/codex/hermes/npx; CASEFILE_SKILL=0"
new_env c1
lean_path "$WORK/c1/path" docker claude codex hermes npx node
for t in claude codex npx node git; do link "$WORK/c1/path" "$t"; done
run_installer c1 c1.out "$WORK/c1/path" CASEFILE_SKILL_ONLY=1 || fail "C1: exited non-zero: $(tail -5 "$EVIDENCE/c1.out")"
PATH="$WORK/c1/path" command -v docker >/dev/null 2>&1 && fail "C1: docker is still on the PATH"
assert_versions c1 "$V2"
[ ! -e "$WORK/c1/casefile-dir" ] || fail "C1: the installation directory was created"
note "C1 ok: no docker on the PATH, the skill is installed, CASEFILE_DIR does not exist"

new_env c2
lean_path "$WORK/c2/path" docker claude codex hermes npx node
run_installer c2 c2.out "$WORK/c2/path" CASEFILE_SKILL_ONLY=1 || fail "C2: exited non-zero: $(tail -5 "$EVIDENCE/c2.out")"
cat "$EVIDENCE/c2.out" | tee -a "$EVIDENCE/run.log"
for h in "Claude Code" Codex Hermes; do
  grep -q "$h .*not found" "$EVIDENCE/c2.out" || fail "C2: no 'not found' line for $h"
done
grep -q 'Other agents .*npx not found' "$EVIDENCE/c2.out" || fail "C2: no 'npx not found' line"
is_empty "$WORK/c2/claude" "$WORK/c2/codex" "$WORK/c2/hermes" ||
  fail "C2: something was installed without a harness"
[ ! -e "$WORK/c2/home/.agents" ] || fail "C2: ~/.agents was created without npx"
note "C2 ok: nothing installed, every harness reported as not found"

# D. Полная установка с подставным docker: тот же сценарий, что у `tests/test_installers.py`.
new_env d
mkdir -p "$WORK/d/scene"
echo "services: {}" >"$WORK/d/scene/compose"
lean_path "$WORK/d/path" docker claude codex hermes npx node
for t in claude codex npx node git; do link "$WORK/d/path" "$t"; done
cat >"$WORK/d/path/docker" <<'SH'
#!/bin/sh
case "$*" in
  "info --format"*) echo linux ;;
  "create "*) echo holder ;;
  "cp "*) cp "$SCENE/compose" "$3" ;;
  "compose run "*agent-token*) echo agent-token-secret ;;
  "compose run "*) echo http://localhost:8100/mcp ;;
esac
SH
chmod +x "$WORK/d/path/docker"
run_installer d d1.out "$WORK/d/path" SCENE="$WORK/d/scene" || fail "D: the full install exited non-zero: $(tail -5 "$EVIDENCE/d1.out")"
grep -q 'Installing the Casefile skill' "$EVIDENCE/d1.out" || fail "D: the full install has no skill step"
grep -q 'CASEFILE_SKILL_ONLY=1 sh' "$EVIDENCE/d1.out" || fail "D: no CASEFILE_SKILL_ONLY line for other machines"
[ "$(grep -n 'Casefile is running' "$EVIDENCE/d1.out" | cut -d: -f1)" -lt "$(grep -n 'Installing the Casefile skill' "$EVIDENCE/d1.out" | cut -d: -f1)" ] ||
  fail "D: the skill step is not after the contour is up"
assert_versions d "$V2"
new_env d0
run_installer d0 d0.out "$WORK/d/path" SCENE="$WORK/d/scene" CASEFILE_SKILL=0 || fail "D0: exited non-zero"
grep -q 'Casefile is running' "$EVIDENCE/d0.out" || fail "D0: the full install did not run"
! grep -q 'Installing the Casefile skill' "$EVIDENCE/d0.out" || fail "D0: CASEFILE_SKILL=0 did not skip the step"
is_empty "$WORK/d0/claude" "$WORK/d0/codex" || fail "D0: CASEFILE_SKILL=0 still touched the harness configs"
note "C3/D ok: the full install runs the step after the contour; CASEFILE_SKILL=0 skips it"

say "E. the owner's settings are as they were"
fingerprint >"$EVIDENCE/fingerprint-after.txt"
diff "$EVIDENCE/fingerprint-before.txt" "$EVIDENCE/fingerprint-after.txt" ||
  fail "the real ~/.claude, ~/.codex or ~/.agents changed (diff above)"
note "E ok: settings.json, config.toml and ls -la ~/.agents are identical before and after"

say "ALL PHASES PASSED"
