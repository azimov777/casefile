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
# скрипт не спрашивает: ключ интерфейса и ключ агента выпускает сама установка
# (`docker-compose.prod.yml`). Claude Code и Codex подключает плагин `casefile` с входом
# OAuth (TRK-452): токен в их файлы не пишется, прежние ручные записи `casefile`/`tracker`
# с адресом этой установки убираются, а ключ агента печатается только харнессам без OAuth.
# Чату Claude Desktop он скачивает расширение `casefile.mcpb` выпуска и открывает его — ставит
# его сам Desktop, по щелчку человека (TRK-514).
#
# Вывод для человека — по-английски, как и вся страница проекта на GitHub.
#
# Переменные (все необязательны):
#   CASEFILE_DIR       каталог установки, по умолчанию ~/casefile
#   CASEFILE_REGISTRY  реестр образов, по умолчанию ghcr.io/azimov777; годится и свой
#                      реестр — так установщик проверяют до публикации
#   CASEFILE_VERSION   выпуск: канал `stable` (по умолчанию) или номер вида 0.2.0
# Обе последние, а также CASEFILE_PORT, TRACKER_MCP_PORT и COMPOSE_PROJECT_NAME (если заданы)
# записываются в `.env` новой установки; без них действует `.env`
# существующей установки, а без него — умолчания compose-файла.
#   CASEFILE_SKILL     0 — не ставить скил агентам этой машины; 1, названная явно, — «да» заранее,
#                      без вопроса. Без неё на терминале перед шагом печатается список файлов
#                      чужих программ, которые он изменит, и спрашивается «y/N»; «N» пропускает
#                      шаг целиком (сервер при этом ставится как обычно). Без терминала (агент,
#                      CI) вопроса нет, шаг идёт как при 1 (TRK-408, TRK-546)
#   CASEFILE_PLUGIN_AUTOUPDATE  0 — плагин Claude Code ставится, но `"autoUpdate": true` в
#                      его settings.json не пишется (по умолчанию 1, TRK-546)
#   CASEFILE_SKILL_ONLY  1 — только агенты этой машины: без Docker, без каталога установки и
#                      без токена; для машины, которая подключается к Casefile на сервере.
#                      Адрес сервера в `CASEFILE_URL` — для чужого сервера, и только https (http — лишь для
#                      localhost: вне своей машины служба отдаёт вход OAuth только по https):
#                      curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh
#                      Без `CASEFILE_URL` плагин Claude Code и Codex ставится с адресом по
#                      умолчанию (http://127.0.0.1:8100/mcp): скил работает сразу, вход не
#                      ведётся, печатается, как задать адрес сервера.
#   CASEFILE_URL       адрес MCP сервера для `CASEFILE_SKILL_ONLY=1`; при полной установке
#                      адрес даёт сама установка
#   CASEFILE_LOGIN     0 — не вести вход OAuth, только напечатать команды (по умолчанию вход
#                      идёт, если есть терминал человека; без него — только печать)
#   CASEFILE_TTY       терминал для вопроса и входа, по умолчанию /dev/tty (в `| sh` stdin — труба);
#                      вопрос задаётся и при названном CASEFILE_TTY, даже если вывод не терминал
#   CASEFILE_SKILL_SOURCE  откуда брать маркетплейс скила, по умолчанию azimov777/casefile;
#                      так шаг проверяют до публикации, как CASEFILE_REGISTRY для образов
#   CASEFILE_MCPB_URL  откуда качать расширение Claude Desktop `casefile.mcpb`, по умолчанию
#                      файл выпуска на GitHub (TRK-514); так его тоже проверяют до публикации
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
# 1 — перед шагом скила спросить «y/N», если есть кого (`can_ask`); явно названная
# `CASEFILE_SKILL` — ответ заранее, вопроса нет (TRK-546).
SKILL_ASK=1
[ -z "${CASEFILE_SKILL:-}" ] || SKILL_ASK=0
# 1 — шаг скила не выполнялся: человек ответил «N» (TRK-546); `main` по нему не печатает
# про плагин то, чего нет.
SKILL_SKIPPED=0
PLUGIN_AUTOUPDATE=${CASEFILE_PLUGIN_AUTOUPDATE:-1}
SKILL_ONLY=${CASEFILE_SKILL_ONLY:-0}
SKILL_SOURCE=${CASEFILE_SKILL_SOURCE:-azimov777/casefile}
LOGIN=${CASEFILE_LOGIN:-1}
TTY=${CASEFILE_TTY:-/dev/tty}
# Адрес MCP, с которым ставится плагин: у полной установки — ответ самой установки, у
# `CASEFILE_SKILL_ONLY=1` — `CASEFILE_URL`; без него — адрес по умолчанию (TRK-480).
PLUGIN_URL=
# 1 — адрес не назван (`CASEFILE_SKILL_ONLY=1` без `CASEFILE_URL`): плагин ставится с
# адресом по умолчанию ради скила; вход OAuth не ведётся, чужие записи MCP не трогаются.
DEFAULT_URL=0
DEFAULT_NOTE=
# Адрес, который у Codex уже прописан в плагине (`.codex-plugin/mcp.json`): другой адрес
# ему задаёт только `codex mcp add` (TRK-451#13).
CODEX_PLUGIN_URL=http://127.0.0.1:8100/mcp
LOGIN_CLAUDE=0
LOGIN_CODEX=0
# Куда шаг Claude Desktop кладёт скачанный `casefile.mcpb` (`install_skills`, TRK-514).
MCPB_FILE=

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

# Автообновление сервера (TRK-548): по умолчанию включено, и человек должен узнать об этом
# до установки и после неё, вместе с тем, что служба `updater` для этого держит сокет
# Docker, и как это выключить. Выключено оно только точным `false` в `.env` — так читает
# его сама служба (`docker-compose.prod.yml`): `False`, `0` и пустое значение оставляют его
# включённым, и строки об этом печатаются по `.env`, а не по умолчанию. Строки есть только
# здесь, в полной установке: при `CASEFILE_SKILL_ONLY=1` сервера на машине нет, и слова об
# его автообновлении были бы неправдой.
auto_update_off() {
  [ "$(sed -n 's/^CASEFILE_AUTO_UPDATE=//p' "$DIR/.env" 2>/dev/null | tail -n 1)" = false ]
}

