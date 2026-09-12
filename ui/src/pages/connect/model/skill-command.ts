/**
 * Команда установки скила дисциплины файлом: `skill/tracker-agent/SKILL.md` есть у
 * сервиса `mcp` и в образе установки (`docker/Dockerfile.prod`), и в контуре
 * разработки, где репозиторий смонтирован. Ссылка на GitHub из `docs/agent-install.md`
 * верна только для опубликованного репозитория, а экран обязан работать на любой
 * установке.
 *
 * Оболочку экран не угадывает: bash/zsh и PowerShell — разные строки, показанные
 * подряд, той же дисциплиной, что переменная токена Codex (`UI-114`, решение
 * UI-114#5; здесь — разбор `UI-118`).
 *
 * Расхождение с bash/zsh не в одном знаке — PowerShell-строка не получена заменой
 * символов в общей заготовке, а собрана заново под три находки `UI-118`:
 *
 * 1. `&&` — оператор цепочки пайплайнов, появился только в PowerShell 7
 *    (`about_Pipeline_Chain_Operators`: «Beginning in PowerShell 7, PowerShell
 *    implements the && and || operators»). В Windows PowerShell 5.1, которую тоже
 *    ставит `install.ps1` (`docs/CONVENTIONS.md` корня), это `ParserError` —
 *    «The token '&&' is not a valid statement separator in this version» — и
 *    команда не выполняется вовсе, до всякого `mkdir`. Замена — `;`.
 * 2. `mkdir -p` в PowerShell не ломается, но и не значит «parents»: `mkdir` там —
 *    функция-обёртка над `New-Item -Type Directory` (исходник движка PowerShell,
 *    `InitialSessionState.cs`, `GetMkdirFunctionText`), и её параметры — `Path`,
 *    `Name`, `Value`, `Force`, `Credential`. Из них на «p» начинается только
 *    `Path`, и PowerShell резолвит `-p` в него сокращением имени (`about_Parameters`
 *    про однозначные сокращения имён параметров) — значение после `-p` становится
 *    путём, а не флагом. `New-Item -Path <вложенный путь> -ItemType Directory`
 *    создаёт недостающие промежуточные каталоги и без `-Force` (документация
 *    `New-Item`), так что результат совпадает с bash — но случайно, а не потому что
 *    PowerShell знает такой флаг: без `-Force` повторный запуск на существующем
 *    каталоге кончится ошибкой «already exists», которой у идемпотентного
 *    `mkdir -p` не бывает. Explicit `-Force` в PowerShell-строке даёт то же самое,
 *    что бы ни значило совпадение по случаю: недостающие каталоги и никакой ошибки
 *    на существующем.
 *
 *    Этим же объясняется, почему прежний способ проверки PowerShell в контейнере
 *    (`docs/notes/docker.md`, `mcr.microsoft.com/powershell`) здесь не годится:
 *    функция `mkdir` в PowerShell собрана только для Windows (`#if !UNIX` вокруг её
 *    регистрации в том же исходнике движка, с комментарием «we remove mkdir on
 *    Linux because of a conflict») — в Linux-контейнере имя `mkdir` резолвится в
 *    настоящий `/usr/bin/mkdir`, и поведение функции PowerShell там не проверить
 *    вовсе, что бы она ни делала.
 * 3. Запись файла: `>` в Windows PowerShell 5.1 — это `Out-File` с кодировкой по
 *    умолчанию `Unicode` (UTF-16LE); `Set-Content -Encoding utf8` там же кладёт
 *    BOM в начало файла (`about_Character_Encoding`: «Using any Unicode encoding,
 *    except UTF7, always creates a BOM» и явно про `UTF8` пятой версии — «Uses
 *    UTF-8 (with BOM)»). Тот же класс поломки уже нашёлся в этом репозитории у
 *    `.env` в `install.ps1`: `Set-Content -Encoding UTF8` в PowerShell 5.1 ставит
 *    BOM перед первой переменной, и compose читает её с невидимым символом в
 *    имени — почему там применён `[System.IO.File]::WriteAllLines` без BOM.
 *    Скил — тоже текст, который разбирает не PowerShell, а харнесс агента: BOM
 *    перед `---` фронтматтера сломал бы разбор так же тихо. Пишем тем же приёмом
 *    проекта — `[System.IO.File]::WriteAllText` с `UTF8Encoding($false)`.
 *
 *    Байты `cat` при этом идут через конвейер PowerShell, а не пишутся в файл
 *    напрямую, и PowerShell декодирует вывод внешней команды кодировкой
 *    `[Console]::OutputEncoding` — по умолчанию в Windows PowerShell 5.1 это
 *    кодовая страница системы, не UTF-8 (`about_Character_Encoding`, раздел про
 *    `$OutputEncoding`: «affects the encoding PowerShell uses to communicate with
 *    external programs»; кодовая страница по умолчанию, а не UTF-8, подтверждена
 *    независимо разбором той же поломки для других программ). Скил — сплошь
 *    русский текст: без явного `[Console]::OutputEncoding =
 *    [System.Text.Encoding]::UTF8` до вызова `docker` строки декодировались бы
 *    уже испорченными, и никакой выбор кодировки записи это не исправил бы задним
 *    числом.
 *
 * Источники проверены по документации Microsoft и исходнику движка PowerShell, а
 * не в Linux-контейнере (находка выше, пункт 2) и не на настоящем Windows — на
 * момент разбора он не запрошен ни у кого (`TRK-63`, открытый вопрос).
 */

const SKILL_SOURCE_PATH = 'skill/tracker-agent/SKILL.md';
const TARGET_DIR = '~/.claude/skills/tracker-agent';
const TARGET_FILE = `${TARGET_DIR}/SKILL.md`;

export const SKILL_COMMAND = {
  bashZsh: `mkdir -p ${TARGET_DIR} && docker compose exec -T mcp cat ${SKILL_SOURCE_PATH} > ${TARGET_FILE}`,

  powerShell:
    '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; ' +
    'New-Item -ItemType Directory -Force -Path "$HOME\\.claude\\skills\\tracker-agent" | Out-Null; ' +
    '[System.IO.File]::WriteAllText("$HOME\\.claude\\skills\\tracker-agent\\SKILL.md", ' +
    `((docker compose exec -T mcp cat ${SKILL_SOURCE_PATH}) -join "\`n") + "\`n", ` +
    '[System.Text.UTF8Encoding]::new($false))',
} as const;
