#!/usr/bin/env bash
# Собирает ZIP плагина casefile (только скил) для загрузки на platform.openai.com/plugins (TRK-461).
#
# В архив идёт ровно то, что плагину нужно: `.codex-plugin/` (манифест и иконка), `skills/`
# и `LICENSE`. `.claude-plugin/`, бэкенд и интерфейс в него не попадают. Подачу команда не
# делает: архив кладётся в каталог, названный первым аргументом (по умолчанию `dist/`),
# а загрузка — отдельная задача по слову владельца.
#
#   scripts/build-openai-plugin.sh [каталог-назначения]
#
# Печатает путь к архиву. Падает, если версия в манифесте не равна версии выпуска из
# `pyproject.toml`, если нет файла, на который ссылается манифест, или иконка больше 5 МиБ.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$root/dist}"
manifest="$root/.codex-plugin/plugin.json"

command -v zip >/dev/null || { echo "нужен zip" >&2; exit 1; }
command -v python3 >/dev/null || { echo "нужен python3 (только разобрать JSON)" >&2; exit 1; }

read -r name version icons < <(python3 - "$manifest" "$root/pyproject.toml" <<'PY'
import json, re, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
release = re.search(r'^version\s*=\s*"([^"]+)"', open(sys.argv[2], encoding="utf-8").read(), re.M).group(1)
if m["version"] != release:
    sys.exit(f"версия манифеста {m['version']} не равна версии выпуска {release}")
i = m.get("interface", {})
icons = [i[k] for k in ("logo", "composerIcon") if k in i]
print(m["name"], m["version"], ",".join(icons))
PY
)

for icon in ${icons//,/ }; do
  path="$root/${icon#./}"
  [ -f "$path" ] || { echo "нет иконки $icon" >&2; exit 1; }
  [ "$(wc -c <"$path")" -le 5242880 ] || { echo "иконка $icon больше 5 МиБ" >&2; exit 1; }
done

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/.codex-plugin" "$out_dir"
cp "$root"/.codex-plugin/plugin.json "$root"/.codex-plugin/*.svg "$stage/.codex-plugin/"
cp -R "$root/skills" "$stage/skills"
cp "$root/LICENSE" "$stage/LICENSE"

zip_path="$(cd "$out_dir" && pwd)/$name-$version.zip"
rm -f "$zip_path"
(cd "$stage" && zip -X -q -r "$zip_path" .codex-plugin skills LICENSE -x "skills/AGENTS.md")
echo "$zip_path"
