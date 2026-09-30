#!/bin/sh
# Casefile installer for macOS and Linux:
#
#   curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | sh
#
# Кладёт `docker-compose.prod.yml` в каталог установки (`~/casefile`), поднимает контур
# и печатает, куда открыть интерфейс и чем подключить агента. Повторный запуск —
# это обновление: свежий compose-файл, свежие образы, данные остаются в томах.
#
# Нужен только Docker с Compose v2. Всё остальное — образы из ghcr.io, которые конвейер
# публикует на каждый выпуск с git-тегом (канал `stable`). Compose-файл берётся из образа
# того же выпуска, а не с main: файл и образы установки всегда одного выпуска. Секретов
# скрипт не спрашивает: ключ интерфейса и токен агента выпускает сама установка
# (`docker-compose.prod.yml`).
#
# Вывод для человека — по-английски, как и вся страница проекта на GitHub.
#
# Переменные (все необязательны):
#   CASEFILE_DIR       каталог установки, по умолчанию ~/casefile
#   CASEFILE_REGISTRY  реестр образов, по умолчанию ghcr.io/azimov777; годится и свой
#                      реестр — так установщик проверяют до публикации
#   CASEFILE_VERSION   выпуск: канал `stable` (по умолчанию) или номер вида 0.2.0
# Обе последние записываются в `.env` новой установки; без них действует `.env`
# существующей установки, а без него — умолчания compose-файла.
#   CASEFILE_SKILL     0 — не ставить скил агентам этой машины (по умолчанию 1, TRK-408)
#   CASEFILE_SKILL_ONLY  1 — только скил: без Docker, без каталога установки и без токена;
#                      для машины агента, которая подключается к Casefile на сервере:
#                      curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh
#   CASEFILE_SKILL_SOURCE  откуда брать маркетплейс скила, по умолчанию azimov777/casefile;
#                      так шаг проверяют до публикации, как CASEFILE_REGISTRY для образов
#
# Всё тело — в `main`, который зовётся последней строкой. Запущенный через `| sh`
# скрипт читается из трубы по мере исполнения, и любая команда, читающая stdin, съела бы
# его остаток: `docker compose run` так и делал, и установка молча кончалась на середине
# (TRK-58). С функцией оболочка дочитывает файл целиком прежде, чем выполнить хоть
# строку, — а заодно оборванная загрузка не исполняет половину скрипта. Docker-команды
# вдобавок читают `/dev/null`.
set -eu

DIR=${CASEFILE_DIR:-"$HOME/casefile"}
COMPOSE=docker-compose.prod.yml
SKILL=${CASEFILE_SKILL:-1}
SKILL_ONLY=${CASEFILE_SKILL_ONLY:-0}
SKILL_SOURCE=${CASEFILE_SKILL_SOURCE:-azimov777/casefile}

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() {
  printf 'casefile: %s\n' "$*" >&2
  exit 1
}

# Значение переменной из `.env` установки или умолчание: порты в итоговом сообщении
# должны быть теми, на которых контур действительно поднялся.
setting() {
  value=$(sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1)
  printf '%s' "${value:-$2}"
}

# Обновлятор установки на время установщика стоит: иначе его проверка, пришедшаяся на
# `pull` и `up` установщика, звала бы свой `up`, и два compose останавливали бы контейнеры
# друг друга (TRK-131). Идущую проверку он доводит до конца. Её видно по файлу
# `/tmp/checking` в контейнере, а у обновлятора прежних выпусков — по процессу `docker` в
# нём, как видит `updater-renew`. Запускает его снова `up` установщика, а если установщик
# упал раньше — выход скрипта: остановленный руками контейнер Docker сам уже не поднимет.
updater_checking() {
  docker exec "$updater" test -e /tmp/checking </dev/null >/dev/null 2>&1 ||
    docker top "$updater" -o pid,comm </dev/null 2>/dev/null |
    awk 'NR > 1 && $2 ~ /^docker/ { found = 1 } END { exit !found }'
}

