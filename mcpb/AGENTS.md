# mcpb

Исходники расширения чата Claude Desktop `casefile.mcpb` (формат MCPB): мост `mcp-remote` к MCP-серверу
Casefile, адрес установки спрашивает форма приложения (`user_config`), вход — OAuth моста, токена нет.
Архив собирает `scripts/build-mcpb.sh`, в GitHub Release его кладёт `.github/workflows/mcpb.yml`.

## Файлы
- `manifest.json` — манифест MCPB: `name` равно имени сервера `SERVER_NAME`, `version` — версии выпуска, сервер —
  мост с адресом из поля `casefile_url` и именем клиента OAuth «Claude Desktop»; сверяет `tests/test_mcpb_manifest.py`
- `package.json` — единственная зависимость `mcp-remote`, закреплённая точной версией
- `package-lock.json` — закреплённое дерево зависимостей моста; собирается `npm install --package-lock-only` в контейнере `node`
