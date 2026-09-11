#!/bin/sh
# Casefile installer for macOS and Linux:
#
#   curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | sh
#
# Кладёт `docker-compose.prod.yml` в каталог установки (`~/casefile`), поднимает контур
# и печатает, куда открыть интерфейс и чем подключить агента. Повторный запуск —
# это обновление: свежий compose-файл, свежие образы, данные остаются в томах.
#
# Нужен только Docker с Compose v2. Всё остальное — образы из ghcr.io, которые
# собирает конвейер из каждого коммита main. Секретов скрипт не спрашивает: ключ
# интерфейса и токен агента выпускает сама установка (`docker-compose.prod.yml`).
#
# Вывод для человека — по-английски, как и вся страница проекта на GitHub.
#
# Переменные (все необязательны):
#   CASEFILE_DIR     каталог установки, по умолчанию ~/casefile
#   CASEFILE_SOURCE  откуда брать файлы установки, по умолчанию raw-адрес main на GitHub;
#                    годится и file:// — так установщик проверяют до публикации
#
# Всё тело — в `main`, который зовётся последней строкой. Запущенный через `| sh`
# скрипт читается из трубы по мере исполнения, и любая команда, читающая stdin, съела бы
# его остаток: `docker compose run` так и делал, и установка молча кончалась на середине
# (TRK-58). С функцией оболочка дочитывает файл целиком прежде, чем выполнить хоть
# строку, — а заодно оборванная загрузка не исполняет половину скрипта. Docker-команды
# вдобавок читают `/dev/null`.
set -eu

DIR=${CASEFILE_DIR:-"$HOME/casefile"}
SOURCE=${CASEFILE_SOURCE:-https://raw.githubusercontent.com/azimov777/casefile/main}
COMPOSE=docker-compose.prod.yml

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() {
  printf 'casefile: %s\n' "$*" >&2
  exit 1
}

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$1" -O "$2"
  else
    fail "curl or wget is required to download $1"
  fi
}

# Значение переменной из `.env` установки или умолчание: порты в итоговом сообщении
# должны быть теми, на которых контур действительно поднялся.
setting() {
  value=$(sed -n "s/^$1=//p" .env 2>/dev/null | tail -n 1)
  printf '%s' "${value:-$2}"
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
  fetch "$SOURCE/$COMPOSE" "$COMPOSE.download"
  mv "$COMPOSE.download" "$COMPOSE"

  # `.env` заводится один раз и дальше принадлежит человеку: повторный запуск его не
  # трогает. COMPOSE_FILE — чтобы в этом каталоге работал просто `docker compose logs`;
  # CASEFILE_COMPOSE_URL — откуда службе updater освежать compose-файл.
  if [ ! -f .env ]; then
    {
      echo "COMPOSE_FILE=$COMPOSE"
      echo "CASEFILE_COMPOSE_URL=$SOURCE/$COMPOSE"
    } >.env
  fi

  bold "Starting Casefile (the first run downloads the images)..."
  docker compose pull --quiet </dev/null
  docker compose up -d --remove-orphans </dev/null

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

  ui_port=$(setting CASEFILE_PORT 8080)

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
  echo "Updates arrive by themselves every time Docker starts. Files and data: $DIR"
}

main "$@"
