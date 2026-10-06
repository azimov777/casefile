# Подключение агента: чужие клиенты MCP

Что выяснено о клиентах, под которые экран «Подключить агента» собирает фрагменты
(`src/features/connect-agent`). Ключи и флаги сверены по документации клиентов и их
справке — источники в деле `UI-105#14`; сюда попадает то, что из документации не видно.

## Единой формы JSON `mcpServers` у клиентов нет

**Что:** корневой ключ `mcpServers` у клиентов общий, а поля сервера — нет: Claude Code
(`.mcp.json`) ждёт `type`, `url` и `headers`; Cursor — `url` и `headers`, без `type`
в примере документации; Windsurf — `serverUrl`; Gemini CLI — `httpUrl` для потокового
HTTP (`url` у него значит SSE); VS Code — корень `servers`, а не `mcpServers`.
**Почему важно:** фрагмент, подписанный «для любого клиента», у половины клиентов
молча не заведёт сервер.
**Как правильно:** фрагмент — форма `.mcp.json` Claude Code, и объяснение рядом называет,
у каких клиентов поля совпадают, а у каких нет; новый клиент в этот список добавляется
по его документации, а не по сходству.
**Где:** `src/features/connect-agent/model/snippets.ts`, `connectionSnippets`;
`src/shared/i18n/dictionaries/en/ui.ts`, `jsonHint`.

## Claude Code и Codex на экране подключаются плагином и входом OAuth, ключа во фрагментах у них нет

**Что:** с TRK-479 вкладки «Claude Code» и «Codex» печатают команды установщика (корневой скрипт
установки, TRK-452#18): маркетплейс, `claude plugin install … --config "casefile_url=<адрес>"`,
`claude mcp login plugin:casefile:casefile`; у Codex — маркетплейс `--ref plugin` (ветка с одними
файлами плагина, TRK-494), `codex plugin add casefile@casefile`, `codex mcp login casefile`
и, если адрес не `127.0.0.1:8100` (`localhost` — тот же), две строки `[mcp_servers.casefile] url=`
для `config.toml`. Фрагментов с `Authorization`, переменной окружения с токеном и формой Codex с
ключом на этих вкладках больше нет; ключ остался во вкладках «JSON mcpServers» и «Любой клиент
MCP» (Hermes, Cursor, сторож журнала). Команды `claude mcp add` с заголовком, переменной окружения
Codex и скила под PowerShell на экране больше нет; их уроки о чужих клиентах верны и для живого кода:
у `claude mcp add` флаг `--header` вариадический — заголовки ставят последними, после имени и адреса,
иначе они съедают имя (`scripts/check-skill-install.sh`, `README.md`); `codex mcp list` показывает
«Bearer token» и без переменной окружения в процессе Codex, поэтому подключение проверяют вызовом
инструмента (`/mcp`) или сервером приложения Codex (`../docs/notes/mcp.md`), а не списком; строка для
Windows PowerShell 5.1 пишется заново, а не берётся от bash: вместо `&&` стоит `;` (оператор цепочки
появился только в PowerShell 7), в одинарных кавычках особая одна `'` и удваивается, `>` и
`Set-Content -Encoding utf8` кладут UTF-16 или BOM, поэтому файл пишут `WriteAllLines`/`WriteAllText`
с `UTF8Encoding($false)` — живое место на экране `machine.powerShell` и в `../install.ps1`.

**Почему важно:** Codex находит подключение плагина только в файле mcp.json папки плагина Codex
(TRK-451#13): ветка `plugin` её несёт, а со `stable` нужен был `--sparse .codex-plugin`, который к
тому же не отсекал файлы корня репозитория (TRK-494). Служба отдаёт вход OAuth только по https (по
http — на своей машине), поэтому для адреса `http://<IP>` экран предупреждает, что плагин не
подключится, вместо молчаливой нерабочей команды.

**Как правильно:** команды плагина сверять с установщиком дословно — это делает
`snippets.test.ts`; менять строки на экране и в установщике вместе.

**Где:** `src/features/connect-agent/model/snippets.ts` (`claudePlugin`, `codexPlugin`,
`codexUrlFile`, `oauthAvailable`), `e2e/connect.spec.ts`, `e2e/access.spec.ts`; `../install.ps1`.