# До установки: каталог ещё не создан, и человек может остановиться (Ctrl+C), ничего не
# получив на диск.
auto_update_intro() {
  if auto_update_off; then
    bold "Auto-update is off in this installation (CASEFILE_AUTO_UPDATE=false in $DIR/.env)."
    echo "  This run installs the latest release. After it, the board tells you when a newer one is out,"
    echo "  and you update by running this installer again."
  else
    bold "Casefile updates itself."
    echo "  Once installed, its updater service checks for a new release when Docker starts and then every"
    echo "  hour, and installs it by replacing the Casefile containers; your data stays in its volumes."
    echo "  To replace containers the updater holds the Docker socket (/var/run/docker.sock), which is"
    echo "  root access to this machine."
    echo "  To turn it off, put CASEFILE_AUTO_UPDATE=false into $DIR/.env and run, in $DIR:"
    echo "    docker compose up -d --no-deps updater"
    echo "  Then the board tells you when a new release is out, and you update by running this installer again."
  fi
  echo
}

# В конце: тот же факт короткой строкой, с командой выключения (или включения обратно).
auto_update_outro() {
  if auto_update_off; then
    echo "Auto-update is off (CASEFILE_AUTO_UPDATE=false in $DIR/.env): the board tells you when a new release is out;"
    echo "update by running this installer again. To turn it on, delete that line and run, in $DIR:"
    echo "  docker compose up -d --no-deps updater"
  else
    echo "Updates arrive by themselves: the updater checks for a new release when Docker starts and then every hour,"
    echo "and holds the Docker socket (/var/run/docker.sock) for that. To turn it off, put CASEFILE_AUTO_UPDATE=false into $DIR/.env and run, in $DIR:"
    echo "  docker compose up -d --no-deps updater"
  fi
  echo "Files and data: $DIR"
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

# Снимок базы перед `up` (TRK-654): повторный запуск установщика и смена `CASEFILE_VERSION`
# мигрируют базу так же, как обновлятор, и ей нужна та же копия на случай беды. Правило и
# запрос те же, что в `schema_revision` службы `updater` (`docker-compose.prod.yml`, TRK-652):
# `no-table` — таблицы версии нет, база пуста, снимка нет; ревизия — сравнить с головой
# образа; пусто (не прочлось) — как «может меняться»: снимок. Общего файла между compose и
# установщиком нет, поэтому запрос продублирован. Снимок — тот же `pg_dump -Fc`, в том же
# томе `updater-snapshot`, под тем же именем `before-update.dump`: сначала целиком во
# временный файл, прежний снимок затирает лишь непустой. Сбой снимка — остановка до `up`.
SNAPSHOT_REVISION_SQL="SELECT CASE WHEN to_regclass('public.alembic_version') IS NULL THEN 'no-table' ELSE (xpath('/row/version_num/text()', query_to_xml('SELECT version_num FROM public.alembic_version', false, true, '')))[1]::text END"

snapshot_before_up() {
  # Первая установка — это нет тома базы, а не нет контейнера `db`: после `docker compose
  # down` без `-v` контейнеров нет, а том `pgdata` цел (TRK-664). Том есть, контейнера нет —
  # поднять одну `db`, дождаться здоровья и дальше по тем же правилам. Том ищется по меткам
  # compose: проект — из `docker compose config`, иначе имя каталога установки.
  if [ -z "$(docker compose ps -aq db </dev/null 2>/dev/null)" ]; then
    project=$(docker compose config </dev/null 2>/dev/null | awk '/^name: / { print $2; exit }')
    [ -n "$project" ] || project=$(basename "$PWD" | tr '[:upper:]' '[:lower:]')
    [ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$project" \
      --filter label=com.docker.compose.volume=pgdata </dev/null 2>/dev/null)" ] || return 0
    docker compose up -d --wait db </dev/null >/dev/null 2>&1 ||
      fail "the database volume exists but the database did not start, so it could not be snapshotted; nothing was changed. See: docker compose logs db"
  fi
  revision=$(docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$1"' sh \
    "$SNAPSHOT_REVISION_SQL" </dev/null 2>/dev/null | head -n 1)
  [ "$revision" != no-table ] || return 0
  why=
  if [ -z "$revision" ]; then
    why="could not read the schema revision of the database"
  else
    api_image=$(docker compose config </dev/null 2>/dev/null |
      awk '/^  [^ ]/ { cur = $1 } cur == "api:" && /^    image: / { print $2; exit }')
    head_revision=
    [ -z "$api_image" ] ||
      head_revision=$(docker run --rm --pull never --network none --entrypoint alembic "$api_image" heads \
        </dev/null 2>/dev/null | awk 'NR == 1 { print $1 }')
    if [ -z "$head_revision" ]; then
      why="could not read the latest schema revision of the new image"
    elif [ "$head_revision" != "$revision" ]; then
      why="the release changes the database ($revision -> $head_revision)"
    fi
  fi
  [ -n "$why" ] || return 0

  bold "Taking a snapshot of the database before the update ($why)..."
  dump=$(mktemp "${TMPDIR:-/tmp}/casefile-snapshot.XXXXXX")
  if docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
      </dev/null >"$dump" 2>/dev/null && [ -s "$dump" ] &&
    docker compose run --rm --no-deps -T --entrypoint sh updater -c \
      'cat >/snapshot/before-update.dump.part && [ -s /snapshot/before-update.dump.part ] &&
       mv -f /snapshot/before-update.dump.part /snapshot/before-update.dump' <"$dump" >/dev/null 2>&1; then
    rm -f "$dump"
    echo "  Snapshot kept in the volume updater-snapshot as before-update.dump (docs/backup-restore.md)."
  else
    rm -f "$dump"
    fail "could not take a snapshot of the database before the update ($why); nothing was changed. Check that the database is running (docker compose ps db) and try again."
  fi
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

# --- Согласие и копии (TRK-546) -----------------------------------------------------------
# Шаг скила меняет файлы чужих программ: `settings.json` Claude Code, `config.toml` Codex,
# их записи MCP, `~/.agents/skills`. Он идёт с согласия человека, а перед первой правкой
# файла рядом остаётся его копия `<имя>.casefile-bak`. Beads потерял доверие именно этим:
# переписывал `~/.claude/settings.json` без вопроса (TRK-527#7).

claude_settings_file() { printf '%s' "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"; }
# Пользовательские и локальные записи MCP Claude Code лежат не в settings.json, а в
# `.claude.json`: `claude mcp remove` правит его, и копия нужна ему.
claude_json_file() { printf '%s' "${CLAUDE_CONFIG_DIR:-$HOME}/.claude.json"; }
codex_config_file() { printf '%s' "${CODEX_HOME:-$HOME/.codex}/config.toml"; }

# Есть ли у кого спросить. В `curl | sh` stdin — труба, поэтому читается терминал `$TTY`
# (по умолчанию `/dev/tty`), а не stdin. Одного «открывается» мало: потомок сеанса с
# терминалом (агент, запущенный из терминала без `setsid`) его тоже открывает, но ответа
# оттуда никто не даст, и установщик встал бы навсегда на терминале чужой программы.
# Поэтому и вывод обязан идти на терминал, как у человека; названный `CASEFILE_TTY` —
# слово того, кто запускает (свой терминал, тест).
can_ask() {
  ( : <"$TTY" ) 2>/dev/null || return 1
  [ -n "${CASEFILE_TTY:-}" ] || [ -t 1 ] || [ -t 2 ]
}

# Копия кладётся один раз и дальше не затирается: повторный запуск видит файл уже тронутым
# и должен сохранить исходный. `cp -p` — с правами: в settings.json бывают ключи окружения,
# копия не должна оказаться читаемой всем. Нет файла — копировать нечего (0). Не вышло —
# 1: файл тогда не меняется, а вызывающий пропускает свой шаг.
backup_once() { # $1 — метка в выводе, $2 — файл
  [ -f "$2" ] || return 0
  [ ! -e "$2.casefile-bak" ] && [ ! -L "$2.casefile-bak" ] || return 0
  if cp -p "$2" "$2.casefile-bak" 2>/dev/null; then
    skill_line "$1" "saved a copy of $2 as $(basename "$2").casefile-bak (the original, kept: it is never overwritten)"
  else
    skill_line "$1" "could not save a copy of $2, so nothing in it was changed"
    return 1
  fi
}

# Что шаг изменит, и вопрос. 0 — идти дальше, 1 — человек ответил «N»: шаг пропущен
# целиком (сервер уже стоит). Список печатается и без терминала — в журнале агента или CI
# видно, что было тронуто. Строится по найденным харнессам и режиму: чужие записи MCP
# убираются, только если адрес известен (не `DEFAULT_URL`), а config.toml Codex получает
# запись, только если адрес не тот, что зашит в его плагине.
skill_consent() {
  c_claude=0 c_codex=0 c_hermes=0 c_npx=0 c_desktop=0
  if command -v claude >/dev/null 2>&1; then c_claude=1; fi
  if command -v codex >/dev/null 2>&1; then c_codex=1; fi
  if command -v hermes >/dev/null 2>&1; then c_hermes=1; fi
  if command -v npx >/dev/null 2>&1; then c_npx=1; fi
  if desktop_pending; then c_desktop=1; fi
  [ $((c_claude + c_codex + c_hermes + c_npx + c_desktop)) -gt 0 ] || return 0
  echo "  This step changes files that belong to other programs. Before the first change to a file"
  echo "  a copy is saved next to it as <name>.casefile-bak (kept, never overwritten). What it touches:"
  if [ "$c_claude" = 1 ]; then
    skill_line "Claude Code" "$(claude_settings_file): the claude command adds the plugin there"
    if [ "$PLUGIN_AUTOUPDATE" != 0 ]; then
      skill_line "" "and \"autoUpdate\": true goes into extraKnownMarketplaces.casefile (CASEFILE_PLUGIN_AUTOUPDATE=0 leaves it out)"
    fi
    if [ "$DEFAULT_URL" != 1 ]; then
      skill_line "" "the manual MCP entries \"casefile\" and \"tracker\" at $PLUGIN_URL are removed ($(claude_json_file); its copy keeps them)"
    fi
  fi
  if [ "$c_codex" = 1 ]; then
    skill_line "Codex" "$(codex_config_file): the codex command adds the plugin there"
    if [ "$(norm_url "$PLUGIN_URL")" != "$(norm_url "$CODEX_PLUGIN_URL")" ]; then
      skill_line "" "and the lines [mcp_servers.casefile] url = \"$PLUGIN_URL\" are appended"
    fi
    if [ "$DEFAULT_URL" != 1 ]; then
      skill_line "" "the manual MCP entries \"casefile\" and \"tracker\" at $PLUGIN_URL are removed (its copy keeps them)"
    fi
  fi
  if [ "$c_hermes" = 1 ]; then
    skill_line "Hermes" "hermes skills install (its own skills folder)"
  fi
  if [ "$c_npx" = 1 ]; then
    skill_line "Other agents" "$HOME/.agents/skills/casefile (npx skills add)"
  fi
  if [ "$c_desktop" = 1 ]; then
    skill_line "Claude Desktop" "casefile.mcpb is downloaded to $MCPB_FILE and opened; Claude Desktop then"
    skill_line "" "asks before it installs anything (claude_desktop_config.json is not touched)"
  fi
  if [ "$SKILL_ASK" = 0 ]; then
    echo "  CASEFILE_SKILL=1 is set: going ahead without asking."
  elif can_ask; then
    printf '  Install the plugin and make these changes? [y/N] '
    answer=
    read -r answer <"$TTY" || echo
    case "$answer" in
      y | Y | yes | Yes | YES) ;;
      *)
        SKILL_SKIPPED=1
        later="curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL=1"
        [ "$SKILL_ONLY" != 1 ] || later="$later CASEFILE_SKILL_ONLY=1"
        [ -z "${CASEFILE_URL:-}" ] || later="$later CASEFILE_URL=$CASEFILE_URL"
        echo "  Skipped: no file of another program was touched. To install the plugin later, run the"
        echo "  installer again and answer y (CASEFILE_SKILL=1 in front of sh skips the question):"
        echo "    $later sh"
        echo "  Or by hand: docs/agent-install.md, step 4"
        echo "  (https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md)."
        echo
        return 1 ;;
    esac
  else
    echo "  No terminal to ask on, so it goes ahead (CASEFILE_SKILL=0 skips it)."
  fi
}

# Объявление маркетплейса `casefile` в settings.json Claude Code правится точечно (TRK-546):
# файл не пересобирается из разобранного JSON, а получает ровно одну текстовую вставку —
# так порядок ключей, отступы, концы строк и всё, что лежит рядом, остаются байт в байт.
# Узел находится сканером по тексту (границы строк и вложенных значений), вставка
# проверяется разбором: результат обязан равняться исходному объекту с одним изменённым
# ключом, иначе файл не пишется. `auto_update` ставит `"autoUpdate": true` последним ключом
# extraKnownMarketplaces.casefile: у сторонних маркетплейсов Claude Code обновляет плагин
# сам только с ним, а флага в CLI нет (TRK-406). `drop` вырезает само объявление вместе с
# запятой: так установка уходит с прежнего источника (TRK-494). Нужны node или python3 (один
# и тот же алгоритм в обоих; jq пересобирает файл целиком, поэтому не годится); без них —
# отказ, и установщик печатает правку для ручного ввода. Файл пишется, только если изменился;
# копию `.casefile-bak` кладёт `backup_once` до первой команды харнесса.
claude_settings() {
  settings=$(claude_settings_file)
  [ -f "$settings" ] || return 1
  patched="$skill_tmp/settings.json"
  if command -v node >/dev/null 2>&1; then
    node -e 'const fs=require("fs");
const text=fs.readFileSync(process.argv[1],"utf8"),op=process.argv[2];
JSON.parse(text.replace(/^\ufeff/,""));
const WS=" \t\r\n\ufeff";
const ws=i=>{while(i<text.length&&WS.includes(text[i]))i++;return i};
const sEnd=i=>{i++;while(text[i]!=="\"")i+=text[i]==="\\"?2:1;return i+1};
const vEnd=i=>{let c=text[i];
  if(c==="\"")return sEnd(i);
  if(c==="{"||c==="["){let d=0;for(;;){c=text[i];if(c==="\""){i=sEnd(i);continue}
    if(c==="{"||c==="[")d++;else if(c==="}"||c==="]")d--;i++;if(d===0)return i}}
  while(i<text.length&&!(WS+",}]").includes(text[i]))i++;return i};
const members=i=>{const out=[];i=ws(i+1);
  while(text[i]!=="}"){const ks=i,ke=sEnd(i);i=ws(ke);const vs=ws(i+1),ve=vEnd(vs);
    out.push({k:text.slice(ks,ke),ks,ke,vs,ve});i=ws(ve);if(text[i]===",")i=ws(i+1)}
  return out};
const find=(ms,k)=>ms.find(m=>m.k==="\""+k+"\"");
const want=JSON.parse(text.replace(/^\ufeff/,""));
const tm=find(members(ws(0)),"extraKnownMarketplaces");
const km=tm&&text[tm.vs]==="{"?members(tm.vs):[];
const mc=find(km,"casefile");
let out=text;
if(!mc||text[mc.vs]!=="{"){if(op!=="drop")process.exit(1)}
else if(op==="drop"){const i=km.indexOf(mc);
  out=km.length===1?text.slice(0,tm.vs+1)+text.slice(mc.ve)
    :i<km.length-1?text.slice(0,mc.ks)+text.slice(km[i+1].ks)
    :text.slice(0,km[i-1].ve)+text.slice(mc.ve);
  delete want.extraKnownMarketplaces.casefile}
else{const cm=members(mc.vs),au=find(cm,"autoUpdate");
  if(au)out=text.slice(0,au.vs)+"true"+text.slice(au.ve);
  else if(!cm.length)out=text.slice(0,mc.vs+1)+"\"autoUpdate\": true"+text.slice(mc.vs+1);
  else{const e=cm[cm.length-1].ve,f=cm[0];
    out=text.slice(0,e)+","+text.slice(mc.vs+1,f.ks)+"\"autoUpdate\""+text.slice(f.ke,f.vs)+"true"+text.slice(e)}
  want.extraKnownMarketplaces.casefile.autoUpdate=true}
if(JSON.stringify(JSON.parse(out.replace(/^\ufeff/,"")))!==JSON.stringify(want))process.exit(2);
process.stdout.write(out)' "$settings" "$1" >"$patched" || return 1
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys
path,op=sys.argv[1],sys.argv[2]
text=open(path,encoding="utf-8",newline="").read()
want=json.loads(text.lstrip("\ufeff"))
WS=" \t\r\n\ufeff"
def ws(i):
    while i<len(text) and text[i] in WS: i+=1
    return i
def s_end(i):
    i+=1
    while text[i]!="\"": i+=2 if text[i]=="\\" else 1
    return i+1
def v_end(i):
    c=text[i]
    if c=="\"": return s_end(i)
    if c in "{[":
        d=0
        while True:
            c=text[i]
            if c=="\"": i=s_end(i); continue
            if c in "{[": d+=1
            elif c in "}]": d-=1
            i+=1
            if d==0: return i
    while i<len(text) and text[i] not in WS+",}]": i+=1
    return i
def members(i):
    out=[]; i=ws(i+1)
    while text[i]!="}":
        ks=i; ke=s_end(i); i=ws(ke); vs=ws(i+1); ve=v_end(vs)
        out.append((text[ks:ke],ks,ke,vs,ve)); i=ws(ve)
        if text[i]==",": i=ws(i+1)
    return out
def find(ms,k):
    return next((m for m in ms if m[0]=="\""+k+"\""),None)
tm=find(members(ws(0)),"extraKnownMarketplaces")
km=members(tm[3]) if tm and text[tm[3]]=="{" else []
mc=find(km,"casefile")
out=text
if mc is None or text[mc[3]]!="{":
    if op!="drop": sys.exit(1)
elif op=="drop":
    i=km.index(mc)
    if len(km)==1: out=text[:tm[3]+1]+text[mc[4]:]
    elif i<len(km)-1: out=text[:mc[1]]+text[km[i+1][1]:]
    else: out=text[:km[i-1][4]]+text[mc[4]:]
    del want["extraKnownMarketplaces"]["casefile"]
else:
    cm=members(mc[3]); au=find(cm,"autoUpdate")
    if au: out=text[:au[3]]+"true"+text[au[4]:]
    elif not cm: out=text[:mc[3]+1]+"\"autoUpdate\": true"+text[mc[3]+1:]
    else:
        e=cm[-1][4]; f=cm[0]
        out=text[:e]+","+text[mc[3]+1:f[1]]+"\"autoUpdate\""+text[f[2]:f[3]]+"true"+text[e:]
    want["extraKnownMarketplaces"]["casefile"]["autoUpdate"]=True
if json.loads(out.lstrip("\ufeff"))!=want: sys.exit(2)
sys.stdout.buffer.write(out.encode("utf-8"))' "$settings" "$1" >"$patched" || return 1
  else
    return 1
  fi
  cmp -s "$patched" "$settings" || cat "$patched" >"$settings"
}

# Маркетплейс плагина — узкая ветка `plugin`: в ней одни файлы плагина (TRK-494). Со
# `stable` харнесс выписывал и файлы корня репозитория — `--sparse` в режиме cone берёт их
# всегда, — и `source: "./"` уносил их в cache плагина. Установка, поставленная со
# `stable`, держит прежний источник: Claude Code отказывает в `add` с другим источником
# (до 2.1.289 — «differs from the one declared», с 2.1.289 — «its source doesn't match its
# extraKnownMarketplaces entry»), Codex — «already added from a different source». Тогда
# прежний источник снимается и `add` повторяется. Сопоставляются обе фразы Claude Code, и
# только они: иная ошибка `add` — не повод править settings.json (TRK-550). У Claude Code снимается только объявление в
# settings.json: `marketplace remove` удалил бы и плагин с его настройками. У Codex
# `marketplace remove` оставляет плагин включённым, а `plugin add` ниже ставит его заново.
claude_marketplace_add() {
  skill_run claude plugin marketplace add "$1" && return 0
  tail -n 5 "$skill_log" | grep -Eq 'differs from the one declared|match its extraKnownMarketplaces entry' || return 1
  claude_settings drop && skill_run claude plugin marketplace add "$1" && CLAUDE_MOVED=1
}

# Вход Claude Code лежит под ключом «имя сервера | хеш type, url, headers» (TRK-502#6): другой
# адрес, даже `127.0.0.1` вместо `localhost`, — другой ключ, и прежний вход клиент не видит.
# Поэтому адрес установленного плагина читается до `install`: без `CASEFILE_URL` он
# остаётся, а смена адреса печатает команду входа. Пусто — плагина нет или клиент старый.
claude_current_url() {
  claude plugin configure casefile@casefile --json </dev/null 2>/dev/null |
    sed -n 's/^ *"casefile_url": *"\([^"]*\)".*/\1/p' | head -n 1
}

codex_marketplace_add() {
  skill_run codex plugin marketplace add "$SKILL_SOURCE" --ref plugin && return 0
  tail -n 5 "$skill_log" | grep -q 'already added from a different source' || return 1
  skill_run codex plugin marketplace remove casefile &&
    skill_run codex plugin marketplace add "$SKILL_SOURCE" --ref plugin
}

# --- Ручные записи MCP, которые плагин заменяет (TRK-452, TRK-427#10) ------------------------
# Записи `casefile` (и `tracker`, как её звали раньше) со старым токеном в заголовке
# дублируют коннектор плагина: у Claude Code при том же адресе ручная запись главнее и
# держит токен в файле, у Codex она вытесняет плагинную. Убирается только своё: запись с
# этим именем И с адресом этой установки (`localhost` и `127.0.0.1` — один адрес).
# Остальные остаются как есть, а о каждом решении печатается строка.

norm_url() { printf '%s' "$1" | sed -e 's#^\(https\{0,1\}://\)localhost#\1127.0.0.1#' -e 's#/*$##'; }

cleanup_claude_entries() {
  for name in casefile tracker; do
    info=$(claude mcp get "$name" </dev/null 2>/dev/null) || continue
    url=$(printf '%s\n' "$info" | sed -n 's/^  URL: *//p' | head -n 1)
    scope=$(printf '%s\n' "$info" | sed -n 's/^  Scope: *\([A-Za-z]*\).*/\1/p' | head -n 1)
    [ -n "$url" ] || continue
    if [ "$(norm_url "$url")" = "$(norm_url "$PLUGIN_URL")" ]; then
      case "$scope" in User) flag=user ;; Local) flag=local ;; *) flag= ;; esac
      if [ -n "$flag" ] && backup_once "Claude Code" "$(claude_json_file)" &&
        skill_run claude mcp remove "$name" --scope "$flag"; then
        skill_line "Claude Code" "removed the manual MCP entry \"$name\" ($url, $flag scope): the plugin carries the connection"
      else
        skill_line "Claude Code" "left the manual MCP entry \"$name\" ($url, $scope scope): remove it by hand: claude mcp remove $name"
      fi
    else
      skill_line "Claude Code" "left the MCP entry \"$name\" ($url): it is not this installation's address"
    fi
  done
}

