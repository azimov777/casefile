#!/usr/bin/env bash
# Собирает расширение Claude Desktop `casefile.mcpb` (формат MCPB) из `mcpb/` (TRK-514).
#
# Внутри архива — манифест, иконка плагина, `LICENSE` и мост `mcp-remote` с зависимостями
# по `mcpb/package-lock.json`: Claude Desktop запускает его своей встроенной средой Node,
# и Node.js у человека не нужен. Токена в архиве нет — адрес спрашивает форма Desktop
# (`user_config`), вход OAuth ведёт `mcp-remote`. Сборка идёт в контейнере `node`
# (`npm ci` и проверка манифеста `mcpb validate`, упаковка `mcpb pack` закреплённой версии):
# на хосте нужны только Docker и python3. Имя файла без версии — так у выпуска GitHub
# есть постоянный адрес `releases/latest/download/casefile.mcpb`, который качают установщики.
#
#   scripts/build-mcpb.sh [каталог-назначения]
#
# Печатает путь к архиву и его размер. Падает, если версия манифеста не равна версии выпуска
# из `pyproject.toml`, если `mcp-remote` в `package.json` не закреплён точной версией, равной
# версии в lock-файле, или если в архиве нет манифеста или моста. Архив кладётся в каталог,
# названный первым аргументом (по умолчанию `dist/`, вне git); в выпуск его кладёт конвейер
# `.github/workflows/mcpb.yml`.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$root/dist}"
src="$root/mcpb"
node_image="${CASEFILE_NODE_IMAGE:-node:24-alpine}"
mcpb_cli="@anthropic-ai/mcpb@2.1.2"
bridge="node_modules/mcp-remote/dist/proxy.js"

command -v python3 >/dev/null || { echo "нужен python3 (только разобрать JSON)" >&2; exit 1; }

# Сверка до Docker: расхождение версий называется сразу, без контейнера и сети.
python3 - "$src" "$root/pyproject.toml" "$bridge" <<'PY'
import json, re, sys
from pathlib import Path
src, pyproject, bridge = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
release = re.search(r'^version\s*=\s*"([^"]+)"', open(pyproject, encoding="utf-8").read(), re.M).group(1)
if manifest["version"] != release:
    sys.exit(f"версия манифеста {manifest['version']} не равна версии выпуска {release}")
if manifest["server"]["entry_point"] != bridge:
    sys.exit(f"entry_point манифеста не {bridge}")
pinned = json.loads((src / "package.json").read_text(encoding="utf-8"))["dependencies"]["mcp-remote"]
locked = json.loads((src / "package-lock.json").read_text(encoding="utf-8"))["packages"]["node_modules/mcp-remote"]["version"]
if pinned != locked:
    sys.exit(f"mcp-remote в package.json ({pinned}) не равен lock-файлу ({locked}): закрепите точную версию")
PY

command -v docker >/dev/null || { echo "нужен docker" >&2; exit 1; }

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/src" "$stage/out" "$out_dir"
cp "$src/manifest.json" "$src/package.json" "$src/package-lock.json" "$stage/src/"
cp "$root/.claude-plugin/icon.png" "$stage/src/icon.png"
cp "$root/LICENSE" "$stage/src/LICENSE"

# Под uid хоста: файлы в смонтированных каталогах остаются своими и удаляются ловушкой.
# Кеш npm — во временном HOME контейнера, на хост он не попадает.
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$stage/src:/w" -v "$stage/out:/out" -w /w "$node_image" sh -c "
    npm ci --omit=dev --ignore-scripts --no-audit --no-fund --loglevel=error &&
    npx --yes $mcpb_cli validate manifest.json &&
    npx --yes $mcpb_cli pack . /out/casefile.mcpb" </dev/null >&2

python3 - "$stage/out/casefile.mcpb" "$bridge" <<'PY'
import sys, zipfile
names = set(zipfile.ZipFile(sys.argv[1]).namelist())
for need in ("manifest.json", "icon.png", sys.argv[2]):
    if need not in names:
        sys.exit(f"в архиве нет {need}")
PY

mcpb_path="$(cd "$out_dir" && pwd)/casefile.mcpb"
mv "$stage/out/casefile.mcpb" "$mcpb_path"
echo "$(wc -c <"$mcpb_path" | tr -d ' ') bytes" >&2
echo "$mcpb_path"
