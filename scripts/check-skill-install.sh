#!/usr/bin/env bash
#
# Живая проверка шага «скил» и плагина установщика (TRK-408, TRK-452) на своём стенде, без GitHub:
#
#   scripts/check-skill-install.sh [каталог-для-улик]
#
# Поднимает локальный git по http (`git http-backend` за крошечным CGI-сервером на
# python3: `dumb http` не годится — у него нет shallow) с двумя ветками, как у выпуска: `stable`
# — файлы плагина из рабочего дерева и файлы корня (`openapi.json` с примером `trk_`,
# `install.sh`), `plugin` — одни файлы плагина, как её собирает `build-plugin-branch.sh`
# (TRK-494); версия скила — стендовая. Установщик запускается только с временными
# `HOME`/`CLAUDE_CONFIG_DIR`/`CODEX_HOME`/`HERMES_HOME`, `CASEFILE_SKILL_SOURCE` на стенд и
# `CASEFILE_DIR` во временном каталоге. Настоящие `~/.claude`, `~/.codex`, `~/.agents` и
# установка `~/casefile` не читаются и не меняются; их отпечаток до и после — последняя
# проверка. Нужны `claude`, `codex`, `npx`, `git`, `python3` на хосте: набор бэкенда идёт
# в контейнере, а харнессов там нет.
#
# Фазы (первая неудача останавливает скрипт с кодом 1):
#   A. `CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://<не localhost>`: `claude plugin list` и
#      `codex plugin list` показывают casefile со стендовой версией, `claude mcp list` и
#      `codex mcp list` — casefile с этим адресом, у маркетплейса Claude Code
#      `autoUpdate: true`, `npx skills` положил SKILL.md в HOME стенда, заглушка `hermes`
#      получила команду; каталог установки не создан, `grep -r trk_` по каталогам харнессов
#      и HOME пуст — в них нет файлов корня репозитория (TRK-494).
#      A0: без `CASEFILE_URL` плагин ставится с адресом по умолчанию (TRK-480), вход не
#      ведётся, docker не зовётся, печатается, как задать адрес; скил Hermes и прочих ставится. A1: адрес `http://` не с localhost — отказ.
#   M. установка прежними строками (`#stable --sparse …`, TRK-494): `grep -r trk_` находит
#      файлы корня; прогон установщика переводит оба харнесса на ветку `plugin` — источник в
#      settings.json и config.toml, `autoUpdate` на месте, маркетплейсы и cache Codex без `trk_`;
#      вывод называет команду входа Claude Code на случай «Needs authentication» (TRK-502).
#   M2. плагин уже стоит с адресом `localhost`: прогон без `CASEFILE_URL` адрес оставляет, прогон
#      с другим адресом печатает «the address changed from …» с командой входа (TRK-502).
#   B. второй прогон подряд (идемпотентность), затем ветки `stable` и `plugin` сдвинуты на
#      коммит с новой версией и прогон ещё раз: версия в обоих харнессах новая; у окружения M
#      cache Claude Code новой версии тоже без `trk_`, прежняя помечена `.orphaned_at`.
#   C. `CASEFILE_SKILL_ONLY=1` при PATH без `docker` ставит скил и не создаёт каталог
#      установки; при PATH без `claude`/`codex`/`hermes`/`npx` не падает и печатает not
#      found по каждому и ничего не ставит.
#   D. полная установка с подставным `docker`: шаг скила идёт после поднятия контура и
#      печатает строку с `CASEFILE_SKILL_ONLY=1`; с `CASEFILE_SKILL=0` шага нет вовсе.
#   F. прежние ручные записи: `casefile` с токеном и адресом этой установки убрана из
#      Claude Code и Codex, запись `tracker` с чужим адресом осталась, `grep -r trk_` по
#      конфигам пуст, в блоках Claude Code и Codex вывода токена нет; без терминала вход
#      не запускается, печатаются команды. F2: полная установка с адресом не по умолчанию
#      кладёт Codex запись без токена с этим адресом.
#   E. отпечаток `~/.claude/settings.json`, `~/.codex/config.toml` и `ls -la ~/.agents`
#      совпадает с отпечатком до всех фаз.
#
# Переменные: CHECK_PORT — порт стенда (по умолчанию 18409); CHECK_LIVE_URL — адрес MCP
# контура стенда для фазы F (по умолчанию http://localhost:18552/mcp).
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${CHECK_PORT:-18409}
EVIDENCE=$(mkdir -p "${1:-/tmp/check-skill-install-evidence}" && cd "${1:-/tmp/check-skill-install-evidence}" && pwd)
WORK=$(mktemp -d)
REAL_HOME=$HOME
V1=9.9.1
V2=9.9.2
URL=http://127.0.0.1:$PORT/casefile.git
SERVER_URL=https://casefile.stand.test/mcp
# Адрес «установки» для фазы F: здесь `claude mcp list` соединяется по-настоящему, поэтому
# это стенд из контура задачи, а не установка владельца на 8100.
LIVE_URL=${CHECK_LIVE_URL:-http://localhost:18552/mcp}
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

# --- Стенд: репозиторий с ветками stable и plugin и git по http ------------------------
mkdir -p "$WORK/srv" "$WORK/repo"
git init -q -b stable "$WORK/repo"
publish_version() { # версия → коммит выпуска в `stable` и в `plugin` и в bare-репозитории
  cp -R "$ROOT/.claude-plugin" "$ROOT/.codex-plugin" "$ROOT/skills" "$WORK/repo/"
  cp "$ROOT/LICENSE" "$ROOT/README.md" "$ROOT/openapi.json" "$ROOT/install.sh" "$WORK/repo/"
  sed -i.bak "s/\"version\": \"[^\"]*\"/\"version\": \"$1\"/" "$WORK/repo/.claude-plugin/"*.json "$WORK/repo/.codex-plugin/plugin.json"
  rm -f "$WORK/repo/.claude-plugin/"*.bak "$WORK/repo/.codex-plugin/"*.bak
  git -C "$WORK/repo" add -A
  git -C "$WORK/repo" -c user.email=check@example.com -c user.name=check commit -q -m "stand $1"
  # Ветка `plugin` — тот же отбор, что у `scripts/build-plugin-branch.sh` (его сверка версии
  # с `pyproject.toml` стендовой версии не пропустит): файлы плагина без карты `skills/`.
  rm -rf "$WORK/plugin-tree" "$WORK/plugin-index"
  mkdir -p "$WORK/plugin-tree"
  (cd "$WORK/repo" && cp -R .claude-plugin .codex-plugin skills LICENSE README.md "$WORK/plugin-tree/")
  rm -f "$WORK/plugin-tree/skills/AGENTS.md"
  GIT_INDEX_FILE="$WORK/plugin-index" git -C "$WORK/repo" --work-tree="$WORK/plugin-tree" add -A -f .
  tree=$(GIT_INDEX_FILE="$WORK/plugin-index" git -C "$WORK/repo" write-tree)
  parent=$(git -C "$WORK/repo" rev-parse --verify --quiet refs/heads/plugin || true)
  commit=$(git -C "$WORK/repo" -c user.email=check@example.com -c user.name=check \
    commit-tree "$tree" ${parent:+-p "$parent"} -m "stand $1: plugin files")
  git -C "$WORK/repo" update-ref refs/heads/plugin "$commit"
  if [ -d "$WORK/srv/casefile.git" ]; then
    git -C "$WORK/repo" push -q "$WORK/srv/casefile.git" stable:next plugin:plugin
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

no_secrets() { # $1 — окружение: ни одного токена `trk_` в конфигах харнессов и в HOME
  if grep -rq 'trk_' "$WORK/$1/claude" "$WORK/$1/codex" "$WORK/$1/home" 2>/dev/null; then
    grep -rl 'trk_' "$WORK/$1/claude" "$WORK/$1/codex" "$WORK/$1/home" 2>/dev/null | head
    fail "$1: a token (trk_) is written into a harness config"
  fi
  note "$1: grep -r trk_ over the Claude Code, Codex and HOME of the stand finds nothing"
}

assert_connection() { # $1 — окружение, $2 — адрес, который показывают `claude mcp list` и `codex mcp list`
  local e=$1 u=$2 claude codex
  claude=$(harness "$e" claude mcp list)
  echo "$claude" | grep -q "plugin:casefile:casefile: $u" || fail "$e: claude mcp list has no casefile at $u: $claude"
  codex=$(harness "$e" codex mcp list)
  echo "$codex" | grep -E "^casefile +$u" >/dev/null || fail "$e: codex mcp list has no casefile at $u: $codex"
  note "$e: claude mcp list -> $(echo "$claude" | grep 'plugin:casefile:casefile' | cut -c1-90)"
  note "$e: codex mcp list -> $(echo "$codex" | grep '^casefile' | tr -s ' ' | cut -d' ' -f1-2)"
}

full_path="$WORK/stubs:$PATH"

say "A. CASEFILE_SKILL_ONLY=1 on a clean machine"
new_env a
run_installer a a1.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "A: the installer exited non-zero: $(tail -5 "$EVIDENCE/a1.out")"
cat "$EVIDENCE/a1.out" | tee -a "$EVIDENCE/run.log"
assert_versions a "$V1"
[ -f "$WORK/a/home/.agents/skills/casefile/SKILL.md" ] || fail "A: npx skills left no SKILL.md in the stand HOME"
grep -q 'skills install' "$WORK/a/hermes/calls" || fail "A: the hermes stub was not called"
[ -f "$WORK/a/hermes/skills/casefile/SKILL.md" ] || fail "A: the hermes stub has no skill"
grep -q 'Hermes .*installed' "$EVIDENCE/a1.out" || fail "A: the output has no installed line for Hermes"
[ ! -e "$WORK/a/casefile-dir" ] || fail "A: the installation directory was created"
! grep -Eq 'Bearer|agent-token' "$EVIDENCE/a1.out" || fail "A: the output carries a token or connect command"
assert_connection a "$SERVER_URL"
no_secrets a
grep -q 'signed in\|needs a terminal' "$EVIDENCE/a1.out" || fail "A: the output says nothing about the sign-in"
note "A ok: plugin installed with $SERVER_URL, no installation directory, no token"

say "A0. CASEFILE_SKILL_ONLY=1 without CASEFILE_URL: the plugin with the default address, no sign-in, no docker"
new_env a0
mkdir -p "$WORK/a0/spy"
printf '#!/bin/sh\necho "$*" >>"%s"\nexit 1\n' "$WORK/a0/docker-calls" >"$WORK/a0/spy/docker"
chmod +x "$WORK/a0/spy/docker"
run_installer a0 a0.out "$WORK/a0/spy:$full_path" CASEFILE_SKILL_ONLY=1 || fail "A0: exited non-zero: $(tail -5 "$EVIDENCE/a0.out")"
cat "$EVIDENCE/a0.out" | tee -a "$EVIDENCE/run.log"
harness a0 claude plugin list | grep -q casefile@casefile || fail "A0: the Claude Code plugin is not listed"
harness a0 codex plugin list | grep -E '^casefile@casefile +installed' >/dev/null || fail "A0: the Codex plugin is not listed"
assert_connection a0 "http://127.0.0.1:8100/mcp"
grep -q 'CASEFILE_URL=https://' "$EVIDENCE/a0.out" || fail "A0: the output does not say how to set the address"
! grep -q 'Signing the agents in' "$EVIDENCE/a0.out" || fail "A0: a sign-in was started without an address"
[ ! -e "$WORK/a0/docker-calls" ] || fail "A0: docker was called: $(cat "$WORK/a0/docker-calls")"
[ -f "$WORK/a0/hermes/skills/casefile/SKILL.md" ] || fail "A0: the Hermes skill was not installed"
[ ! -e "$WORK/a0/casefile-dir" ] || fail "A0: the installation directory was created"
no_secrets a0
note "A0 ok"

say "A1. an http:// address that is not localhost is refused"
new_env a1
if run_installer a1 a1.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL=http://203.0.113.7:8100/mcp; then fail "A1: http://203.0.113.7 was accepted"; fi
grep -q 'https' "$EVIDENCE/a1.out" || fail "A1: the refusal does not name https"
is_empty "$WORK/a1/claude" "$WORK/a1/codex" || fail "A1: something was installed"
note "A1 ok"

say "M. an installation from stable with --sparse (before TRK-494) moves to the plugin branch"
new_env m
harness m claude plugin marketplace add "$URL#stable" --sparse .claude-plugin skills >/dev/null
harness m claude plugin install casefile@casefile --scope user --config "casefile_url=$SERVER_URL" >/dev/null
harness m codex plugin marketplace add "$URL" --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills >/dev/null
harness m codex plugin add casefile@casefile >/dev/null
grep -rq trk_ "$WORK/m/claude" "$WORK/m/codex" ||
  fail "M: the install from stable carries no trk_: the stand does not reproduce the old state"
note "M: before: $(grep -rl trk_ "$WORK/m/claude" "$WORK/m/codex" | sed "s#$WORK/##" | tr '\n' ' ')"
run_installer m m1.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "M: exited non-zero: $(tail -5 "$EVIDENCE/m1.out")"
cat "$EVIDENCE/m1.out" | tee -a "$EVIDENCE/run.log"
assert_versions m "$V1"
assert_connection m "$SERVER_URL"
grep -Eq '"ref": *"plugin"' "$WORK/m/claude/settings.json" && ! grep -q sparsePaths "$WORK/m/claude/settings.json" ||
  fail "M: the Claude Code marketplace is not on the plugin branch: $(cat "$WORK/m/claude/settings.json")"
grep -A4 '^\[marketplaces.casefile\]' "$WORK/m/codex/config.toml" | grep -q 'ref = "plugin"' ||
  fail "M: the Codex marketplace is not on the plugin branch"
if grep -rq trk_ "$WORK/m/claude/plugins/marketplaces" "$WORK/m/codex"; then
  grep -rl trk_ "$WORK/m/claude/plugins/marketplaces" "$WORK/m/codex" | head
  fail "M: the marketplaces or the Codex cache still carry repository files"
fi
grep -q 'moved to the plugin branch; the sign-in stays with the address.*claude mcp login plugin:casefile:casefile' "$EVIDENCE/m1.out" ||
  fail "M: the output does not name the sign-in command for Claude Code after the move"
note "M ok: both harnesses on the plugin branch; left until the next version: $(grep -rl trk_ "$WORK/m/claude" | sed "s#$WORK/##" | tr '\n' ' ')"

say "M2. the address the plugin has is kept without CASEFILE_URL; a new address names the sign-in again (TRK-502)"
# Вход Claude Code лежит под ключом из имени сервера и адреса: `localhost` и `127.0.0.1` —
# разные ключи. Адрес стенда — порт, на котором никого нет: `mcp list` к нему не дозвонится.
OLD_URL=http://localhost:18399/mcp
new_env m2
harness m2 claude plugin marketplace add "$URL#stable" --sparse .claude-plugin skills >/dev/null
harness m2 claude plugin install casefile@casefile --scope user --config "casefile_url=$OLD_URL" >/dev/null
run_installer m2 m2a.out "$full_path" CASEFILE_SKILL_ONLY=1 || fail "M2: exited non-zero: $(tail -5 "$EVIDENCE/m2a.out")"
cat "$EVIDENCE/m2a.out" | tee -a "$EVIDENCE/run.log"
harness m2 claude mcp list | grep -q "plugin:casefile:casefile: $OLD_URL" ||
  fail "M2: without CASEFILE_URL the Claude Code address did not stay $OLD_URL: $(harness m2 claude mcp list)"
grep -q "kept the address it had" "$EVIDENCE/m2a.out" || fail "M2: the output does not say the address was kept"
run_installer m2 m2b.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "M2: the run with an address exited non-zero"
cat "$EVIDENCE/m2b.out" | tee -a "$EVIDENCE/run.log"
harness m2 claude mcp list | grep -q "plugin:casefile:casefile: $SERVER_URL" || fail "M2: the new address is not set"
grep -q "the address changed from $OLD_URL: .*claude mcp login plugin:casefile:casefile" "$EVIDENCE/m2b.out" ||
  fail "M2: the output does not name the sign-in again after the address changed"
note "M2 ok: the address stays without CASEFILE_URL; a changed address prints the sign-in command"

say "B. second run in a row, then shifted stable and plugin branches with a new version"
run_installer a a2.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "B: the second run exited non-zero: $(tail -5 "$EVIDENCE/a2.out")"
assert_versions a "$V1"
publish_version "$V2"
[ "$(git -C "$WORK/srv/casefile.git" rev-parse stable)" = "$(git -C "$WORK/repo" rev-parse HEAD)" ] &&
  [ "$(git -C "$WORK/srv/casefile.git" rev-parse plugin)" = "$(git -C "$WORK/repo" rev-parse plugin)" ] ||
  fail "B: the stand branches stable and plugin did not move"
run_installer a a3.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "B: the run after the shift exited non-zero: $(tail -5 "$EVIDENCE/a3.out")"
cat "$EVIDENCE/a3.out" | tee -a "$EVIDENCE/run.log"
assert_versions a "$V2"
run_installer m m2.out "$full_path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "B: the M run after the shift exited non-zero"
assert_versions m "$V2"
cache=$WORK/m/claude/plugins/cache/casefile/casefile
if grep -rq trk_ "$cache/$V2" "$WORK/m/claude/plugins/marketplaces" "$WORK/m/codex"; then
  fail "B: the $V2 plugin of the migrated install carries repository files"
fi
[ ! -d "$cache/$V1" ] || [ -f "$cache/$V1/.orphaned_at" ] || fail "B: the $V1 cache from stable is not marked for removal"
note "B: the migrated install at $V2 is clean; the $V1 cache from stable: $( [ -d "$cache/$V1" ] && echo 'marked .orphaned_at, Claude Code removes it' || echo removed)"
note "B ok: idempotent, and both harnesses moved to $V2"

say "C. PATH without docker; PATH without claude/codex/hermes/npx; CASEFILE_SKILL=0"
new_env c1
lean_path "$WORK/c1/path" docker claude codex hermes npx node
for t in claude codex npx node git; do link "$WORK/c1/path" "$t"; done
run_installer c1 c1.out "$WORK/c1/path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "C1: exited non-zero: $(tail -5 "$EVIDENCE/c1.out")"
PATH="$WORK/c1/path" command -v docker >/dev/null 2>&1 && fail "C1: docker is still on the PATH"
assert_versions c1 "$V2"
[ ! -e "$WORK/c1/casefile-dir" ] || fail "C1: the installation directory was created"
note "C1 ok: no docker on the PATH, the skill is installed, CASEFILE_DIR does not exist"

new_env c2
lean_path "$WORK/c2/path" docker claude codex hermes npx node
run_installer c2 c2.out "$WORK/c2/path" CASEFILE_SKILL_ONLY=1 CASEFILE_URL="$SERVER_URL" || fail "C2: exited non-zero: $(tail -5 "$EVIDENCE/c2.out")"
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
  "compose run "*agent-token*) echo trk_standfaketoken ;;
  "compose run "*) echo "${MCP_URL:-http://localhost:8100/mcp}" ;;
