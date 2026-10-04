# mcpb

Расширение чата Claude Desktop `casefile.mcpb` (формат MCPB, https://github.com/modelcontextprotocol/mcpb):
то, через что десктоп-приложение Claude получает Casefile, раз плагин Claude Code его чат не
грузит (TRK-514). Внутри архива — мост `mcp-remote` к MCP-серверу Casefile; Claude Desktop
запускает его своей встроенной средой Node, адрес установки спрашивает форма приложения
(`user_config`), вход — OAuth моста, токена в расширении нет. В git лежат только исходники:
архив собирает `scripts/build-mcpb.sh` (в `dist/`, вне git), а в GitHub Release его кладёт
`.github/workflows/mcpb.yml`. Установщики скачивают его оттуда и открывают.

## Файлы
- `manifest.json` — манифест MCPB 0.3: `name` равно `serverInfo.name` сервера (`SERVER_NAME` в `app/mcp/server.py`; иначе Desktop не отдаёт чату инструменты, решение TRK-514#20), на экранах — `display_name` «Casefile»; `version` равна версии выпуска; сервер — `node_modules/mcp-remote/dist/proxy.js` с адресом из поля `casefile_url` (по умолчанию `http://127.0.0.1:8100/mcp`) и именем клиента OAuth «Claude Desktop»
- `package.json` — единственная зависимость `mcp-remote`, закреплённая точной версией
- `package-lock.json` — закреплённое дерево зависимостей моста; правится `npm install --package-lock-only` в контейнере `node`, не руками