hold_updater() {
  updater=$(docker compose ps -q updater </dev/null 2>/dev/null || true)
  [ -n "$updater" ] || return 0
  i=0
  while updater_checking && [ "$i" -lt 120 ]; do
    [ "$i" -gt 0 ] || bold "Waiting for the updater to finish its check..."
    sleep 5
    i=$((i + 1))
  done
  docker stop "$updater" </dev/null >/dev/null
  trap 'docker start "$updater" </dev/null >/dev/null 2>&1 || true' EXIT
}

# --- Скил во все найденные харнессы (TRK-408, решения TRK-401#11, #18) -------------------
# Напечатанную команду агент может не выполнить, поэтому скил ставит сам установщик: для
# каждого найденного `claude`, `codex`, `hermes` — маркетплейс и плагин, для прочих
# агентов — `npx skills`. Всё идемпотентно: уже стоящее обновляется, а не падает, и
# повторный запуск ставит скил в харнесс, появившийся позже. Ставится только скил: токен
# в файлы харнессов не пишется, подключение MCP остаётся напечатанной командой. Самих
# харнессов установщик не ставит. Команды читают `/dev/null` (TRK-58); их вывод — в
# журнале шага, а видна строка итога с командой для ручного повтора. Ошибка скила
# установку сервиса не валит.

skill_line() { printf '  %-13s %s\n' "$1" "$2"; }

# Одна команда харнесса: тихо, stdin из /dev/null, вывод — в журнал шага.
skill_run() { "$@" </dev/null >>"$skill_log" 2>&1; }

# Итог неудачи: строка, команда повтора и хвост журнала, чтобы причину не искать.
skill_failed() {
  skill_line "$1" "failed - repeat by hand:"
  printf '                %s\n' "$2"
  tail -n 3 "$skill_log" | sed 's/^/                > /'
}

# `"autoUpdate": true` рядом с `source` в extraKnownMarketplaces.casefile: у сторонних
# маркетплейсов Claude Code обновляет плагин сам только с ним, а флага в CLI нет (TRK-406).
# Правится JSON тем, что есть на машине; файл переписывается, только если ключа не было.
claude_auto_update() {
  settings="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
  [ -f "$settings" ] || return 1
  patched="$skill_tmp/settings.json"
  if command -v jq >/dev/null 2>&1; then
    jq '.extraKnownMarketplaces.casefile.autoUpdate = true' "$settings" >"$patched" || return 1
  elif command -v node >/dev/null 2>&1; then
    node -e 'const fs=require("fs");const o=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));
      o.extraKnownMarketplaces.casefile.autoUpdate=true;
      process.stdout.write(JSON.stringify(o,null,2)+"\n")' "$settings" >"$patched" || return 1
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys
o=json.load(open(sys.argv[1],encoding="utf-8"))
o["extraKnownMarketplaces"]["casefile"]["autoUpdate"]=True
sys.stdout.write(json.dumps(o,indent=2,ensure_ascii=False)+"\n")' "$settings" >"$patched" || return 1
  else
    return 1
  fi
  cmp -s "$patched" "$settings" || cat "$patched" >"$settings"
}

skill_claude() {
  src="$SKILL_SOURCE#stable"
  retry="claude plugin marketplace add $src --sparse .claude-plugin skills && claude plugin install casefile@casefile --scope user"
  if skill_run claude plugin marketplace add "$src" --sparse .claude-plugin skills &&
    skill_run claude plugin marketplace update casefile &&
    skill_run claude plugin install casefile@casefile --scope user &&
    skill_run claude plugin update casefile@casefile; then
    found=$(claude plugin list </dev/null 2>/dev/null |
      awk '/casefile@casefile/ {f=1; next} f && /Version:/ {v=$2} f && /Status:/ {print v, ($0 ~ /enabled/ ? "enabled" : "off"); exit}')
    case "$found" in
      *" enabled")
        if claude_auto_update; then
          skill_line "Claude Code" "installed ${found% *} (updates itself)"
        else
          skill_line "Claude Code" "installed ${found% *} (automatic updates not switched on: add \"autoUpdate\": true inside extraKnownMarketplaces.casefile in settings.json)"
        fi ;;
      *) skill_failed "Claude Code" "$retry" ;;
    esac
  else
    skill_failed "Claude Code" "$retry"
  fi
}