cleanup_codex_entries() {
  for name in casefile tracker; do
    info=$(codex mcp get "$name" --json </dev/null 2>/dev/null) || continue
    url=$(printf '%s\n' "$info" | sed -n 's/.*"url": *"\([^"]*\)".*/\1/p' | head -n 1)
    [ -n "$url" ] || continue
    if [ "$(norm_url "$url")" = "$(norm_url "$PLUGIN_URL")" ]; then
      if skill_run codex mcp remove "$name"; then
        skill_line "Codex" "removed the manual MCP entry \"$name\" ($url) from config.toml"
      else
        skill_line "Codex" "left the manual MCP entry \"$name\" ($url): remove it by hand: codex mcp remove $name"
      fi
    else
      skill_line "Codex" "left the MCP entry \"$name\" ($url): it is not this installation's address"
    fi
  done
}

skill_claude() {
  backup_once "Claude Code" "$(claude_settings_file)" || return 0
  src="$SKILL_SOURCE#plugin"
  claude_url=$PLUGIN_URL
  claude_note=$DEFAULT_NOTE
  claude_was=$(claude_current_url)
  CLAUDE_MOVED=0
  if [ "$DEFAULT_URL" = 1 ] && [ -n "$claude_was" ]; then
    claude_url=$claude_was
    claude_note=" (kept the address it had: your server's goes in CASEFILE_URL)"
  fi
  retry="claude plugin marketplace add $src && claude plugin install casefile@casefile --scope user --config casefile_url=$claude_url"
  [ "$DEFAULT_URL" = 1 ] || cleanup_claude_entries
  if claude_marketplace_add "$src" &&
    skill_run claude plugin marketplace update casefile &&
    skill_run claude plugin install casefile@casefile --scope user --config "casefile_url=$claude_url" &&
    skill_run claude plugin update casefile@casefile; then
    found=$(claude plugin list </dev/null 2>/dev/null |
      awk '/casefile@casefile/ {f=1; next} f && /Version:/ {v=$2} f && /Status:/ {print v, ($0 ~ /enabled/ ? "enabled" : "off"); exit}')
    case "$found" in
      *" enabled")
        [ "$DEFAULT_URL" = 1 ] || LOGIN_CLAUDE=1
        if [ "$PLUGIN_AUTOUPDATE" = 0 ]; then
          skill_line "Claude Code" "installed ${found% *}, connected to $claude_url$claude_note (automatic updates not switched on, as CASEFILE_PLUGIN_AUTOUPDATE=0 says; to update by hand: claude plugin update casefile@casefile)"
        elif claude_settings auto_update; then
          skill_line "Claude Code" "installed ${found% *} (updates itself), connected to $claude_url$claude_note"
        else
          skill_line "Claude Code" "installed ${found% *}, connected to $claude_url$claude_note (automatic updates not switched on: add \"autoUpdate\": true inside extraKnownMarketplaces.casefile in settings.json)"
        fi
        if [ -n "$claude_was" ] && [ "$claude_was" != "$claude_url" ]; then
          skill_line "Claude Code" "the address changed from $claude_was: the sign-in belongs to the address, sign in again: claude mcp login plugin:casefile:casefile"
        elif [ "$CLAUDE_MOVED" = 1 ]; then
          skill_line "Claude Code" "moved to the plugin branch; the sign-in stays with the address - if claude mcp list shows \"Needs authentication\": claude mcp login plugin:casefile:casefile"
        fi ;;
      *) skill_failed "Claude Code" "$retry" ;;
    esac
  else
    skill_failed "Claude Code" "$retry"
  fi
}

