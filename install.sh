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

main() {
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
  bold "Connect Claude Code:"
  echo "  claude mcp add --transport http --scope user casefile $mcp_url \\"
  echo "    --header \"Authorization: Bearer $token\""
  echo
  bold "Any other MCP client (Codex, Cursor, ...):"
  echo "  URL     $mcp_url"
  echo "  Header  Authorization: Bearer $token"
  echo
  echo "Updates arrive by themselves: Casefile checks for a new release every hour. Files and data: $DIR"
}

main "$@"
