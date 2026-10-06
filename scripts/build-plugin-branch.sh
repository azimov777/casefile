#!/usr/bin/env bash
# Собирает дерево узкой ветки `plugin`: только файлы плагина casefile (TRK-478).
#
# Портал Anthropic смотрит на «отслеживаемую ветку» и сканирует всё её дерево: пределы
# 512 файлов и 256 КиБ на файл не-картинки (TRK-457#6). Весь репозиторий в них не входит,
# а плагину нужны только `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, `gemini-extension.json` (расширение
# Gemini CLI, TRK-497), `mcp.json` (коннектор по стандарту Open Plugins, TRK-584), `skills/` (без своей карты `AGENTS.md`), `LICENSE` и `README.md`. Ту же сборку берёт шаг конвейера выпуска
# (`.github/workflows/images.yml`, джоб `channel`) и человек для проверки.
#
#   scripts/build-plugin-branch.sh [--commit ТЕГ [--parent REF]] КАТАЛОГ
#
# Кладёт дерево в КАТАЛОГ (создаёт или очищает) и печатает число файлов. С `--commit`
# дополнительно создаёт в репозитории скрипта коммит с этим деревом, родитель — `--parent`
# (без него — корневой коммит), и печатает его хеш последней строкой; коммит не создаётся
# и печатается хеш родителя, если дерево родителя то же. Ветку и пуш скрипт не трогает.
# Падает, если версия плагина не равна версии выпуска из `pyproject.toml`, нет файла
# плагина, файлов 512 и больше или файл не-картинки больше 256 КиБ.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tag="" parent=""
while [ $# -gt 1 ]; do
  case "$1" in
    --commit) tag="${2:?нужен тег}"; shift 2 ;;
    --parent) parent="${2:?нужен ref}"; shift 2 ;;
    *) echo "неизвестный аргумент $1" >&2; exit 2 ;;
  esac
done
dest="${1:?нужен каталог назначения}"

command -v python3 >/dev/null || { echo "нужен python3 (только разобрать JSON)" >&2; exit 1; }
python3 - "$root" <<'PY'
import json, re, sys
root = sys.argv[1]
release = re.search(r'^version\s*=\s*"([^"]+)"', open(f"{root}/pyproject.toml", encoding="utf-8").read(), re.M).group(1)
for path in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", ".cursor-plugin/plugin.json", "gemini-extension.json"):
    version = json.load(open(f"{root}/{path}", encoding="utf-8"))["version"]
    if version != release:
        sys.exit(f"версия плагина {version} ({path}) не равна версии выпуска {release}")
PY

for path in .claude-plugin/plugin.json .codex-plugin/plugin.json .cursor-plugin/plugin.json gemini-extension.json mcp.json skills/casefile/SKILL.md LICENSE README.md; do
  [ -f "$root/$path" ] || { echo "нет файла $path" >&2; exit 1; }
done

rm -rf "$dest"
mkdir -p "$dest"
dest="$(cd "$dest" && pwd)"
cp -R "$root/.claude-plugin" "$root/.codex-plugin" "$root/.cursor-plugin" "$root/skills" "$dest/"
cp "$root/LICENSE" "$root/README.md" "$root/gemini-extension.json" "$root/mcp.json" "$dest/"
rm -f "$dest/skills/AGENTS.md"

count=$(find "$dest" -type f | wc -l | tr -d ' ')
[ "$count" -lt 512 ] || { echo "файлов $count: предел портала 512" >&2; exit 1; }
big=$(find "$dest" -type f -size +256k ! \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \
  -o -iname '*.gif' -o -iname '*.svg' -o -iname '*.webp' -o -iname '*.ico' \))
[ -z "$big" ] || { echo "файл не-картинки больше 256 КиБ: $big" >&2; exit 1; }
echo "files: $count"

[ -n "$tag" ] || exit 0
index="$(mktemp)"
trap 'rm -f "$index"' EXIT
rm -f "$index"
export GIT_INDEX_FILE="$index"
git -C "$root" --work-tree="$dest" add -A -f .
tree=$(git -C "$root" write-tree)
args=()
if [ -n "$parent" ]; then
  if [ "$(git -C "$root" rev-parse "$parent^{tree}")" = "$tree" ]; then
    git -C "$root" rev-parse "$parent^{commit}"
    exit 0
  fi
  args=(-p "$parent")
fi
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-github-actions[bot]}" \
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-github-actions[bot]}" \
GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-41898282+github-actions[bot]@users.noreply.github.com}" \
  git -C "$root" commit-tree "$tree" ${args[@]+"${args[@]}"} -m "release $tag: plugin files"