codex_set_url() {
  cfg=$(codex_config_file)
  if [ -f "$cfg" ] && grep -q '^\[mcp_servers\.casefile[].]' "$cfg"; then
    return 1
  fi
  mkdir -p "$(dirname "$cfg")" || return 1
  printf '\n[mcp_servers.casefile]\nurl = "%s"\n' "$PLUGIN_URL" >>"$cfg"
}

skill_codex() {
  backup_once "Codex" "$(codex_config_file)" || return 0
  retry="codex plugin marketplace add $SKILL_SOURCE --ref plugin && codex plugin add casefile@casefile"
  [ "$DEFAULT_URL" = 1 ] || cleanup_codex_entries
  if codex_marketplace_add &&
    skill_run codex plugin marketplace upgrade casefile &&
    skill_run codex plugin add casefile@casefile; then
    found=$(codex plugin list </dev/null 2>/dev/null | awk '$1 == "casefile@casefile" && /installed/ {
      for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+[.][0-9]+/) { print $i; exit } }')
    if [ -z "$found" ]; then
      skill_failed "Codex" "$retry"
      return 0
    fi
    [ "$DEFAULT_URL" = 1 ] || LOGIN_CODEX=1
    # Адрес плагина у Codex зашит: другой задаёт одноимённый сервер из config.toml, он
    # вытесняет плагинный (TRK-451#13). Токена в нём нет — вход OAuth. Строка пишется сюда
    # же, куда её пишет `codex mcp add`, но без него: тот сразу запускает вход и без
    # терминала возвращает ошибку, хотя запись уже есть.
    if [ "$(norm_url "$PLUGIN_URL")" = "$(norm_url "$CODEX_PLUGIN_URL")" ]; then
      skill_line "Codex" "installed $found, connected to $PLUGIN_URL$DEFAULT_NOTE"
    elif codex_set_url; then
      skill_line "Codex" "installed $found, connected to $PLUGIN_URL (an entry without a token in config.toml)"
    else
      skill_failed "Codex" "codex mcp add casefile --url $PLUGIN_URL"
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