skill_codex() {
  retry="codex plugin marketplace add $SKILL_SOURCE --ref stable --sparse .claude-plugin --sparse skills && codex plugin add casefile@casefile"
  if skill_run codex plugin marketplace add "$SKILL_SOURCE" --ref stable --sparse .claude-plugin --sparse skills &&
    skill_run codex plugin marketplace upgrade casefile &&
    skill_run codex plugin add casefile@casefile; then
    found=$(codex plugin list </dev/null 2>/dev/null | awk '$1 == "casefile@casefile" && /installed/ {
      for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+[.][0-9]+/) { print $i; exit } }')
    if [ -n "$found" ]; then
      skill_line "Codex" "installed $found"
    else
      skill_failed "Codex" "$retry"
    fi
  else
    skill_failed "Codex" "$retry"
  fi
}

skill_hermes() {
  retry="hermes skills install $SKILL_SOURCE/skills/casefile"
  if skill_run hermes skills install "$SKILL_SOURCE/skills/casefile" &&
    { find "${HERMES_HOME:-$HOME/.hermes}" -path '*casefile/SKILL.md' 2>/dev/null | grep -q . ||
      hermes skills list </dev/null 2>/dev/null | grep -qi casefile; }; then
    skill_line "Hermes" "installed"
  else
    skill_failed "Hermes" "$retry"
  fi
}

# Прочие агенты (Cursor, Cline, ...) читают общий `~/.agents/skills`: `--agent cursor` кладёт
# скил именно туда и не трогает каталог Claude Code, где он уже стоит плагином.
skill_others() {
  retry="npx skills add $SKILL_SOURCE#stable -g -y --agent cursor"
  if skill_run npx -y skills add "$SKILL_SOURCE#stable" -g -y --agent cursor &&
    [ -f "$HOME/.agents/skills/casefile/SKILL.md" ]; then
    skill_line "Other agents" "installed (~/.agents/skills/casefile)"
  else
    skill_failed "Other agents" "$retry"
  fi
}

install_skills() {
  skill_tmp=$(mktemp -d)
  skill_log="$skill_tmp/log"
  : >"$skill_log"
  bold "Installing the Casefile skill for the agents on this machine:"
  for harness in claude codex hermes; do
    if command -v "$harness" >/dev/null 2>&1; then
      "skill_$harness"
    else
      case "$harness" in claude) name="Claude Code" ;; codex) name=Codex ;; *) name=Hermes ;; esac
      skill_line "$name" "not found (run this installer again after installing it)"
    fi
  done
  if command -v npx >/dev/null 2>&1; then
    skill_others
  else
    skill_line "Other agents" "npx not found (with Node.js: npx skills add $SKILL_SOURCE#stable)"
  fi
  rm -rf "$skill_tmp"
  echo "  A running session picks up the skill after a restart (in Claude Code: /reload-plugins)."
  echo
}

