#!/bin/sh
# Поднимает установку целиком и заканчивается адресом, по которому сразу видны задачи.
#
#   ./scripts/up.sh        (или `pnpm start`)
#
# Пять шагов: бэкенд, миграции, владелец, ключ интерфейса, интерфейс. Человек не вводит
# и не копирует ни одного секрета: ключ выпускает сама установка и кладёт в файл, скрипт
# передаёт его контуру интерфейса, а тот отдаёт браузеру конфигурацией на своём
# источнике. Секрет не покидает машину: порт опубликован только на петлю.
#
# Повторный запуск безопасен. Действующий ключ не перевыпускается, миграции идут поверх
# применённых, владелец заводится только на пустой установке, а контейнер интерфейса
# пересоздаётся, лишь если изменился образ или настройки, — открытая вкладка при этом
# продолжает работать с тем же ключом.
#
# Настройки — в `.env` рядом с `docker-compose.prod.yml` (образец: `.env.example`).
# Его же читает compose, поэтому одно значение живёт в одном месте.
set -eu

cd "$(dirname "$0")/.."

# `.env` читается так же, как его читает compose: переменная, уже стоящая в окружении,
# сильнее файла. Иначе `UI_PORT=8090 ./scripts/up.sh` молча поднимал бы контур на порту
# из файла.
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case $line in '' | '#'*) continue ;; esac
    key=${line%%=*}
    value=${line#*=}
    case $key in *[!A-Za-z0-9_]*) continue ;; esac
    # Кавычки вокруг значения снимает и compose: `.env` — не сценарий оболочки.
    case $value in
      '"'*'"') value=${value#\"} value=${value%\"} ;;
      "'"*"'") value=${value#\'} value=${value%\'} ;;
    esac
    # Именно `+`, а не `-`: переменная, выставленная пустой, тоже сильнее файла.
    eval "already=\${$key+set}"
    [ -n "${already:-}" ] || export "$key=$value"
  done <.env
fi

backend_dir=${TRACKER_BACKEND_DIR:-../tracker}
backend_compose=${TRACKER_BACKEND_COMPOSE:-docker-compose.prod.yml}
token_file=${TRACKER_UI_TOKEN_FILE:-$backend_dir/.secrets/ui-token}
ui_port=${UI_PORT:-8080}

# Свой файл контура подсовывается через `COMPOSE_FILE` — тем же способом, каким это
# делает `pnpm e2e` в соседних рабочих деревьях. Без него работает умолчание, и человеку
# ничего не надо помнить.
COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.prod.yml}
export COMPOSE_FILE

if [ ! -d "$backend_dir" ]; then
  echo "Бэкенда нет по пути $backend_dir." >&2
  echo "Склонируйте репозиторий tracker рядом или назовите путь в TRACKER_BACKEND_DIR." >&2
  exit 1
fi

# Каталог под ключ заводится здесь, а не Docker'ом: недостающий источник bind-mount
# Docker создаёт сам и на Linux — от root, а пишет в него непривилегированный процесс
# прод-образа бэкенда (`../tracker/docs/notes/docker.md`).
mkdir -p "$(dirname "$token_file")"

backend() {
  (cd "$backend_dir" && COMPOSE_FILE=$backend_compose docker compose "$@")
}

echo "1/5 Бэкенд: $backend_dir, $backend_compose"
backend up -d --wait

echo "2/5 Миграции"
backend run --rm migrate

echo "3/5 Владелец установки (на настроенной установке ничего не делает)"
backend run --rm init

echo "4/5 Ключ интерфейса (действующий не перевыпускается)"
backend run --rm local-token

if [ -z "${TRACKER_UI_TOKEN:-}" ] && [ -f "$token_file" ]; then
  TRACKER_UI_TOKEN=$(cat "$token_file")
  export TRACKER_UI_TOKEN
fi

# Сборка без provenance-манифеста. С ним `docker build` выдаёт **новый идентификатор
# образа даже на сборке, целиком попавшей в кэш** (замерено: два одинаковых прогона —
# два разных `Id`, с `--provenance=false` — один и тот же). Compose сравнивает
# идентификаторы, видит новый и пересоздаёт контейнер, то есть повторный запуск ронял бы
# открытую вкладку без всякой на то причины. Манифест этот нужен тому, кто образ
# публикует; здесь он не нужен никому.
BUILDX_NO_DEFAULT_ATTESTATIONS=${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}
export BUILDX_NO_DEFAULT_ATTESTATIONS

echo "5/5 Интерфейс"
docker compose up -d --build --wait

echo
if [ -n "${TRACKER_UI_TOKEN:-}" ]; then
  echo "Трекер открыт: http://127.0.0.1:$ui_port/"
  echo "Ключ выдала установка — вводить ничего не нужно."
else
  # Ключа нет, но контур поднят: это не отказ, а установка с экраном входа. Причина
  # почти всегда одна — команда `local-token` не дошла до файла на хосте.
  echo "Трекер открыт: http://127.0.0.1:$ui_port/"
  echo "Ключа установки нет ($token_file) — интерфейс встретит экраном входа."
fi