esac
SH
chmod +x "$WORK/d/path/docker"
run_installer d d1.out "$WORK/d/path" SCENE="$WORK/d/scene" || fail "D: the full install exited non-zero: $(tail -5 "$EVIDENCE/d1.out")"
grep -q 'Installing the Casefile skill' "$EVIDENCE/d1.out" || fail "D: the full install has no skill step"
grep -q 'CASEFILE_SKILL_ONLY=1 CASEFILE_URL=' "$EVIDENCE/d1.out" || fail "D: no CASEFILE_SKILL_ONLY line for other machines"
[ "$(grep -n 'Casefile is running' "$EVIDENCE/d1.out" | cut -d: -f1)" -lt "$(grep -n 'Installing the Casefile skill' "$EVIDENCE/d1.out" | cut -d: -f1)" ] ||
  fail "D: the skill step is not after the contour is up"
assert_versions d "$V2"
new_env d0
run_installer d0 d0.out "$WORK/d/path" SCENE="$WORK/d/scene" CASEFILE_SKILL=0 || fail "D0: exited non-zero"
grep -q 'Casefile is running' "$EVIDENCE/d0.out" || fail "D0: the full install did not run"
! grep -q 'Installing the Casefile skill' "$EVIDENCE/d0.out" || fail "D0: CASEFILE_SKILL=0 did not skip the step"
is_empty "$WORK/d0/claude" "$WORK/d0/codex" || fail "D0: CASEFILE_SKILL=0 still touched the harness configs"
note "C3/D ok: the full install runs the step after the contour; CASEFILE_SKILL=0 skips it"