# --- Claude Desktop (TRK-514) -------------------------------------------------------------
# Чат десктоп-приложения Claude не видит ни плагин, ни записи Claude Code: у него свои
# локальные серверы. Casefile приходит туда расширением `casefile.mcpb` из выпуска GitHub
# (решение TRK-514#5): внутри мост `mcp-remote` на встроенной в Desktop среде Node — Node.js
# человеку не нужен, — адрес спрашивает форма Desktop, вход — OAuth моста. Установщик файл
# только скачивает и открывает (`open`): ставит его сам Desktop, по щелчку человека, и
# `claude_desktop_config.json` никто не правит. Стоящее расширение второй раз не открывается:
# Desktop держит его распакованный манифест в `Claude Extensions/<id>/manifest.json`, а наш
# узнаётся по адресу репозитория. Новый выпуск расширения сам не приезжает — его файл
# называется в строке итога.

desktop_dir() { printf '%s' "$HOME/Library/Application Support/Claude"; }

# Файл выпуска, названного CASEFILE_VERSION (полная установка — ещё и её `.env`), иначе
# последнего; CASEFILE_MCPB_URL — свой адрес. Имя файла без версии, и у последнего выпуска
# адрес постоянный (`.github/workflows/mcpb.yml`).
mcpb_url() {
  if [ -n "${CASEFILE_MCPB_URL:-}" ]; then
    printf '%s' "$CASEFILE_MCPB_URL"
    return 0
  fi
  mcpb_version=${CASEFILE_VERSION:-}
  if [ -z "$mcpb_version" ] && [ "$SKILL_ONLY" != 1 ]; then
    mcpb_version=$(setting CASEFILE_VERSION stable)
  fi
  case "$mcpb_version" in
    [0-9]*) printf 'https://github.com/azimov777/casefile/releases/download/v%s/casefile.mcpb' "$mcpb_version" ;;
    *) printf '%s' https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb ;;
  esac
}

