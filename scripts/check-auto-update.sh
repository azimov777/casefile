#!/usr/bin/env bash
#
# Живая проверка автообновления установки (TRK-119) на своём реестре, без ghcr.io и GitHub:
#
#   CHECK_PROJECT=au-check scripts/check-auto-update.sh [каталог-для-улик]
#
# Поднимает установку из `docker-compose.prod.yml` в отдельном проекте compose и ведёт её
# через выпуски, которые кладёт в локальный `registry:2`:
#
#   A. переход: установка на compose-файле до TRK-119 (`latest`, обновлятор без канала и
#      без проверки на ходу) после «старта Docker» сама переходит на `stable`, а
#      `updater-renew` меняет ей обновлятор на нынешний;
#   B. новый выпуск под `stable` доходит до api/mcp/ui без перезапуска Docker, данные на
#      месте;
#   C. проверка без нового выпуска не пересоздаёт ни одной службы;
#   D. новый образ под `latest` и новый compose-файл «в main» установку не трогают;
#   E. закреплённый `CASEFILE_VERSION` и `CASEFILE_AUTO_UPDATE=false` останавливают
#      обновление, а снятое выключение его возвращает;
#   F. повторный запуск `install.sh` берёт compose-файл из образа выпуска.
#
# Час ожидания сокращён: `CASEFILE_UPDATE_INTERVAL` берётся из `CHECK_INTERVAL` (по
# умолчанию `1m`), разброс — до шестой доли, как и у часа. Каждая фаза кончается
# проверкой; первая неудача останавливает скрипт с кодом 1. Улики — логи обновлятора,
# `docker inspect` служб до и после, вывод установщика — в каталоге первого аргумента.
#
# «main на GitHub», с которого старый обновлятор качает compose-файл, — контейнер httpd в
# сети проекта. Скрипт собирает образы из рабочего дерева, поэтому запускается из корня
# репозитория. Всё своё — контейнеры, тома, реестр, образы под его адресом — он гасит на
# выходе; образы сборки `<проект>-build/*` остаются.
#
# Переменные:
#   CHECK_PROJECT   имя проекта compose, обязательно и не `casefile`: это установка
#   CHECK_PORT      порт реестра (по умолчанию 5019); интерфейс — на 200 выше, MCP — на 300
#   CHECK_INTERVAL  интервал проверок обновлятора (по умолчанию 1m)
#   CHECK_OLD_REF   коммит с compose-файлом до TRK-119 (по умолчанию 428a9a1)
set -euo pipefail

P=${CHECK_PROJECT:?CHECK_PROJECT is required}
[ "$P" != casefile ] || { echo "refusing to touch the project casefile" >&2; exit 2; }
PORT=${CHECK_PORT:-5019}
REG_PORT=$PORT UI_PORT=$((PORT + 200)) MCP_PORT=$((PORT + 300))
INTERVAL=${CHECK_INTERVAL:-1m}
OLD_REF=${CHECK_OLD_REF:-428a9a1}
ROOT=$(pwd)
EVIDENCE=$(mkdir -p "${1:-/tmp/$P-evidence}" && cd "${1:-/tmp/$P-evidence}" && pwd)
WORK=$(mktemp -d)
DIR=$WORK/install
WEB=$WORK/web
REG=localhost:$REG_PORT
mkdir -p "$DIR" "$WEB"

# Всё, что зовёт compose, — строго в своём проекте: и здесь, и внутри обновлятора (`.env`).
export COMPOSE_PROJECT_NAME=$P COMPOSE_FILE=docker-compose.prod.yml
unset CASEFILE_REGISTRY CASEFILE_VERSION CASEFILE_DIR

say() { printf '\n=== %s\n' "$*" | tee -a "$EVIDENCE/run.log"; }
note() { printf '%s\n' "$*" | tee -a "$EVIDENCE/run.log"; }
fail() { note "FAIL: $*"; exit 1; }
dc() { (cd "$DIR" && docker compose "$@"); }