say "F. manual entries from before the plugin are removed, the others stay; no token in any config, no sign-in without a terminal"
new_env f
harness f claude mcp add --transport http --scope user casefile http://localhost:18552/mcp \
  --header "Authorization: Bearer trk_manualtoken" >/dev/null
harness f claude mcp add --transport http --scope user tracker https://other.example.test/mcp >/dev/null
cat >"$WORK/f/codex/config.toml" <<'TOML'
[mcp_servers.casefile]
url = "http://localhost:18552/mcp"
http_headers = { Authorization = "Bearer trk_manualtoken" }

[mcp_servers.tracker]
url = "https://other.example.test/mcp"
TOML
grep -rq trk_manualtoken "$WORK/f/claude" "$WORK/f/codex" || fail "F: the stand has no manual token to remove"
run_installer f f1.out "$WORK/d/path" SCENE="$WORK/d/scene" MCP_URL="$LIVE_URL" || fail "F: the full install exited non-zero: $(tail -5 "$EVIDENCE/f1.out")"
cat "$EVIDENCE/f1.out" | tee -a "$EVIDENCE/run.log"
grep -q 'Claude Code .*removed the manual MCP entry "casefile"' "$EVIDENCE/f1.out" || fail "F: Claude Code manual entry not reported removed"
grep -q 'Codex .*removed the manual MCP entry "casefile"' "$EVIDENCE/f1.out" || fail "F: Codex manual entry not reported removed"
grep -q 'Claude Code .*left the MCP entry "tracker"' "$EVIDENCE/f1.out" || fail "F: Claude Code foreign tracker entry not left"
grep -q 'Codex .*left the MCP entry "tracker"' "$EVIDENCE/f1.out" || fail "F: Codex foreign tracker entry not left"
claude=$(harness f claude mcp list)
echo "$claude" | grep -q '^casefile:' && fail "F: the manual Claude Code entry casefile is still there: $claude"
echo "$claude" | grep -q 'tracker: https://other.example.test/mcp' || fail "F: the foreign tracker entry of Claude Code is gone"
codex=$(harness f codex mcp list)
! grep -q 'http_headers' "$WORK/f/codex/config.toml" || fail "F: the manual Codex entry with its header is still in config.toml"
echo "$codex" | grep -q 'tracker  *https://other.example.test/mcp' || fail "F: the foreign tracker entry of Codex is gone"
assert_connection f "$LIVE_URL"
no_secrets f
grep -q 'needs a terminal' "$EVIDENCE/f1.out" || fail "F: without a terminal the installer did not print the sign-in commands"
grep -q 'claude mcp login plugin:casefile:casefile' "$EVIDENCE/f1.out" && grep -q 'codex mcp login casefile' "$EVIDENCE/f1.out" ||
  fail "F: the sign-in commands are not printed"