# Версия стоящего расширения Casefile (или `installed`, если её не прочесть); пусто — нет.
desktop_extension() {
  for manifest in "$(desktop_dir)/Claude Extensions"/*/manifest.json; do
    [ -f "$manifest" ] && grep -q 'github.com/azimov777/casefile' "$manifest" || continue
    found=$(sed -n 's/^ *"version": *"\([^"]*\)".*/\1/p' "$manifest" | head -n 1)
    printf '%s' "${found:-installed}"
    return 0
  done
}

# Шагу есть что делать: Desktop стоит, адрес сервера известен, расширения ещё нет.
desktop_pending() {
  [ -d "$(desktop_dir)" ] && [ "$DEFAULT_URL" != 1 ] && [ -z "$(desktop_extension)" ]
}

skill_desktop() {
  url=$(mcpb_url)
  by_hand="double-click it, or in Claude Desktop: Settings > Extensions > Advanced settings > Install Extension..."
  if [ "$DEFAULT_URL" = 1 ]; then
    skill_line "Claude Desktop" "not set up: it needs your server's address in CASEFILE_URL (or install $url by hand)"
    return 0
  fi
  found=$(desktop_extension)
  if [ -n "$found" ]; then
    skill_line "Claude Desktop" "has the Casefile extension ($found); a newer one: $url, $by_hand"
    return 0
  fi
  # Адрес по умолчанию у расширения тот же, что у плагина Codex (`mcpb/manifest.json`).
  if [ "$(norm_url "$PLUGIN_URL")" = "$(norm_url "$CODEX_PLUGIN_URL")" ]; then
    address="keep the address it shows ($CODEX_PLUGIN_URL)"
  else
    address="put $PLUGIN_URL into its address field"
  fi
  if ! skill_run curl -fsSL -o "$MCPB_FILE.download" "$url"; then
    rm -f "$MCPB_FILE.download"
    skill_line "Claude Desktop" "could not download $url - download it and $by_hand; $address"
    tail -n 2 "$skill_log" | sed 's/^/                > /'
    return 0
  fi
  mv -f "$MCPB_FILE.download" "$MCPB_FILE" || {
    skill_line "Claude Desktop" "could not save $MCPB_FILE - download $url and $by_hand"
    return 0
  }
  if skill_run open "$MCPB_FILE"; then
    skill_line "Claude Desktop" "opened $MCPB_FILE: click Install in Claude Desktop and $address;"
    skill_line "" "its first connection opens a browser page for the sign-in (Node.js is not needed)"
  else
    skill_line "Claude Desktop" "could not open $MCPB_FILE - $by_hand; $address"
  fi
}

