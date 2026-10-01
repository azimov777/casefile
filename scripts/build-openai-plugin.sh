#!/usr/bin/env bash
# Собирает ZIP плагина casefile (только скил) для загрузки на platform.openai.com/plugins (TRK-461).
#
# В архив идёт ровно то, что плагину нужно: `.codex-plugin/` (манифест и иконка), `skills/`
# и `LICENSE`. Манифест в архиве без `mcpServers` и без `mcp.json` рядом: заявка идёт как
# плагин только со скилом, без MCP-ревью (TRK-503); в репозитории манифест остаётся с
# коннектором, правится только копия в архиве. Описания в копии не говорят про коннектор. `.claude-plugin/`, бэкенд и интерфейс в него не попадают. Подачу команда не
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
cp "$root"/.codex-plugin/*.svg "$stage/.codex-plugin/"
python3 - "$manifest" "$stage/.codex-plugin/plugin.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
m.pop("mcpServers", None)
m["keywords"] = [k for k in m.get("keywords", []) if k != "mcp"]
m["description"] = (
    "Casefile for agents: the skill for working a task through the Casefile MCP server "
    "(take it, keep its case, ask the human, hand it off, close it with verdicts)."
)
i = m["interface"]
text = i["longDescription"]
cut = text.index(" The connector points at")
i["longDescription"] = (
    text[:cut]
    .replace("This plugin carries the Casefile skill and the Casefile MCP connector.", "This plugin carries the Casefile skill.")
)
for k in ("websiteURL", "privacyPolicyURL", "termsOfServiceURL"):
    if not i.get(k, "").startswith("https://"):
        sys.exit(f"в interface нет https-адреса {k}")
json.dump(m, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
cp -R "$root/skills" "$stage/skills"
cp "$root/LICENSE" "$stage/LICENSE"

zip_path="$(cd "$out_dir" && pwd)/$name-$version.zip"
rm -f "$zip_path"
(cd "$stage" && zip -X -q -r "$zip_path" .codex-plugin skills LICENSE -x "skills/AGENTS.md")
echo "$zip_path"
