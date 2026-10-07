#!/usr/bin/env bash
# Снимает архив демо-данных выпуска для `tests/test_release_archives.py` (TRK-653).
#
# Выпуск, сменивший схему базы, кладёт в `tests/data/` архив переноса, снятый на своём теге
# (решение проекта TRK#49): тест принимает каждый такой архив в head и сверяет, что ни одна
# строка не потерялась.
# Скрипт поднимает код тега с нуля так, как его поднимала установка того выпуска, заводит
# демо-данные и выгружает архив тем же `GET /api/v1/installation/archive`, что и человек.
#
#   scripts/snapshot-release-archive.sh <тег> [файл]
#
# Файл по умолчанию — `tests/data/archive-<тег>.json`. Рабочее дерево и ветка не меняются:
# дерево тега берётся `git archive` во временный каталог. Образ собирается из
# `docker/Dockerfile.dev` и `uv.lock` самого тега — код выпуска идёт на своих зависимостях.
#
# Окружение (всё необязательно):
#   SNAPSHOT_PROJECT  — проект compose, по умолчанию `casefile-snapshot-<версия>`;
#                       `tracker` и `casefile` запрещены — это установки владельца
#   SNAPSHOT_IMAGE    — имя образа тега, по умолчанию `casefile-snapshot:<версия>`;
#                       образ, который уже есть, не перезаписывается
#   POSTGRES_PORT, TRACKER_PORT, TRACKER_MCP_PORT — порты публикации, по умолчанию
#                       55491, 18491, 18591, чтобы не задеть установку и дев-контур
#
# База проекта поднимается с нуля: `docker compose down -v` своего проекта до подъёма и
# после выгрузки. Собранный образ и временный каталог удаляются на выходе.
set -euo pipefail

tag="${1:?usage: scripts/snapshot-release-archive.sh <tag> [file]}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="${2:-$root/tests/data/archive-$tag.json}"
version="${tag#v}"
project="${SNAPSHOT_PROJECT:-casefile-snapshot-${version//./-}}"
image="${SNAPSHOT_IMAGE:-casefile-snapshot:$version}"

case "$project" in
  tracker | casefile) echo "проект compose $project — установка владельца, возьмите другой" >&2; exit 2 ;;
esac
git -C "$root" rev-parse --verify --quiet "refs/tags/$tag" >/dev/null \
  || { echo "тега $tag нет" >&2; exit 2; }
command -v docker >/dev/null || { echo "нужен docker" >&2; exit 1; }
if docker image inspect "$image" >/dev/null 2>&1; then
  echo "образ $image уже есть; скрипт его не перезаписывает — задайте SNAPSHOT_IMAGE" >&2
  exit 2
fi

# Чужой контур не должен подмешаться: проект и файл compose задаются только здесь.
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
export POSTGRES_PORT="${POSTGRES_PORT:-55491}"
export TRACKER_PORT="${TRACKER_PORT:-18491}"
export TRACKER_MCP_PORT="${TRACKER_MCP_PORT:-18591}"

work="$(mktemp -d)"
built=""
dc() { docker compose -p "$project" --project-directory "$work" -f "$work/docker-compose.yml" "$@"; }
cleanup() {
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  if [ -n "$built" ]; then docker image rm "$image" >/dev/null 2>&1 || true; fi
  rm -rf "$work"
}
trap cleanup EXIT

git -C "$root" archive "$tag" | tar -x -C "$work"
# Все службы приложения дев-контура берут образ из одного якоря `x-app-service`.
if [ "$(grep -c '^  image: tracker-dev:latest$' "$work/docker-compose.yml")" != 1 ]; then
  echo "в docker-compose.yml тега $tag нет ровно одной строки 'image: tracker-dev:latest'" >&2
  exit 1
fi
sed -i.orig "s|^  image: tracker-dev:latest$|  image: $image|" "$work/docker-compose.yml"

dc down -v --remove-orphans
built=1
dc build api
dc up -d --wait db
dc run --rm migrate
dc run --rm init
dc run --rm local-token
dc run --rm agent-token
# Учебный проект `START` заводила установка v0.6.0–v0.8.x при подъёме (TRK-370).
if grep -q '^  tutorial:$' "$work/docker-compose.yml"; then dc run --rm tutorial; fi
dc run --rm demo
dc up -d --wait api

mkdir -p "$(dirname "$out")"
# По строке на строку таблицы: в диффе пересъёмки видно, какие строки поменялись.
dc exec -T api python - >"$out.part" <<'PY'
import json, urllib.request
from pathlib import Path

secret = Path(".secrets/ui-token").read_text().strip()
request = urllib.request.Request(
    "http://localhost:8000/api/v1/installation/archive",
    headers={"Authorization": f"Bearer {secret}"},
)
with urllib.request.urlopen(request) as response:
    data = json.load(response)["data"]

dump = lambda value: json.dumps(value, ensure_ascii=False)
head = [f" {dump(key)}: {dump(value)}" for key, value in data.items() if key != "tables"]
tables = []
for table in data["tables"]:
    rows = ",\n".join(f"    {dump(row)}" for row in table["rows"])
    tables.append(
        f'  {{"name": {dump(table["name"])}, "columns": {dump(table["columns"])}, "rows": [\n'
        + (rows + "\n" if rows else "")
        + "  ]}"
    )
text = "{\n" + ",\n".join([*head, ' "tables": [\n' + ",\n".join(tables) + "\n ]"]) + "\n}\n"
assert json.loads(text) == data
print(text, end="")
PY
mv "$out.part" "$out"

python_summary='import json, sys
data = json.load(open(sys.argv[1]))
print("schema_revision", data["schema_revision"], "app_version", data["app_version"])
print({t["name"]: len(t["rows"]) for t in data["tables"]})'
dc exec -T api python -c "$python_summary" /dev/stdin <"$out"
echo "архив $tag: $out"