install_skills() {
  # Полная установка кладёт расширение в свой каталог, `CASEFILE_SKILL_ONLY=1` каталога не
  # заводит — туда же, куда его положил бы браузер.
  if [ "$SKILL_ONLY" = 1 ]; then
    if [ -d "$HOME/Downloads" ]; then MCPB_FILE="$HOME/Downloads/casefile.mcpb"; else MCPB_FILE="$HOME/casefile.mcpb"; fi
  else
    MCPB_FILE="$DIR/casefile.mcpb"
  fi
  skill_tmp=$(mktemp -d)
  skill_log="$skill_tmp/log"
  : >"$skill_log"
  bold "Installing the Casefile skill for the agents on this machine:"
  if ! skill_consent; then
    rm -rf "$skill_tmp"
    return 0
  fi
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
  if [ -d "$(desktop_dir)" ]; then
    skill_desktop
  elif [ "$(uname -s 2>/dev/null)" = Darwin ]; then
    skill_line "Claude Desktop" "not found (run this installer again after installing it)"
  fi
  rm -rf "$skill_tmp"
  echo "  A running session picks up the plugin after a restart (in Claude Code: /reload-plugins)."
  echo
  sign_in || true
}

# --- Вход OAuth (TRK-452) -----------------------------------------------------------------
# Один раз на харнесс. Claude Code входит только в интерактивном терминале (TRK-432#8), и
# в `curl | sh` stdin — труба, поэтому терминал берётся из CASEFILE_TTY (`/dev/tty`). Нет
# терминала или CASEFILE_LOGIN=0 — вход не запускается, печатается команда. Ошибка входа
# установку не валит: это строка с командой повтора.

have_tty() { [ "$LOGIN" != 0 ] && ( : <"$TTY" ) 2>/dev/null; }

sign_in_one() { # $1 — имя харнесса, остальное — команда входа
  name=$1
  shift
  if "$@" <"$TTY"; then
    skill_line "$name" "signed in"
  else
    skill_line "$name" "sign-in did not finish - repeat by hand: $*"
  fi
}

sign_in() {
  [ "$LOGIN_CLAUDE" = 1 ] || [ "$LOGIN_CODEX" = 1 ] || return 0
  bold "Signing the agents in to Casefile (OAuth, no token on disk):"
  if have_tty; then
    echo "  A browser window may open; approve the sign-in there."
    [ "$LOGIN_CLAUDE" = 0 ] || sign_in_one "Claude Code" claude mcp login plugin:casefile:casefile
    [ "$LOGIN_CODEX" = 0 ] || sign_in_one "Codex" codex mcp login casefile
  else
    echo "  This needs a terminal; run once, in a terminal of yours:"
    [ "$LOGIN_CLAUDE" = 0 ] || echo "    claude mcp login plugin:casefile:casefile"
    [ "$LOGIN_CODEX" = 0 ] || echo "    codex mcp login casefile"
  fi
  echo
}