blocks=$(sed -n '/^Claude Code:/,/^Hermes/p' "$EVIDENCE/f1.out")
echo "$blocks" | grep -q 'trk_\|Bearer' && fail "F: the Claude Code or Codex block carries a token"
grep -q 'Hermes (OAuth, no token)' "$EVIDENCE/f1.out" && grep -q 'auth: oauth' "$EVIDENCE/f1.out" &&
  grep -q 'Bearer trk_standfaketoken' "$EVIDENCE/f1.out" ||
  fail "F: Hermes has no OAuth block or the key is not printed for the clients without OAuth"
run_installer f f2.out "$WORK/d/path" SCENE="$WORK/d/scene" MCP_URL="$LIVE_URL" || fail "F: the second full install exited non-zero"
assert_connection f "$LIVE_URL"
no_secrets f
note "F ok: manual entries removed, foreign kept, no token in configs, commands printed without a terminal, second run is clean"

say "F2. an installation at another address: Codex gets an entry without a token"
new_env f2
run_installer f2 f21.out "$WORK/d/path" SCENE="$WORK/d/scene" MCP_URL=https://casefile.stand.test/mcp || fail "F2: exited non-zero: $(tail -5 "$EVIDENCE/f21.out")"
assert_connection f2 https://casefile.stand.test/mcp
grep -A1 '^\[mcp_servers.casefile\]' "$WORK/f2/codex/config.toml" | grep -q 'url = "https://casefile.stand.test/mcp"' || fail "F2: config.toml has no casefile entry"
no_secrets f2
note "F2 ok"

say "E. the owner's settings are as they were"
fingerprint >"$EVIDENCE/fingerprint-after.txt"
diff "$EVIDENCE/fingerprint-before.txt" "$EVIDENCE/fingerprint-after.txt" ||
  fail "the real ~/.claude, ~/.codex or ~/.agents changed (diff above)"
note "E ok: settings.json, config.toml and ls -la ~/.agents are identical before and after"

say "ALL PHASES PASSED"