main() {
  if [ "$SKILL_ONLY" = 1 ]; then
    # Машина агента, которая только подключается к Casefile на сервере: ни Docker, ни
    # каталога установки, ни токена (TRK-401#18).
    install_skills || true
    echo "Now connect the agent to your Casefile over MCP: docs/agent-install.md,"
    echo "\"Joining an installation someone else runs\" (https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md)."
    return 0
  fi

  command -v docker >/dev/null 2>&1 ||
    fail "Docker is required: https://docs.docker.com/get-docker/"
  docker compose version </dev/null >/dev/null 2>&1 ||
    fail "Docker Compose v2 is required (the 'docker compose' command)."
  docker info </dev/null >/dev/null 2>&1 ||
    fail "Docker is not running. Start Docker Desktop (or the docker service) and run this again."

  # Docker Desktop может быть переключён в режим Windows-контейнеров: тогда образы
  # Linux не поднимутся, а человек увидит чужую ошибку пула вместо причины. `|| true`
  # не даёт `set -e` остановить скрипт, если старый Docker не понимает `--format`.
  os_type=$(docker info --format '{{.OSType}}' </dev/null 2>/dev/null || true)
  case "$os_type" in
    windows)
      fail "Docker Desktop is set to Windows containers, but Casefile needs Linux containers. Switch to Linux containers (right-click the Docker Desktop tray icon and choose \"Switch to Linux containers...\") and run this again." ;;
  esac

  mkdir -p "$DIR"
  cd "$DIR"

  bold "Installing Casefile into $DIR"

  # `.env` заводится один раз и дальше принадлежит человеку: повторный запуск его не
  # трогает. COMPOSE_FILE — чтобы в этом каталоге работал просто `docker compose logs`;
  # реестр и выпуск — только если их назвали установщику, иначе действуют умолчания файла.
  if [ ! -f .env ]; then
    {
      echo "COMPOSE_FILE=$COMPOSE"
      [ -z "${CASEFILE_REGISTRY:-}" ] || echo "CASEFILE_REGISTRY=$CASEFILE_REGISTRY"
      [ -z "${CASEFILE_VERSION:-}" ] || echo "CASEFILE_VERSION=$CASEFILE_VERSION"
    } >.env
  fi

  # Compose-файл лежит в образе выпуска (`docker/Dockerfile.prod`); тем же путём его берёт
  # служба updater. Выпусков раньше 0.2.0 в канале нет, и файла в них тоже нет.
  # Выбор тот же, что у compose: окружение, затем `.env`, затем умолчание файла.
  registry=${CASEFILE_REGISTRY:-$(setting CASEFILE_REGISTRY ghcr.io/azimov777)}
  image="$registry/casefile:${CASEFILE_VERSION:-$(setting CASEFILE_VERSION stable)}"
  docker pull --quiet "$image" </dev/null >/dev/null ||
    fail "could not download $image; check the network, or the release name in CASEFILE_VERSION"
  holder=$(docker create --pull never "$image" </dev/null) || fail "could not open $image"
  copied=0
  docker cp "$holder:/app/$COMPOSE" "$COMPOSE.download" </dev/null >/dev/null || copied=$?
  docker rm "$holder" </dev/null >/dev/null
  [ "$copied" -eq 0 ] ||
    fail "$image carries no $COMPOSE; releases before 0.2.0 cannot be installed this way"
  mv "$COMPOSE.download" "$COMPOSE"

  hold_updater

  bold "Starting Casefile (the first run downloads the images)..."
  docker compose pull --quiet </dev/null
  docker compose up -d --remove-orphans </dev/null
  trap - EXIT

  # Токен агента лежит в томе установки; читается разовым контейнером и попадает только
  # в этот терминал — ни в журнал, ни в файл на диске.
  token=$(docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token </dev/null)
  [ -n "$token" ] ||
    fail "the installation did not issue an agent token; see: docker compose logs agent-token"

  # Адрес MCP спрашивается у самой установки, а не собирается из порта: правило адреса
  # (`Settings.effective_mcp_public_url`, оно же отдаёт интерфейсу `GET
  # /api/v1/installation`) живёт одним местом, и установщик не держит вторую его копию,
  # которая разошлась бы при заданном `TRACKER_MCP_PUBLIC_URL` (TRK-71).
  mcp_url=$(docker compose run --rm --no-deps -T --entrypoint python api -c \
    "from app.core.config import get_settings; print(get_settings().effective_mcp_public_url)" \
    </dev/null)
  [ -n "$mcp_url" ] ||
    fail "the installation did not report its MCP address; see: docker compose logs api"

  # Тот же порядок, что у compose и уже у `registry`/`image` выше: окружение, затем
  # `.env`, затем умолчание. Раньше здесь стоял один `setting`, и заданный установщику
  # `CASEFILE_PORT` в окружении не менял напечатанный адрес, хотя двигал реальную публикацию
  # порта — установщик рапортовал про порт, на котором доска не поднималась (TRK-169).
  ui_port=${CASEFILE_PORT:-$(setting CASEFILE_PORT 8080)}

  echo
  bold "Casefile is running."
  echo
  echo "  Board:  http://localhost:$ui_port"
  echo "  MCP:    $mcp_url"
  echo
  if [ "$SKILL" != 0 ]; then
    install_skills || echo "casefile: the skill step failed; the installation itself is done."
  fi
  # Подключение и скил — по блоку на харнесс (TRK-406, решения TRK-398#7, #9, TRK-401#18).
  # Токен только печатается, в файлы харнессов установщик его не пишет. Имена маркетплейса,
  # плагина и ветки `stable` — из `.claude-plugin/marketplace.json` и `images.yml`; те же
  # команды дословно стоят в `docs/agent-install.md`, и `tests/test_installers.py` сверяет их.
  bold "Connect Claude Code:"
  echo "  claude mcp add --transport http --scope user casefile $mcp_url \\"
  echo "    --header \"Authorization: Bearer $token\""
  echo "  claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills"
  echo "  claude plugin install casefile@casefile --scope user"
  echo "  Then let Claude Code keep the skill current: in ~/.claude/settings.json add"
  echo "  \"autoUpdate\": true next to \"source\" inside extraKnownMarketplaces.casefile."
  echo
  bold "Connect Codex:"
  echo "  Add to ~/.codex/config.toml (works in the terminal and in the Codex app):"
  echo "    [mcp_servers.casefile]"
  echo "    url = \"$mcp_url\""
  echo "    http_headers = { Authorization = \"Bearer $token\" }"
  echo "  Terminal only, token kept out of the file: export CASEFILE_TOKEN=<token> and write"
  echo "  bearer_token_env_var = \"CASEFILE_TOKEN\" instead of the http_headers line."
  echo "  codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse skills"
  echo "  codex plugin add casefile@casefile"
  echo
  bold "Connect Hermes:"
  echo "  Add to ~/.hermes/config.yaml:"
  echo "    mcp_servers:"
  echo "      casefile:"
  echo "        url: \"$mcp_url\""
  echo "        headers:"
  echo "          Authorization: \"Bearer $token\""
  echo "  hermes skills install azimov777/casefile/skills/casefile"
  echo
  bold "Any other MCP client (Cursor, ...):"
  echo "  URL     $mcp_url"
  echo "  Header  Authorization: Bearer $token"
  echo "  npx skills add azimov777/casefile#stable"
  echo
  echo "The skill teaches an agent how to work in Casefile. A running session picks up a new"
  echo "plugin after a restart or /reload-plugins. Steps and updates: docs/agent-install.md"
  echo "(https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md)."
  echo

  # Дословный текст двух фраз (`app/domain/agent_phrases.py`, `AGENT_PHRASES`): это одна
  # из копий, и сверяет их сплошная проверка множеств, а не вычитка (`docs/CONVENTIONS.md`,
  # «Документация»; `tests/test_agent_phrases_everywhere.py`, TRK-367).
  # Адрес в последней строке — тот же порт, что и строка `Board:` выше, плюс `/start`:
  # там те же фразы стоят на языке человека, с копированием по кнопке.
  bold "Tell your agent what to do:"
  echo "  Have work to hand over? Say:"
  echo "    File tasks in Casefile for my work: a project for it if there is none yet, and tasks with all their sections and checks, each small enough for one agent to finish in one go, each naming its environment in \`context\` — where the work lives and how to check it is done. Don't start the work itself; if I haven't described it yet, ask me."
  echo "  Then, in a new agent session, say:"
  echo "    Carry out the tasks for this work from the Casefile tracker. Hand them to agents, one task per agent, to save your own context, and give them cheaper models where those cope."
  echo "  The same phrases with copy buttons, in your language: http://localhost:$ui_port/start"
  echo

  echo "Another machine whose agents will connect to this installation gets the skill with:"
  echo "  curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 sh"
  echo "  (Windows PowerShell: \$env:CASEFILE_SKILL_ONLY=1; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex)"
  echo

  echo "Updates arrive by themselves: Casefile checks for a new release every hour. Files and data: $DIR"
}

main "$@"