cleanup() {
  set +e
  dc logs --no-color -t updater updater-renew >"$EVIDENCE/compose-logs.txt" 2>&1
  dc down -v --remove-orphans >/dev/null 2>&1
  docker rm -f "$P-registry" "$P-web" >/dev/null 2>&1
  docker images --format '{{.Repository}}:{{.Tag}}' | grep "^$REG/" | xargs docker rmi >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

[ -z "$(docker ps -aq --filter "label=com.docker.compose.project=$P")" ] ||
  fail "project $P already has containers"

# --- Образы -----------------------------------------------------------------------------

say "build images from the working tree"
docker build -q -f docker/Dockerfile.prod -t "$P-build/casefile" . >/dev/null
docker build -q -f ui/docker/Dockerfile -t "$P-build/casefile-ui" ui >/dev/null

docker run -d --name "$P-registry" -p "127.0.0.1:$REG_PORT:5000" registry:2 >/dev/null
docker run -d --name "$P-web" -v "$WEB:/www:ro" busybox httpd -f -p 80 -h /www >/dev/null
sleep 2

# Выпуск: образ дерева с меткой версии — у каждого выпуска свой Id. Второй
# аргумент — compose-файл, который выпуск несёт в себе (по умолчанию файл дерева).
# Локальная копия после push удаляется: иначе `pull` скачивать нечего.
publish() {
  local version=$1 compose=${2:-$ROOT/docker-compose.prod.yml} tags=("${@:3}") ctx
  ctx=$(mktemp -d)
  cp "$compose" "$ctx/docker-compose.prod.yml"
  printf 'FROM %s\nLABEL org.opencontainers.image.version=%s\nCOPY docker-compose.prod.yml /app/\n' \
    "$P-build/casefile" "$version" >"$ctx/Dockerfile"
  docker build -q -t "$REG/casefile:$version" "$ctx" >/dev/null
  printf 'FROM %s\nLABEL org.opencontainers.image.version=%s\n' \
    "$P-build/casefile-ui" "$version" | docker build -q -t "$REG/casefile-ui:$version" - >/dev/null
  rm -rf "$ctx"
  for name in casefile casefile-ui; do
    docker push -q "$REG/$name:$version" >/dev/null
    for tag in "${tags[@]}"; do
      docker tag "$REG/$name:$version" "$REG/$name:$tag"
      docker push -q "$REG/$name:$tag" >/dev/null
      docker rmi "$REG/$name:$tag" >/dev/null
    done
    note "$(docker image inspect -f '{{.Id}}' "$REG/$name:$version") = $name:$version ${tags[*]}"
    docker rmi "$REG/$name:$version" >/dev/null
  done
}

# Id образа выпуска в реестре: скачать его под номером и сразу забыть имя.
release_id() {
  docker pull -q "$REG/$1:$2" >/dev/null
  docker image inspect -f '{{.Id}}' "$REG/$1:$2"
}

# Службы: имя, Id образа, время создания контейнера.
services() {
  for s in api mcp ui updater; do
    c=$(dc ps -q "$s")
    [ -z "$c" ] || docker inspect -f "$s {{.Image}} {{.Created}} {{.Config.Image}}" "$c"
  done
}

image_of() { docker inspect -f '{{.Image}}' "$(dc ps -q "$1")"; }
checks_logged() { dc logs --no-color updater 2>/dev/null | grep -c "$1" || true; }

# Ждать, пока условие не станет истинным: не дольше `$1` секунд.
wait_for() {
  local limit=$1 i=0
  shift
  until "$@"; do
    i=$((i + 5))
    [ "$i" -le "$limit" ] || return 1
    sleep 5
  done
}

on_release() { [ "$(image_of api)" = "$1" ] && [ "$(image_of mcp)" = "$1" ] && [ "$(image_of ui)" = "$2" ]; }
more_checks() { [ "$(checks_logged "$1")" -gt "$2" ]; }

token() { dc run --rm --no-deps -T agent-token cat .secrets/agent-token </dev/null; }
api() { curl -fsS -H "Authorization: Bearer $(token)" "$@"; }

# --- A. Переход установки с `latest` ------------------------------------------------------

say "A. an installation from before TRK-119 on latest ($OLD_REF)"
publish main "" latest
git -C "$ROOT" show "$OLD_REF:docker-compose.prod.yml" >"$DIR/docker-compose.prod.yml"
cp "$DIR/docker-compose.prod.yml" "$WEB/docker-compose.prod.yml"
cat >"$DIR/.env" <<EOF
COMPOSE_FILE=docker-compose.prod.yml
COMPOSE_PROJECT_NAME=$P
CASEFILE_REGISTRY=$REG
CASEFILE_PORT=$UI_PORT
TRACKER_MCP_PORT=$MCP_PORT
CASEFILE_UPDATE_INTERVAL=$INTERVAL
CASEFILE_COMPOSE_URL=http://casefile-main/docker-compose.prod.yml
EOF
[ "$(dc config | sed -n 1p)" = "name: $P" ] || fail "compose would not stay in project $P"
dc up -d --quiet-pull >"$EVIDENCE/A-up.log" 2>&1
# «GitHub» для старого обновлятора — в сети проекта: адрес не зависит от платформы.
docker network connect --alias casefile-main "${P}_default" "$P-web"
latest_api=$(release_id casefile latest) latest_ui=$(release_id casefile-ui latest)
on_release "$latest_api" "$latest_ui" || fail "the old installation is not on latest"
api -X POST -H 'Content-Type: application/json' -d '{"key":"KEEP","title":"survives updates"}' \
  "http://127.0.0.1:$UI_PORT/api/v1/queues" >/dev/null
services | tee "$EVIDENCE/A-before.txt"

say "A. release 0.2.0 under stable; main gets the new compose file; Docker restarts"
publish 0.2.0 "" stable
cp "$ROOT/docker-compose.prod.yml" "$WEB/docker-compose.prod.yml"
r1_api=$(release_id casefile 0.2.0) r1_ui=$(release_id casefile-ui 0.2.0)
old_updater=$(dc ps -q updater)
docker restart $(dc ps -q) >/dev/null
# Лог прежнего обновлятора исчезает вместе с ним — сберечь последний снимок.
renewed() {
  docker logs -t "$old_updater" >"$WORK/old-updater.log" 2>&1 &&
    mv "$WORK/old-updater.log" "$EVIDENCE/A-old-updater.log"
  [ "$(docker inspect -f '{{index .Config.Labels "casefile.updater.revision"}}' "$(dc ps -q updater)" 2>/dev/null)" != "" ]
}
wait_for 300 renewed || fail "updater-renew did not replace the old updater"
wait_for 120 on_release "$r1_api" "$r1_ui" || fail "services did not move to 0.2.0"
services | tee "$EVIDENCE/A-after.txt"
dc logs --no-color updater-renew | tee "$EVIDENCE/A-renew.log"
note "A passed: the old installation is on stable 0.2.0 with the new updater"

# --- B. Новый выпуск без перезапуска Docker -----------------------------------------------

wait_for 120 more_checks "casefile-updater:" 0 || fail "the new updater logged nothing"
services >"$EVIDENCE/B-before.txt"
say "B. release 0.2.1 under stable, no Docker restart"
publish 0.2.1 "" stable
published=$(date -u +%s)
r2_api=$(release_id casefile 0.2.1) r2_ui=$(release_id casefile-ui 0.2.1)
wait_for 600 on_release "$r2_api" "$r2_ui" || fail "0.2.1 did not arrive"
note "running $(($(date -u +%s) - published))s after the push (interval $INTERVAL)"
services | tee "$EVIDENCE/B-after.txt"
api "http://127.0.0.1:$UI_PORT/api/v1/queues/KEEP" | tee "$EVIDENCE/B-data.json" | grep -q '"KEEP"' ||
  fail "the queue created before the updates is gone"
dc logs --no-color -t updater >"$EVIDENCE/B-updater.log"
note "B passed"

# --- C. Проверка без выпуска ---------------------------------------------------------------

say "C. a check without a new release"
services >"$EVIDENCE/C-before.txt"
seen=$(checks_logged "already up to date")
wait_for 300 more_checks "already up to date" "$seen" || fail "no idle check logged"
services >"$EVIDENCE/C-after.txt"
diff "$EVIDENCE/C-before.txt" "$EVIDENCE/C-after.txt" || fail "an idle check recreated a service"
dc logs --no-color -t updater >"$EVIDENCE/C-updater.log"
note "C passed: Created unchanged"

# --- D. Коммит main без тега ---------------------------------------------------------------

say "D. a new latest image and a new compose file in main, no tag"
{ cat "$ROOT/docker-compose.prod.yml"; echo "# a commit on main without a tag"; } >"$WORK/main.yml"
cp "$WORK/main.yml" "$WEB/docker-compose.prod.yml"
publish main-2 "$WORK/main.yml" latest
compose_before=$(shasum "$DIR/docker-compose.prod.yml" | cut -d' ' -f1)
services >"$EVIDENCE/D-before.txt"
seen=$(checks_logged "already up to date")
wait_for 300 more_checks "already up to date" "$seen" || fail "no check logged"
services >"$EVIDENCE/D-after.txt"
diff "$EVIDENCE/D-before.txt" "$EVIDENCE/D-after.txt" || fail "a main commit reached the installation"
[ "$(shasum "$DIR/docker-compose.prod.yml" | cut -d' ' -f1)" = "$compose_before" ] ||
  fail "the compose file changed"
dc logs --no-color -t updater >"$EVIDENCE/D-updater.log"
note "D passed"

# --- E. Закрепление и выключатель ----------------------------------------------------------

say "E. CASEFILE_VERSION=0.2.1 pinned, 0.2.2 under stable"
echo "CASEFILE_VERSION=0.2.1" >>"$DIR/.env"
publish 0.2.2 "" stable
services >"$EVIDENCE/E-pin-before.txt"
seen=$(checks_logged "already up to date")
wait_for 300 more_checks "already up to date" "$seen" || fail "no check logged"
services >"$EVIDENCE/E-pin-after.txt"
diff "$EVIDENCE/E-pin-before.txt" "$EVIDENCE/E-pin-after.txt" || fail "the pin did not hold"
dc logs --no-color -t updater >"$EVIDENCE/E-pin-updater.log"
note "E: the pin holds"

say "E. CASEFILE_AUTO_UPDATE=false, pin removed, Docker restarts"
sed -i.bak '/^CASEFILE_VERSION=/d' "$DIR/.env"
echo "CASEFILE_AUTO_UPDATE=false" >>"$DIR/.env"
dc up -d --no-deps updater >/dev/null 2>&1
docker restart $(dc ps -q) >/dev/null
off() { dc logs --no-color updater | grep -q "auto-update is off"; }
wait_for 60 off || fail "the updater did not report it is off"
sleep 90
on_release "$r2_api" "$r2_ui" || fail "the switched-off updater updated"
dc logs --no-color -t updater >"$EVIDENCE/E-off.log"
note "E: off holds"

say "E. auto-update back on"
sed -i.bak '/^CASEFILE_AUTO_UPDATE=/d' "$DIR/.env"
dc up -d --no-deps updater >/dev/null 2>&1
r3_api=$(release_id casefile 0.2.2) r3_ui=$(release_id casefile-ui 0.2.2)
wait_for 300 on_release "$r3_api" "$r3_ui" || fail "0.2.2 did not arrive once back on"
dc logs --no-color -t updater >"$EVIDENCE/E-on-updater.log"
note "E passed"

# --- F. Повторный запуск установщика --------------------------------------------------------

say "F. install.sh again, compose file from the release image"
rm "$DIR/docker-compose.prod.yml"
CASEFILE_DIR=$DIR sh "$ROOT/install.sh" </dev/null >"$EVIDENCE/F-install.txt" 2>&1 ||
  { cat "$EVIDENCE/F-install.txt"; fail "install.sh failed"; }
grep -q "Casefile is running." "$EVIDENCE/F-install.txt" || fail "no final message"
cmp -s "$DIR/docker-compose.prod.yml" "$ROOT/docker-compose.prod.yml" ||
  fail "install.sh did not take the compose file of the release"
sed -i.bak 's/Bearer [^"]*/Bearer <token>/' "$EVIDENCE/F-install.txt" && rm "$EVIDENCE/F-install.txt.bak"
note "F passed"

say "all phases passed"