main() {
  if [ "$SKILL_ONLY" = 1 ]; then
    # Машина агента, которая только подключается к Casefile на сервере: ни Docker, ни
    # каталога установки, ни токена (TRK-401#18). Адрес сервера — `CASEFILE_URL`; с ним
    # ставится плагин (скил и коннектор) и ведётся вход OAuth, без него — тот же плагин с
    # адресом по умолчанию ради скила, без входа, и подсказка, как задать адрес (TRK-480).
    PLUGIN_URL=${CASEFILE_URL:-}
    if [ -z "$PLUGIN_URL" ]; then
      PLUGIN_URL=$CODEX_PLUGIN_URL
      DEFAULT_URL=1
      DEFAULT_NOTE=" (default address: your server's goes in CASEFILE_URL)"
    else
      case "$PLUGIN_URL" in
        https://?*) ;;
        http://localhost[:/]* | http://127.0.0.1[:/]* | http://\[::1\][:/]*) ;;
        *) fail "CASEFILE_URL must be an https:// address (http:// only for localhost): outside the local machine the service offers the OAuth sign-in over https only" ;;
      esac
    fi
    install_skills || true
    if [ "$DEFAULT_URL" = 1 ] && [ "$SKILL_SKIPPED" = 0 ]; then
      echo "The plugin carries the skill and points at the default address $PLUGIN_URL; no sign-in was started."
      echo "To connect Claude Code and Codex to your server, run this again with its address:"
      echo "  curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh"
      echo "(Windows PowerShell: \$env:CASEFILE_SKILL_ONLY=1; \$env:CASEFILE_URL='https://casefile.example.com/mcp'; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex)"
    fi
    echo "Other agents (Hermes and the like): docs/agent-install.md, \"Joining an installation someone else runs\""
    echo "(https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md)."
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

  auto_update_intro

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
      # Порты и имя проекта — тоже, если их назвали установщику (TRK-493): иначе обновлятор и
      # `docker compose up` из этого каталога вернули бы 8080/8100 и проект `casefile`.
      [ -z "${CASEFILE_PORT:-}" ] || echo "CASEFILE_PORT=$CASEFILE_PORT"
      [ -z "${TRACKER_MCP_PORT:-}" ] || echo "TRACKER_MCP_PORT=$TRACKER_MCP_PORT"
      [ -z "${COMPOSE_PROJECT_NAME:-}" ] || echo "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME"
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
  snapshot_before_up
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
  PLUGIN_URL=$mcp_url

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
  # Подключение — по блоку на харнесс (TRK-406, решения TRK-398#7, #9, TRK-401#18, TRK-452).
  # Claude Code и Codex подключены плагином и входят по OAuth: токена для них нет нигде.
  # Ключ агента печатается только харнессам без OAuth. Имена маркетплейса, плагина и веток
  # `plugin` и `stable` — из `.claude-plugin/marketplace.json` и `images.yml`; те же команды дословно
  # стоят в `docs/agent-install.md`, и `tests/test_installers.py` сверяет их.
  bold "Claude Code:"
  if [ "$SKILL_SKIPPED" = 1 ]; then
    echo "  The plugin is not installed: you skipped that step. It carries the skill and the connection"
    echo "  to $mcp_url; once installed, sign in with: claude mcp login plugin:casefile:casefile"
  else
    echo "  The plugin carries the skill and the connection to $mcp_url; the sign-in is OAuth,"
    echo "  no token in any file. If it did not run above: claude mcp login plugin:casefile:casefile"
  fi
  echo "  Without the installer: claude plugin marketplace add azimov777/casefile#plugin"
  echo "  claude plugin install casefile@casefile --scope user --config casefile_url=$mcp_url"
  echo
  bold "Codex:"
  if [ "$SKILL_SKIPPED" = 1 ]; then
    echo "  The plugin is not installed: you skipped that step. Once installed, sign in with: codex mcp login casefile"
  else
    echo "  The plugin carries the skill and the connection to $mcp_url; the sign-in is OAuth."
    echo "  If it did not run above: codex mcp login casefile"
  fi
  echo "  Without the installer: codex plugin marketplace add azimov777/casefile --ref plugin"
  echo "  codex plugin add casefile@casefile"
  echo
  bold "Claude Desktop (the chat app on macOS and Windows; OAuth, no token):"
  echo "  The Casefile extension: https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb"
  echo "  Double-click it (or Settings > Extensions > Advanced settings > Install Extension...), keep or set"
  echo "  the address $mcp_url and sign in on the page its first connection opens; it works while"
  echo "  this installation runs. No Node.js needed: the extension runs on the one inside Claude Desktop."
  echo
  bold "Hermes (OAuth, no token):"
  echo "  Add to ~/.hermes/config.yaml:"
  echo "    mcp_servers:"
  echo "      casefile:"
  echo "        url: \"$mcp_url\""
  echo "        auth: oauth"
  echo "  The sign-in page opens on the first connection, or: hermes mcp login casefile"
  echo "  hermes skills install azimov777/casefile/skills/casefile"
  echo
  bold "OpenCode (OAuth, no token):"
  echo "  Add to opencode.json (or ~/.config/opencode/opencode.json):"
  echo "    {\"mcp\": {\"casefile\": {\"type\": \"remote\", \"url\": \"$mcp_url\"}}}"
  echo "  Then sign in once: opencode mcp auth casefile"
  [ "$SKILL_SKIPPED" = 1 ] || echo "  The skill is the one in ~/.agents/skills/casefile that the step above installed."
  echo
  bold "Any other MCP client without OAuth (Cursor, ...), or a journal watcher between sessions:"
  echo "  URL     $mcp_url"
  echo "  Header  Authorization: Bearer $token"
  echo "  The key lives in the installation; read it again with (in $DIR):"
  echo "    docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token"
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

  echo "Another machine whose agents will connect to a Casefile server gets the plugin and the sign-in with"
  echo "(the address must be https unless it is localhost):"
  echo "  curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh"
  echo "  (Windows PowerShell: \$env:CASEFILE_SKILL_ONLY=1; \$env:CASEFILE_URL='https://casefile.example.com/mcp'; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex)"
  echo

  auto_update_outro
}

main "$@"
