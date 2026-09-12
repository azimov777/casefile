# Подключение агента: чужие клиенты MCP

Что выяснено о клиентах, под которые экран «Подключить агента» собирает фрагменты
(`src/features/connect-agent`). Ключи и флаги сверены по документации клиентов и их
справке — источники в деле `UI-105#14`; сюда попадает то, что из документации не видно.

## Заголовки у `claude mcp add` ставятся после имени и адреса

**Что:** флаг `-H, --header <header...>` у `claude mcp add` вариадический (справка
`claude mcp add --help`, Claude Code 2.1.268): значений у него сколько угодно, и всё,
что идёт следом до следующего флага, он считает заголовками. Повторять `--header`
можно, но только после позиционных аргументов — имени сервера и адреса.
**Почему важно:** команда с заголовками впереди выглядит правильной, а имя и адрес
в ней уезжают в заголовки, и сервер не заводится: `claude mcp add --transport http
--scope user --header "X-Probe: 1" probe <адрес>` отвечает `error: missing required
argument 'name'` (проверено 2026-09-11, UI-105#17).
**Как правильно:** флаги с одним значением впереди, заголовки последними:
`claude mcp add --transport http --scope user casefile "<адрес>" --header "Authorization: Bearer …"`.
**Где:** `src/features/connect-agent/model/snippets.ts`, `claudeCodeCommand`.

## Codex берёт токен из окружения своего процесса, и список серверов этого не проверяет

**Что:** `bearer_token_env_var` в `~/.codex/config.toml` — имя переменной, которую Codex
читает из собственного окружения при подключении; ключа для токена строкой документация
Codex не знает. `codex mcp list` и `codex mcp get` показывают «Bearer token» и тогда,
когда переменной в окружении процесса нет (openai/codex#30125), а приложение Codex видит
смену переменных только после перезапуска. Флага для заголовков у `codex mcp add` нет:
`X-Actor-Label` ставится файлом (`http_headers`) или формой.
**Почему важно:** «сервер в списке» не значит «подключён»: без переменной запрос уходит
без `Authorization`, и MCP отвечает отказом. Вывод по списку выдал бы нерабочий фрагмент
за проверенный.
**Как правильно:** проверять подключение вызовом инструмента (`/mcp` в Codex), а не
списком; переменную задавать там, откуда Codex запускается. Без входа в Codex и без
модели фрагмент проверяется его сервером приложения: `codex app-server` на stdio,
`initialize`, затем `mcpServerStatus/list` с `detail: full` — ответ несёт
`serverInfo` сервера и его инструменты, а при неверном токене `serverInfo: null` и ни
одного инструмента (UI-105#17). Изолированный `CODEX_HOME` не трогает конфигурацию
человека.
**Где:** `src/features/connect-agent/model/snippets.ts`, `TOKEN_ENV`.

## Переменная окружения Codex — две строки, а не одна: экранирование PowerShell не то же, что у bash/zsh

**Что:** `export CASEFILE_TOKEN=…` — синтаксис bash/zsh; вставленный в PowerShell как есть,
он падает (`Object reference not set to an instance of an object.`, `pwsh -Command 'export
CASEFILE_TOKEN="abc"'`) — `export` там не команда. Верная форма — `$env:CASEFILE_TOKEN =
"<значение>"`, а экранирование внутри двойных кавычек у PowerShell своё: экранирующий знак
не обратный слеш, а обратная кавычка ``(`)``, и экранировать нужно её саму, `$` (иначе
начинает подстановку переменной или `$(...)`) и закрывающую кавычку; обратный слеш не
особый знак и не трогается — в отличие от `shellQuote` для bash/zsh, где спецзнаков четыре.
Проверено round-trip в `mcr.microsoft.com/powershell` (pwsh 7.4.2, приём как в TRK-58):
для строк со всеми четырьмя знаками разом, включая `$(rm -rf ~)`, значение `$env:VAR`
после подстановки совпало с исходной строкой посимвольно.
**Почему важно:** Casefile ставится и на Windows (`install.ps1`), и одна строка `export`
на экране не работает там вовсе — не «работает иначе», а не выполняется как команда.
Своя функция экранирования обязательна: применить `shellQuote` к значению для PowerShell
дало бы неверный результат — обратный слеш там ничего не значит, а `` ` `` и `$` заново
раскрылись бы, будучи не экранированы.
**Как правильно:** `connectionSnippets()` отдаёт `codexEnv` объектом `{ bashZsh,
powerShell }`, экран показывает обе строки подряд, не выбирая по `navigator.userAgent`
(`UI-114`, решение UI-114#5) — угадать оболочку по нему нельзя надёжно, а ошибка обошлась
бы тем, что копия строки не сработает молча.
**Где:** `src/features/connect-agent/model/snippets.ts`, `powerShellQuote`, `codexEnv`.

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

## Команда установки скила: `&&` ломается в Windows PowerShell 5.1, `mkdir -p` — нет, но случайно

**Что:** три отдельные находки `UI-118` про `mkdir -p ~/.claude/skills/tracker-agent &&
docker compose exec -T mcp cat skill/tracker-agent/SKILL.md > ~/.claude/skills/tracker-agent/SKILL.md`.

Первая: `&&` как оператор цепочки пайплайнов появился только в PowerShell 7
(`about_Pipeline_Chain_Operators`: «Beginning in PowerShell 7, PowerShell implements the
&& and || operators»). В Windows PowerShell 5.1 это `ParserError` — «The token '&&' is
not a valid statement separator in this version» — и команда не выполняется вовсе, до
всякого `mkdir` (воспроизведено многократно в чужих отчётах об этой самой ошибке, не
только в документации).

Вторая: `mkdir -p` в PowerShell не ломается — но не потому что там знают флаг `-p`.
`mkdir` там — функция-обёртка над `New-Item -Type Directory` (исходник движка
PowerShell, `src/System.Management.Automation/engine/InitialSessionState.cs`,
`GetMkdirFunctionText`), и её параметры — `Path`, `Name`, `Value`, `Force`,
`Credential`. Из них на «p» начинается только `Path`, и PowerShell резолвит `-p` в
него сокращением имени (правило об однозначных сокращениях параметров, `about_Parameters`
/ `about_Command_Syntax`) — значение после `-p` становится путём, а не флагом. А
`New-Item -ItemType Directory -Path <вложенный путь>` создаёт недостающие промежуточные
каталоги и без `-Force` (документация `New-Item`), так что результат случайно совпадает
с bash. Без `-Force` повторный запуск на уже существующем каталоге кончится не тишиной,
а ошибкой «already exists» — тем, чего у идемпотентного `mkdir -p` не бывает.

Тем же исходником объясняется, почему приём проверки PowerShell в Linux-контейнере
(запись выше в `../docs/notes/docker.md` — здесь нужный пример: `mkdir` собран условием
`#if !UNIX` с комментарием «we remove mkdir on Linux because of a conflict») здесь не
годится вовсе: в Linux-сборке PowerShell функции `mkdir` нет, и имя резолвится в
настоящий `/usr/bin/mkdir` — поведение функции там не проверить, что бы она ни делала.

Третья: запись файла. `>` в Windows PowerShell 5.1 — это `Out-File` с кодировкой по
умолчанию `Unicode` (UTF-16LE); `Set-Content -Encoding utf8` там же кладёт BOM в начало
файла (`about_Character_Encoding`: «Using any Unicode encoding, except UTF7, always
creates a BOM», и для `UTF8` пятой версии явно — «Uses UTF-8 (with BOM)»). Тот же класс
поломки уже нашёлся в этом репозитории у `.env` в `install.ps1` — комментарий рядом с
`[System.IO.File]::WriteAllLines` там же объясняет, что `Set-Content -Encoding UTF8`
поставил бы BOM перед первой переменной. Скил — тоже текст с фронтматтером, и невидимый
BOM перед `---` сломал бы его чтение так же тихо.

Довеском к третьей — байты `cat`, прежде чем лечь в файл, идут через конвейер
PowerShell, а PowerShell декодирует вывод внешней команды кодировкой
`[Console]::OutputEncoding` — по умолчанию в Windows PowerShell 5.1 это кодовая
страница системы, не UTF-8 (`about_Character_Encoding`, раздел про `$OutputEncoding`).
Скил (`../skill/tracker-agent/SKILL.md`) — сплошь русский текст: без явного `[Console]::OutputEncoding =
[System.Text.Encoding]::UTF8` до вызова `docker` строки декодировались бы уже
испорченными, и никакой выбор кодировки записи это не исправил бы задним числом.

**Почему важно:** первая находка одна ломает всю строку на Windows PowerShell 5.1,
которую тоже ставит `install.ps1` (`docs/CONVENTIONS.md` корня, «PowerShell 5.1 и 7»).
Вторая — предупреждение не полагаться на случайное совпадение поведения флага:
следующая похожая команда с `-p` может напороться на параметр, чьё сокращение решит
иначе. Третья и четвёртая — та же ловушка, что уже стоила времени у `.env`
(`install.ps1`), только тише: скил читает не PowerShell, а харнесс агента, и оба вида
порчи (BOM, неверная кодировка входа) молчаливы — файл существует, весит разумно и
не считается сломанным ничем в самом PowerShell.

**Как правильно:** для PowerShell — не одна строка на два языка, а собственная,
построенная заново: `;` вместо `&&`; `New-Item -ItemType Directory -Force -Path`
вместо `mkdir -p`; `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` до
вызова `docker`; `[System.IO.File]::WriteAllText` с `UTF8Encoding($false)` вместо `>`
или `Set-Content -Encoding utf8`. Проверять `&&`/`mkdir` в Windows PowerShell 5.1 —
по документации Microsoft и исходнику движка PowerShell (или на настоящем Windows,
когда он появится — `TRK-63`), а не в Linux-контейнере с pwsh.

**Где:** `src/pages/connect/model/skill-command.ts`, `SKILL_COMMAND`;
`install.ps1`, комментарий у `[System.IO.File]::WriteAllLines` (тот же приём против BOM).
