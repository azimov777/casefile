# Casefile installer for Windows (PowerShell 5.1 and 7):
#
#   irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
#
# Близнец `install.sh`: те же шаги в том же порядке — кладёт `docker-compose.prod.yml` в
# каталог установки (`%USERPROFILE%\casefile`), поднимает контур и печатает, куда открыть
# интерфейс и чем подключить агента. Повторный запуск — это обновление.
#
# Compose-файл, как и в `install.sh`, берётся из образа выпуска (канал `stable`), а не с main.
#
# Переменные (все необязательны):
#   CASEFILE_DIR       каталог установки
#   CASEFILE_REGISTRY  реестр образов, по умолчанию ghcr.io/azimov777
#   CASEFILE_VERSION   выпуск: канал `stable` (по умолчанию) или номер вида 0.2.0
# Обе последние, а также CASEFILE_PORT, TRACKER_MCP_PORT и COMPOSE_PROJECT_NAME (если заданы)
# записываются в `.env` новой установки; без них действует `.env`
# существующей установки, а без него — умолчания compose-файла.
#   CASEFILE_SKILL     0 — не ставить скил агентам этой машины; 1, названная явно, — «да» заранее,
#                      без вопроса. Без неё в интерактивном окне перед шагом печатается список
#                      файлов чужих программ, которые он изменит, и спрашивается «y/N»; «N»
#                      пропускает шаг целиком (сервер при этом ставится как обычно). Без
#                      интерактивного окна (агент, CI) вопроса нет, шаг идёт как при 1
#                      (TRK-408, TRK-546)
#   CASEFILE_PLUGIN_AUTOUPDATE  0 — плагин Claude Code ставится, но `"autoUpdate": true` в
#                      его settings.json не пишется (по умолчанию 1, TRK-546)
#   CASEFILE_SKILL_ONLY  1 — только агенты этой машины: без Docker, без каталога установки и
#                      без токена; для машины, которая подключается к Casefile на сервере.
#                      Адрес сервера в `CASEFILE_URL` — для чужого сервера, и только https (http — лишь для
#                      localhost: вне своей машины служба отдаёт вход OAuth только по https):
#                      $env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL='https://casefile.example.com/mcp'; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
#                      Без `CASEFILE_URL` плагин Claude Code и Codex ставится с адресом по
#                      умолчанию (http://127.0.0.1:8100/mcp): скил работает сразу, вход не
#                      ведётся, печатается, как задать адрес сервера.
#   CASEFILE_URL       адрес MCP сервера для `CASEFILE_SKILL_ONLY=1`; при полной установке
#                      адрес даёт сама установка
#   CASEFILE_LOGIN     0 — не вести вход OAuth, только напечатать команды (по умолчанию вход
#                      идёт, если окно — интерактивный терминал; без него — только печать)
#   CASEFILE_SKILL_SOURCE  откуда брать маркетплейс скила, по умолчанию azimov777/casefile;
#                      так шаг проверяют до публикации, как CASEFILE_REGISTRY для образов
#   CASEFILE_MCPB_URL  откуда качать расширение Claude Desktop `casefile.mcpb`, по умолчанию
#                      файл выпуска на GitHub (TRK-514); так его тоже проверяют до публикации

$ErrorActionPreference = 'Stop'

$Dir = if ($env:CASEFILE_DIR) { $env:CASEFILE_DIR } else { Join-Path $HOME 'casefile' }
$Compose = 'docker-compose.prod.yml'
$SkillOn = $env:CASEFILE_SKILL -ne '0'
# $true — перед шагом скила спросить «y/N», если есть кого (`Test-CanAsk`); явно названная
# `CASEFILE_SKILL` — ответ заранее, вопроса нет (TRK-546).
$SkillAsk = [string]::IsNullOrEmpty($env:CASEFILE_SKILL)
$PluginAutoUpdate = $env:CASEFILE_PLUGIN_AUTOUPDATE -ne '0'
# $true — шаг скила не выполнялся: человек ответил «N» (TRK-546); итог по нему не печатает
# про плагин то, чего нет.
$script:SkillSkipped = $false
$SkillOnly = $env:CASEFILE_SKILL_ONLY -eq '1'
$SkillSource = if ($env:CASEFILE_SKILL_SOURCE) { $env:CASEFILE_SKILL_SOURCE } else { 'azimov777/casefile' }
$LoginOn = $env:CASEFILE_LOGIN -ne '0'
# Адрес MCP, с которым ставится плагин: у полной установки — ответ самой установки, у
# `CASEFILE_SKILL_ONLY=1` — `CASEFILE_URL`; без него — адрес по умолчанию (TRK-480).
$script:PluginUrl = ''
# $true — адрес не назван: плагин ставится с адресом по умолчанию ради скила; вход OAuth
# не ведётся, чужие записи MCP не трогаются.
$script:DefaultUrl = $false
$script:DefaultNote = ''
# Адрес, прописанный в плагине Codex (`.codex-plugin/mcp.json`): другой ему задаёт только
# `codex mcp add` (TRK-451#13).
$CodexPluginUrl = 'http://127.0.0.1:8100/mcp'
$script:LoginClaude = $false
$script:LoginCodex = $false
# $true — у Claude Code маркетплейс переведён с прежнего источника (TRK-494, TRK-502).
$script:ClaudeMoved = $false
# Куда шаг Claude Desktop кладёт скачанный `casefile.mcpb` (`Install-Skills`, TRK-514).
$script:McpbFile = ''

function Fail([string] $Message) {
    Write-Host "casefile: $Message" -ForegroundColor Red
    # `exit` закрыл бы окно, из которого скрипт запущен через `iex`; исключение — нет.
    throw "casefile: $Message"
}

# Внешняя команда с ненулевым кодом `$ErrorActionPreference` не останавливает — ни в 5.1,
# ни по умолчанию в 7. Поэтому каждый вызов docker проверяется явно.
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { Fail "docker $($args -join ' ') failed (exit code $LASTEXITCODE)" }
}

# Значение из `.env` установки или умолчание: порты в итоговом сообщении должны быть
# теми, на которых контур действительно поднялся.
function Get-Setting([string] $Name, [string] $Default) {
    if (Test-Path .env) {
        $line = Get-Content .env | Where-Object { $_ -match "^$Name=" } | Select-Object -Last 1
        if ($line) {
            $value = $line.Substring($Name.Length + 1)
            if ($value) { return $value }
        }
    }
    return $Default
}

# Автообновление сервера (TRK-548), близнец `auto_update_*` из `install.sh`: до установки и
# после неё человек читает, что Casefile обновляет себя сам, что служба `updater` держит для
# этого сокет Docker и как это выключить. Выключено оно только точным `false` в `.env` (так
# читает его сама служба: `False`, `0` и пустое значение оставляют его включённым), и строки
# печатаются по `.env`, а не по умолчанию. Только в полной установке: при
# `CASEFILE_SKILL_ONLY=1` сервера на машине нет.
function Test-AutoUpdateOff {
    $envFile = Join-Path $Dir '.env'
    if (-not (Test-Path $envFile)) { return $false }
    $line = Get-Content $envFile | Where-Object { $_ -match '^CASEFILE_AUTO_UPDATE=' } | Select-Object -Last 1
    return [bool]($line -and $line.Substring('CASEFILE_AUTO_UPDATE='.Length).Trim() -ceq 'false')
}

# До установки: каталог ещё не создан, и человек может остановиться (Ctrl+C).
function Write-AutoUpdateIntro {
    if (Test-AutoUpdateOff) {
        Write-Host "Auto-update is off in this installation (CASEFILE_AUTO_UPDATE=false in $(Join-Path $Dir '.env'))." -ForegroundColor White
        Write-Host '  This run installs the latest release. After it, the board tells you when a newer one is out,'
        Write-Host '  and you update by running this installer again.'
    } else {
        Write-Host 'Casefile updates itself.' -ForegroundColor White
        Write-Host '  Once installed, its updater service checks for a new release when Docker starts and then every'
        Write-Host '  hour, and installs it by replacing the Casefile containers; your data stays in its volumes.'
        Write-Host '  To replace containers the updater holds the Docker socket (/var/run/docker.sock), which is'
        Write-Host '  root access to this machine.'
        Write-Host "  To turn it off, put CASEFILE_AUTO_UPDATE=false into $(Join-Path $Dir '.env') and run, in $Dir`:"
        Write-Host '    docker compose up -d --no-deps updater'
        Write-Host '  Then the board tells you when a new release is out, and you update by running this installer again.'
    }
    Write-Host ''
}

# В конце: тот же факт короткой строкой, с командой выключения (или включения обратно).
function Write-AutoUpdateOutro {
    if (Test-AutoUpdateOff) {
        Write-Host "Auto-update is off (CASEFILE_AUTO_UPDATE=false in $(Join-Path $Dir '.env')): the board tells you when a new release is out;"
        Write-Host "update by running this installer again. To turn it on, delete that line and run, in $Dir`:"
        Write-Host '  docker compose up -d --no-deps updater'
    } else {
        Write-Host 'Updates arrive by themselves: the updater checks for a new release when Docker starts and then every hour,'
        Write-Host "and holds the Docker socket (/var/run/docker.sock) for that. To turn it off, put CASEFILE_AUTO_UPDATE=false into $(Join-Path $Dir '.env') and run, in $Dir`:"
        Write-Host '  docker compose up -d --no-deps updater'
    }
    Write-Host "Files and data: $Dir"
}

# --- Скил во все найденные харнессы (TRK-408, решения TRK-401#11, #18) -------------------
# Близнец шага из `install.sh`: для каждого найденного `claude`, `codex`, `hermes` —
# маркетплейс и плагин, для прочих агентов — `npx skills`; всё идемпотентно, токен в файлы
# харнессов не пишется, самих харнессов установщик не ставит. Ошибка скила установку
# сервиса не валит: итог по каждому харнессу — строка с командой для ручного повтора.

$script:SkillLog = ''

function Write-SkillLine([string] $Name, [string] $Text) {
    Write-Host ('  {0,-13} {1}' -f $Name, $Text)
}

# Одна команда харнесса: тихо, stdin пустой, вывод — в журнал шага. `Continue` внутри
# функции: stderr внешней команды при `Stop` в PowerShell 5.1 — исключение.
function Invoke-SkillCmd {
    $ErrorActionPreference = 'Continue'
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    $out = & $exe @rest 2>&1 | Out-String
    $ok = $LASTEXITCODE -eq 0
    $script:SkillLog += $out
    $script:SkillLast = $out
    return $ok
}

function Write-SkillFailed([string] $Name, [string] $Retry) {
    Write-SkillLine $Name 'failed - repeat by hand:'
    Write-Host "                $Retry"
    ($script:SkillLog -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 3) |
        ForEach-Object { Write-Host "                > $_" }
}

# --- Согласие и копии (TRK-546) -----------------------------------------------------------
# Близнец одноимённого шага из `install.sh`. Шаг скила меняет файлы чужих программ:
# `settings.json` Claude Code, `config.toml` Codex, их записи MCP, `~/.agents/skills`. Он идёт
# с согласия человека, а перед первой правкой файла рядом остаётся его копия
# `<имя>.casefile-bak` (TRK-527#7: Beads потерял доверие тем, что переписывал
# `~/.claude/settings.json` без вопроса).

function Get-ClaudeSettingsPath {
    $dir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
    return (Join-Path $dir 'settings.json')
}

# Пользовательские и локальные записи MCP Claude Code лежат не в settings.json, а в
# `.claude.json`: `claude mcp remove` правит его, и копия нужна ему.
function Get-ClaudeJsonPath {
    $dir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { $HOME }
    return (Join-Path $dir '.claude.json')
}

function Get-CodexConfigPath {
    $dir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    return (Join-Path $dir 'config.toml')
}

# Спросить можно только в интерактивном окне: ни ввод, ни вывод не перенаправлены, службой
# окно не является и PowerShell запущен без -NonInteractive (там Read-Host бросает
# исключение). Под `irm | iex` скрипт приходит по конвейеру, а не по stdin, поэтому
# `IsInputRedirected` остаётся ложью, пока окно - консоль человека; агент или CI с трубами
# получает «нельзя» и идёт по CASEFILE_SKILL, не дожидаясь ответа.
function Test-CanAsk {
    try {
        if ([Console]::IsInputRedirected -or [Console]::IsOutputRedirected) { return $false }
        if (-not [Environment]::UserInteractive) { return $false }
    } catch { return $false }
    foreach ($arg in [Environment]::GetCommandLineArgs()) {
        if ($arg -like '-non*') { return $false }
    }
    return $true
}

# Копия кладётся один раз и дальше не затирается: повторный запуск видит файл уже тронутым и
# должен сохранить исходный. Нет файла - копировать нечего ($true). Не вышло - $false: файл
# тогда не меняется, а вызывающий пропускает свой шаг.
function Backup-Once([string] $Label, [string] $File) {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { return $true }
    $copy = "$File.casefile-bak"
    if (Test-Path -LiteralPath $copy) { return $true }
    try {
        Copy-Item -LiteralPath $File -Destination $copy -ErrorAction Stop
        Write-SkillLine $Label "saved a copy of $File as $(Split-Path -Leaf $copy) (the original, kept: it is never overwritten)"
        return $true
    } catch {
        Write-SkillLine $Label "could not save a copy of $File, so nothing in it was changed"
        return $false
    }
}

# Что шаг изменит, и вопрос. $true - идти дальше, $false - человек ответил «N»: шаг пропущен
# целиком (сервер уже стоит). Список печатается и без окна - в журнале агента или CI видно,
# что было тронуто. Строится по найденным харнессам и режиму, как в `install.sh`: чужие
# записи MCP убираются, только если адрес известен, а config.toml Codex получает запись,
# только если адрес не тот, что зашит в его плагине.
function Confirm-SkillStep {
    $hasClaude = [bool] (Get-Command claude -ErrorAction SilentlyContinue)
    $hasCodex = [bool] (Get-Command codex -ErrorAction SilentlyContinue)
    $hasHermes = [bool] (Get-Command hermes -ErrorAction SilentlyContinue)
    $hasNpx = [bool] (Get-Command npx -ErrorAction SilentlyContinue)
    $hasDesktop = Test-DesktopPending
    if (-not ($hasClaude -or $hasCodex -or $hasHermes -or $hasNpx -or $hasDesktop)) { return $true }
    Write-Host '  This step changes files that belong to other programs. Before the first change to a file'
    Write-Host '  a copy is saved next to it as <name>.casefile-bak (kept, never overwritten). What it touches:'
    if ($hasClaude) {
        Write-SkillLine 'Claude Code' "$(Get-ClaudeSettingsPath): the claude command adds the plugin there"
        if ($PluginAutoUpdate) {
            Write-SkillLine '' 'and "autoUpdate": true goes into extraKnownMarketplaces.casefile (CASEFILE_PLUGIN_AUTOUPDATE=0 leaves it out)'
        }
        if (-not $script:DefaultUrl) {
            Write-SkillLine '' "the manual MCP entries `"casefile`" and `"tracker`" at $($script:PluginUrl) are removed ($(Get-ClaudeJsonPath); its copy keeps them)"
        }
    }
    if ($hasCodex) {
        Write-SkillLine 'Codex' "$(Get-CodexConfigPath): the codex command adds the plugin there"
        if ((ConvertTo-NormalUrl $script:PluginUrl) -ne (ConvertTo-NormalUrl $CodexPluginUrl)) {
            Write-SkillLine '' "and the lines [mcp_servers.casefile] url = `"$($script:PluginUrl)`" are appended"
        }
        if (-not $script:DefaultUrl) {
            Write-SkillLine '' "the manual MCP entries `"casefile`" and `"tracker`" at $($script:PluginUrl) are removed (its copy keeps them)"
        }
    }
    if ($hasHermes) { Write-SkillLine 'Hermes' 'hermes skills install (its own skills folder)' }
    if ($hasNpx) { Write-SkillLine 'Other agents' "$(Join-Path $HOME '.agents/skills/casefile') (npx skills add)" }
    if ($hasDesktop) {
        Write-SkillLine 'Claude Desktop' "casefile.mcpb is downloaded to $($script:McpbFile) and opened; Claude Desktop then"
        Write-SkillLine '' 'asks before it installs anything (claude_desktop_config.json is not touched)'
    }
    if (-not $SkillAsk) {
        Write-Host '  CASEFILE_SKILL=1 is set: going ahead without asking.'
        return $true
    }
    if (-not (Test-CanAsk)) {
        Write-Host '  No terminal to ask on, so it goes ahead (CASEFILE_SKILL=0 skips it).'
        return $true
    }
    $answer = $null
    try { $answer = Read-Host '  Install the plugin and make these changes? [y/N]' } catch { $answer = $null }
    if ($null -eq $answer) {
        Write-Host '  No terminal to ask on, so it goes ahead (CASEFILE_SKILL=0 skips it).'
        return $true
    }
    if ($answer.Trim() -match '^(?i:y|yes)$') { return $true }
    $script:SkillSkipped = $true
    $later = '$env:CASEFILE_SKILL=1; '
    if ($SkillOnly) { $later += '$env:CASEFILE_SKILL_ONLY=1; ' }
    if ($env:CASEFILE_URL) { $later += "`$env:CASEFILE_URL='$($env:CASEFILE_URL)'; " }
    Write-Host '  Skipped: no file of another program was touched. To install the plugin later, run the'
    Write-Host '  installer again and answer y ($env:CASEFILE_SKILL=1 before it skips the question):'
    Write-Host "    ${later}irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex"
    Write-Host '  Or by hand: docs/agent-install.md, step 4'
    Write-Host '  (https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md).'
    Write-Host ''
    return $false
}

# Объявление маркетплейса `casefile` в settings.json Claude Code правится точечно, как в
# `install.sh` (TRK-546): файл не пересобирается разбором и обратной сборкой JSON (она
# переформатирует всё и портит значения: целое больше 2^64 становится объектом, замер на
# PowerShell 7.4), а получает ровно одну текстовую вставку. Узел находится сканером по
# тексту, вставка проверяется разбором. Тот же алгоритм, что в `install.sh`.
function Skip-JsonWs([string] $t, [int] $i) {
    while ($i -lt $t.Length) {
        $c = $t[$i]
        if ($c -eq ' ' -or $c -eq "`t" -or $c -eq "`r" -or $c -eq "`n" -or $c -eq [char]0xFEFF) { $i++ } else { break }
    }
    return $i
}

function Get-JsonStringEnd([string] $t, [int] $i) {
    $i++
    while ($t[$i] -ne '"') {
        if ($t[$i] -eq '\') { $i += 2 } else { $i++ }
    }
    return $i + 1
}

function Get-JsonValueEnd([string] $t, [int] $i) {
    $c = $t[$i]
    if ($c -eq '"') { return (Get-JsonStringEnd $t $i) }
    if ($c -eq '{' -or $c -eq '[') {
        $depth = 0
        while ($true) {
            $c = $t[$i]
            if ($c -eq '"') { $i = Get-JsonStringEnd $t $i; continue }
            if ($c -eq '{' -or $c -eq '[') { $depth++ } elseif ($c -eq '}' -or $c -eq ']') { $depth-- }
            $i++
            if ($depth -eq 0) { return $i }
        }
    }
    while ($i -lt $t.Length -and " `t`r`n,}]".IndexOf($t[$i]) -lt 0) { $i++ }
    return $i
}

# Члены объекта, открытого в `$t[$open]`: ключ вместе с кавычками и границы ключа (KS, KE) и
# значения (VS, VE).
function Get-JsonMembers([string] $t, [int] $open) {
    $list = New-Object System.Collections.ArrayList
    $i = Skip-JsonWs $t ($open + 1)
    while ($t[$i] -ne '}') {
        $ks = $i
        $ke = Get-JsonStringEnd $t $i
        $i = Skip-JsonWs $t $ke
        $vs = Skip-JsonWs $t ($i + 1)
        $ve = Get-JsonValueEnd $t $vs
        [void] $list.Add([pscustomobject] @{ Key = $t.Substring($ks, $ke - $ks); KS = $ks; KE = $ke; VS = $vs; VE = $ve })
        $i = Skip-JsonWs $t $ve
        if ($t[$i] -eq ',') { $i = Skip-JsonWs $t ($i + 1) }
    }
    return , $list
}

function Find-JsonMember($members, [string] $name) {
    foreach ($m in $members) {
        if ($m.Key -ceq ('"' + $name + '"')) { return $m }
    }
    return $null
}

# Новый текст; `$null` - узла нет (`auto_update` без объявления `casefile`); без объявления
# `drop` не меняет ничего.
function Edit-ClaudeSettingsText([string] $Text, [string] $Op) {
    $tm = Find-JsonMember (Get-JsonMembers $Text (Skip-JsonWs $Text 0)) 'extraKnownMarketplaces'
    $km = @()
    if ($tm -and $Text[$tm.VS] -eq '{') { $km = Get-JsonMembers $Text $tm.VS }
    $mc = Find-JsonMember $km 'casefile'
    if (-not $mc -or $Text[$mc.VS] -ne '{') {
        if ($Op -ne 'drop') { return $null }
        return $Text
    }
    if ($Op -eq 'drop') {
        $i = $km.IndexOf($mc)
        if ($km.Count -eq 1) { return $Text.Substring(0, $tm.VS + 1) + $Text.Substring($mc.VE) }
        if ($i -lt $km.Count - 1) { return $Text.Substring(0, $mc.KS) + $Text.Substring($km[$i + 1].KS) }
        return $Text.Substring(0, $km[$i - 1].VE) + $Text.Substring($mc.VE)
    }
    $cm = Get-JsonMembers $Text $mc.VS
    $au = Find-JsonMember $cm 'autoUpdate'
    if ($au) { return $Text.Substring(0, $au.VS) + 'true' + $Text.Substring($au.VE) }
    if ($cm.Count -eq 0) { return $Text.Substring(0, $mc.VS + 1) + '"autoUpdate": true' + $Text.Substring($mc.VS + 1) }
    $first = $cm[0]
    $end = $cm[$cm.Count - 1].VE
    $lead = $Text.Substring($mc.VS + 1, $first.KS - $mc.VS - 1)
    $sep = $Text.Substring($first.KE, $first.VS - $first.KE)
    return $Text.Substring(0, $end) + ',' + $lead + '"autoUpdate"' + $sep + 'true' + $Text.Substring($end)
}

# Вставка разбирается как JSON и проверяется на нужный результат; иначе файл не пишется.
function Test-ClaudeSettingsText([string] $Text, [string] $Op) {
    try {
        $entry = ($Text | ConvertFrom-Json).extraKnownMarketplaces.casefile
        if ($Op -eq 'drop') { return (-not $entry) }
        return ($entry.autoUpdate -eq $true)
    } catch {
        return $false
    }
}

# Файл пишется, только если изменился, в той же кодировке (BOM, если был) и с теми же
# концами строк. Копию `.casefile-bak` кладёт `Backup-Once` до первой команды харнесса.
function Update-ClaudeSettings([string] $Op) {
    $file = Get-ClaudeSettingsPath
    if (-not (Test-Path -LiteralPath $file)) { return $false }
    try {
        $bytes = [System.IO.File]::ReadAllBytes($file)
        $bom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
        $text = [System.IO.File]::ReadAllText($file)
        $new = Edit-ClaudeSettingsText $text $Op
        if ($null -eq $new) { return $false }
        if ($new -ceq $text) { return $true }
        if (-not (Test-ClaudeSettingsText $new $Op)) { return $false }
        [System.IO.File]::WriteAllText($file, $new, (New-Object System.Text.UTF8Encoding($bom)))
        return $true
    } catch {
        return $false
    }
}

# `"autoUpdate": true` последним ключом extraKnownMarketplaces.casefile: у сторонних
# маркетплейсов Claude Code обновляет плагин сам только с ним, а флага в CLI нет (TRK-406).
function Set-ClaudeAutoUpdate {
    return (Update-ClaudeSettings 'auto_update')
}

# Близнец `claude_settings drop` из `install.sh`: вырезает объявление маркетплейса `casefile`
# из settings.json, чтобы установка ушла с прежнего источника (TRK-494).
function Remove-ClaudeMarketplaceEntry {
    return (Update-ClaudeSettings 'drop')
}

# Маркетплейс плагина — узкая ветка `plugin` (TRK-494), близнец `claude_marketplace_add` и
# `codex_marketplace_add` из `install.sh`: установка, поставленная со `stable`, получает
# отказ `add` с другим источником, прежний источник снимается и `add` повторяется. У Claude
# Code — только объявление в settings.json (`marketplace remove` удалил бы и плагин с его
# настройками), у Codex — `marketplace remove`, после которого плагин остаётся включённым.
# Отказ Claude Code называется двумя фразами: «differs from the one declared» (до 2.1.289) и
# «match its extraKnownMarketplaces entry» (с 2.1.289, TRK-550); иная ошибка `add` не в счёт.
function Add-ClaudeMarketplace([string] $Source) {
    if (Invoke-SkillCmd claude plugin marketplace add $Source) { return $true }
    if ($script:SkillLast -notmatch 'differs from the one declared|match its extraKnownMarketplaces entry') { return $false }
    if ((Remove-ClaudeMarketplaceEntry) -and (Invoke-SkillCmd claude plugin marketplace add $Source)) {
        $script:ClaudeMoved = $true
        return $true
    }
    return $false
}

# Близнец `claude_current_url` из `install.sh`: вход Claude Code привязан к адресу (ключ —
# имя сервера и хеш type, url, headers; TRK-502#6), поэтому адрес установленного плагина
# читается до `install`. Пусто — плагина нет или клиент старый.
function Get-ClaudeCurrentUrl {
    $ErrorActionPreference = 'Continue'
    try {
        $text = & claude plugin configure casefile@casefile --json 2>$null | Out-String
        $m = [regex]::Match($text, '(?m)^\s*"casefile_url":\s*"([^"]*)"')
        if ($m.Success) { return $m.Groups[1].Value }
    } catch {}
    return ''
}

function Add-CodexMarketplace {
    if (Invoke-SkillCmd codex plugin marketplace add $SkillSource --ref plugin) { return $true }
    if ($script:SkillLast -notmatch 'already added from a different source') { return $false }
    return (Invoke-SkillCmd codex plugin marketplace remove casefile) -and
        (Invoke-SkillCmd codex plugin marketplace add $SkillSource --ref plugin)
}

# --- Ручные записи MCP, которые плагин заменяет (TRK-452, TRK-427#10) ------------------------
# Близнец `cleanup_*_entries` из `install.sh`: запись `casefile` (и `tracker`) убирается, только
# если и имя, и адрес — этой установки (`localhost` и `127.0.0.1` — один адрес); остальные
# остаются, о каждом решении печатается строка.
function ConvertTo-NormalUrl([string] $Url) {
    return ($Url -replace '^(https?://)localhost', '${1}127.0.0.1').TrimEnd('/')
}

function Remove-ClaudeEntries {
    $ErrorActionPreference = 'Continue'
    foreach ($name in 'casefile', 'tracker') {
        $info = & claude mcp get $name 2>$null | Out-String
        if ($LASTEXITCODE -ne 0) { continue }
        $url = [regex]::Match($info, '(?m)^\s*URL:\s*(\S+)').Groups[1].Value
        $scope = [regex]::Match($info, '(?m)^\s*Scope:\s*([A-Za-z]+)').Groups[1].Value
        if (-not $url) { continue }
        if ((ConvertTo-NormalUrl $url) -eq (ConvertTo-NormalUrl $script:PluginUrl)) {
            $flag = switch ($scope) { 'User' { 'user' } 'Local' { 'local' } default { '' } }
            if ($flag -and (Backup-Once 'Claude Code' (Get-ClaudeJsonPath)) -and (Invoke-SkillCmd claude mcp remove $name --scope $flag)) {
                Write-SkillLine 'Claude Code' "removed the manual MCP entry `"$name`" ($url, $flag scope): the plugin carries the connection"
            } else {
                Write-SkillLine 'Claude Code' "left the manual MCP entry `"$name`" ($url, $scope scope): remove it by hand: claude mcp remove $name"
            }
        } else {
            Write-SkillLine 'Claude Code' "left the MCP entry `"$name`" ($url): it is not this installation's address"
        }
    }
}

function Remove-CodexEntries {
    $ErrorActionPreference = 'Continue'
    foreach ($name in 'casefile', 'tracker') {
        $info = & codex mcp get $name --json 2>$null | Out-String
        if ($LASTEXITCODE -ne 0) { continue }
        $url = [regex]::Match($info, '"url":\s*"([^"]*)"').Groups[1].Value
        if (-not $url) { continue }
        if ((ConvertTo-NormalUrl $url) -eq (ConvertTo-NormalUrl $script:PluginUrl)) {
            if (Invoke-SkillCmd codex mcp remove $name) {
                Write-SkillLine 'Codex' "removed the manual MCP entry `"$name`" ($url) from config.toml"
            } else {
                Write-SkillLine 'Codex' "left the manual MCP entry `"$name`" ($url): remove it by hand: codex mcp remove $name"
            }
        } else {
            Write-SkillLine 'Codex' "left the MCP entry `"$name`" ($url): it is not this installation's address"
        }
    }
}

function Install-ClaudeSkill {
    if (-not (Backup-Once 'Claude Code' (Get-ClaudeSettingsPath))) { return }
    $src = "${SkillSource}#plugin"
    $url = $script:PluginUrl
    $note = $script:DefaultNote
    $was = Get-ClaudeCurrentUrl
    $script:ClaudeMoved = $false
    if ($script:DefaultUrl -and $was) {
        $url = $was
        $note = " (kept the address it had: your server's goes in CASEFILE_URL)"
    }
    $retry = "claude plugin marketplace add $src; claude plugin install casefile@casefile --scope user --config casefile_url=$url"
    if (-not $script:DefaultUrl) { Remove-ClaudeEntries }
    $ok = (Add-ClaudeMarketplace $src) -and
        (Invoke-SkillCmd claude plugin marketplace update casefile) -and
        (Invoke-SkillCmd claude plugin install casefile@casefile --scope user --config "casefile_url=$url") -and
        (Invoke-SkillCmd claude plugin update casefile@casefile)
    if (-not $ok) { Write-SkillFailed 'Claude Code' $retry; return }
    $ErrorActionPreference = 'Continue'
    $text = & claude plugin list 2>$null | Out-String
    $m = [regex]::Match($text, 'casefile@casefile[^\r\n]*[\r\n]+\s*Version:\s*(\S+)[\s\S]*?Status:\s*([^\r\n]*)')
    if (-not ($m.Success -and $m.Groups[2].Value -match 'enabled')) { Write-SkillFailed 'Claude Code' $retry; return }
    $version = $m.Groups[1].Value
    if (-not $script:DefaultUrl) { $script:LoginClaude = $true }
    if (-not $PluginAutoUpdate) {
        Write-SkillLine 'Claude Code' "installed $version, connected to $url$note (automatic updates not switched on, as CASEFILE_PLUGIN_AUTOUPDATE=0 says; to update by hand: claude plugin update casefile@casefile)"
    } elseif (Set-ClaudeAutoUpdate) {
        Write-SkillLine 'Claude Code' "installed $version (updates itself), connected to $url$note"
    } else {
        Write-SkillLine 'Claude Code' "installed $version, connected to $url$note (automatic updates not switched on: add `"autoUpdate`": true inside extraKnownMarketplaces.casefile in settings.json)"
    }
    if ($was -and $was -cne $url) {
        Write-SkillLine 'Claude Code' "the address changed from ${was}: the sign-in belongs to the address, sign in again: claude mcp login plugin:casefile:casefile"
    } elseif ($script:ClaudeMoved) {
        Write-SkillLine 'Claude Code' "moved to the plugin branch; the sign-in stays with the address - if claude mcp list shows `"Needs authentication`": claude mcp login plugin:casefile:casefile"
    }
}

function Set-CodexUrl {
    $dir = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    $file = Join-Path $dir 'config.toml'
    try {
        if ((Test-Path $file) -and ([System.IO.File]::ReadAllText($file) -match '(?m)^\[mcp_servers\.casefile[\].]')) { return $false }
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        [System.IO.File]::AppendAllText($file, "`n[mcp_servers.casefile]`nurl = `"$($script:PluginUrl)`"`n", (New-Object System.Text.UTF8Encoding($false)))
        return $true
    } catch {
        return $false
    }
}

function Install-CodexSkill {
    if (-not (Backup-Once 'Codex' (Get-CodexConfigPath))) { return }
    $retry = "codex plugin marketplace add $SkillSource --ref plugin; codex plugin add casefile@casefile"
    if (-not $script:DefaultUrl) { Remove-CodexEntries }
    $ok = (Add-CodexMarketplace) -and
        (Invoke-SkillCmd codex plugin marketplace upgrade casefile) -and
        (Invoke-SkillCmd codex plugin add casefile@casefile)
    if (-not $ok) { Write-SkillFailed 'Codex' $retry; return }
    $ErrorActionPreference = 'Continue'
    $row = & codex plugin list 2>$null | Where-Object { $_ -match '^casefile@casefile\s.*installed' } | Select-Object -First 1
    $m = [regex]::Match([string] $row, '\s(\d+\.\d+\S*)')
    if (-not $m.Success) { Write-SkillFailed 'Codex' $retry; return }
    $version = $m.Groups[1].Value
    if (-not $script:DefaultUrl) { $script:LoginCodex = $true }
    # Адрес плагина у Codex зашит: другой задаёт одноимённый сервер из config.toml, он
    # вытесняет плагинный (TRK-451#13). Токена в нём нет — вход OAuth. Строка пишется сюда
    # же, куда её пишет `codex mcp add`, но без него: тот сразу запускает вход и без
    # терминала возвращает ошибку, хотя запись уже есть.
    if ((ConvertTo-NormalUrl $script:PluginUrl) -eq (ConvertTo-NormalUrl $CodexPluginUrl)) {
        Write-SkillLine 'Codex' "installed $version, connected to $($script:PluginUrl)$($script:DefaultNote)"
    } elseif (Set-CodexUrl) {
        Write-SkillLine 'Codex' "installed $version, connected to $($script:PluginUrl) (an entry without a token in config.toml)"
    } else {
        Write-SkillFailed 'Codex' "codex mcp add casefile --url $($script:PluginUrl)"
    }
}

function Install-HermesSkill {
    $retry = "hermes skills install $SkillSource/skills/casefile"
    $home_ = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME '.hermes' }
    $found = $false
    if (Invoke-SkillCmd hermes skills install "$SkillSource/skills/casefile") {
        $found = [bool] (Get-ChildItem -Path $home_ -Recurse -Filter SKILL.md -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match 'casefile' } | Select-Object -First 1)
        if (-not $found) {
            $ErrorActionPreference = 'Continue'
            $found = (& hermes skills list 2>$null | Out-String) -match '(?i)casefile'
        }
    }
    if ($found) { Write-SkillLine 'Hermes' 'installed' } else { Write-SkillFailed 'Hermes' $retry }
}

# Прочие агенты (Cursor, Cline, ...) читают общий `~/.agents/skills`: `--agent cursor` кладёт
# скил именно туда и не трогает каталог Claude Code, где он уже стоит плагином.
function Install-OtherAgentsSkill {
    $retry = "npx skills add ${SkillSource}#stable -g -y --agent cursor"
    $target = Join-Path $HOME '.agents/skills/casefile/SKILL.md'
    if ((Invoke-SkillCmd npx -y skills add "${SkillSource}#stable" -g -y --agent cursor) -and (Test-Path $target)) {
        Write-SkillLine 'Other agents' 'installed (~/.agents/skills/casefile)'
    } else {
        Write-SkillFailed 'Other agents' $retry
    }
}

# --- Claude Desktop (TRK-514) -------------------------------------------------------------
# Близнец шага из `install.sh`: чат Claude Desktop получает Casefile расширением
# `casefile.mcpb` из выпуска GitHub (решение TRK-514#5) — мост `mcp-remote` на встроенной в
# Desktop среде Node, адрес в форме Desktop, вход OAuth. Установщик файл скачивает и
# открывает (`Start-Process`), ставит его сам Desktop по щелчку человека;
# `claude_desktop_config.json` никто не правит. Папка данных Desktop — `%APPDATA%\Claude`, а у
# сборки MSIX — `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`
# (anthropics/claude-code#25579): ищутся обе. Стоящее расширение узнаётся по адресу
# репозитория в его распакованном `Claude Extensions\<id>\manifest.json`.

function Get-DesktopDirs {
    if ($env:APPDATA) {
        $dir = Join-Path $env:APPDATA 'Claude'
        if (Test-Path -LiteralPath $dir -PathType Container) { $dir }
    }
    if ($env:LOCALAPPDATA) {
        $packages = Join-Path $env:LOCALAPPDATA 'Packages'
        if (Test-Path -LiteralPath $packages -PathType Container) {
            foreach ($package in Get-ChildItem -LiteralPath $packages -Directory -Filter 'Claude_*' -ErrorAction SilentlyContinue) {
                $dir = Join-Path $package.FullName 'LocalCache\Roaming\Claude'
                if (Test-Path -LiteralPath $dir -PathType Container) { $dir }
            }
        }
    }
}

# Файл выпуска, названного CASEFILE_VERSION (полная установка — ещё и её `.env`), иначе
# последнего; CASEFILE_MCPB_URL — свой адрес.
function Get-McpbUrl {
    if ($env:CASEFILE_MCPB_URL) { return $env:CASEFILE_MCPB_URL }
    $mcpbVersion = $env:CASEFILE_VERSION
    if (-not $mcpbVersion -and -not $SkillOnly) { $mcpbVersion = Get-Setting 'CASEFILE_VERSION' 'stable' }
    if ($mcpbVersion -match '^[0-9]') {
        return "https://github.com/azimov777/casefile/releases/download/v$mcpbVersion/casefile.mcpb"
    }
    return 'https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb'
}

# Версия стоящего расширения Casefile (или `installed`); пустая строка — его нет.
function Get-DesktopExtension {
    foreach ($dir in @(Get-DesktopDirs)) {
        $extensions = Join-Path $dir 'Claude Extensions'
        if (-not (Test-Path -LiteralPath $extensions -PathType Container)) { continue }
        foreach ($extension in Get-ChildItem -LiteralPath $extensions -Directory -ErrorAction SilentlyContinue) {
            $manifest = Join-Path $extension.FullName 'manifest.json'
            if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { continue }
            $text = Get-Content -LiteralPath $manifest -Raw -ErrorAction SilentlyContinue
            if ($text -and $text.Contains('github.com/azimov777/casefile')) {
                if ($text -match '"version"\s*:\s*"([^"]+)"') { return $Matches[1] }
                return 'installed'
            }
        }
    }
    return ''
}

# Шагу есть что делать: Desktop стоит, адрес сервера известен, расширения ещё нет.
function Test-DesktopPending {
    return ((@(Get-DesktopDirs).Count -gt 0) -and (-not $script:DefaultUrl) -and (-not (Get-DesktopExtension)))
}

function Install-DesktopExtension {
    $url = Get-McpbUrl
    $byHand = 'double-click it, or in Claude Desktop: Settings > Extensions > Advanced settings > Install Extension...'
    if ($script:DefaultUrl) {
        Write-SkillLine 'Claude Desktop' "not set up: it needs your server's address in CASEFILE_URL (or install $url by hand)"
        return
    }
    $found = Get-DesktopExtension
    if ($found) {
        Write-SkillLine 'Claude Desktop' "has the Casefile extension ($found); a newer one: $url, $byHand"
        return
    }
    # Адрес по умолчанию у расширения тот же, что у плагина Codex (`mcpb/manifest.json`).
    if ((ConvertTo-NormalUrl $script:PluginUrl) -eq (ConvertTo-NormalUrl $CodexPluginUrl)) {
        $address = "keep the address it shows ($CodexPluginUrl)"
    } else {
        $address = "put $($script:PluginUrl) into its address field"
    }
    $part = "$($script:McpbFile).download"
    try {
        # Без -UseBasicParsing PowerShell 5.1 зовёт движок Internet Explorer; полоса прогресса
        # замедляет загрузку в разы.
        $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri $url -OutFile $part -UseBasicParsing
        Move-Item -LiteralPath $part -Destination $script:McpbFile -Force
    } catch {
        Remove-Item -LiteralPath $part -Force -ErrorAction SilentlyContinue
        Write-SkillLine 'Claude Desktop' "could not download $url - download it and $byHand; $address"
        Write-Host "                > $($_.Exception.Message)"
        return
    }
    try {
        Start-Process -FilePath $script:McpbFile
        Write-SkillLine 'Claude Desktop' "opened $($script:McpbFile): click Install in Claude Desktop and $address;"
        Write-SkillLine '' 'its first connection opens a browser page for the sign-in (Node.js is not needed)'
    } catch {
        Write-SkillLine 'Claude Desktop' "could not open $($script:McpbFile) - $byHand; $address"
    }
}

function Install-Skills {
    # Полная установка кладёт расширение в свой каталог, `CASEFILE_SKILL_ONLY=1` каталога не
    # заводит — туда же, куда его положил бы браузер.
    if ($SkillOnly) {
        $downloads = Join-Path $HOME 'Downloads'
        $script:McpbFile = if (Test-Path -LiteralPath $downloads -PathType Container) { Join-Path $downloads 'casefile.mcpb' } else { Join-Path $HOME 'casefile.mcpb' }
    } else {
        $script:McpbFile = Join-Path $Dir 'casefile.mcpb'
    }
    $script:SkillLog = ''
    Write-Host 'Installing the Casefile skill for the agents on this machine:' -ForegroundColor White
    if (-not (Confirm-SkillStep)) { return }
    foreach ($h in @(
            @{ Exe = 'claude'; Name = 'Claude Code'; Run = { Install-ClaudeSkill } },
            @{ Exe = 'codex'; Name = 'Codex'; Run = { Install-CodexSkill } },
            @{ Exe = 'hermes'; Name = 'Hermes'; Run = { Install-HermesSkill } })) {
        if (Get-Command $h.Exe -ErrorAction SilentlyContinue) {
            & $h.Run
        } else {
            Write-SkillLine $h.Name 'not found (run this installer again after installing it)'
        }
    }
    if (Get-Command npx -ErrorAction SilentlyContinue) {
        Install-OtherAgentsSkill
    } else {
        Write-SkillLine 'Other agents' "npx not found (with Node.js: npx skills add ${SkillSource}#stable)"
    }
    if (@(Get-DesktopDirs).Count -gt 0) {
        Install-DesktopExtension
    } else {
        Write-SkillLine 'Claude Desktop' 'not found (run this installer again after installing it)'
    }
    Write-Host '  A running session picks up the plugin after a restart (in Claude Code: /reload-plugins).'
    Write-Host ''
    Invoke-SignIn
}

# --- Вход OAuth (TRK-452) -----------------------------------------------------------------
# Близнец `sign_in` из `install.sh`: один раз на харнесс, только в интерактивном терминале
# (Claude Code иначе не входит, TRK-432#8). Не терминал (stdin или stdout перенаправлены) или
# CASEFILE_LOGIN=0 — вход не запускается, печатается команда. Ошибка входа установку не валит.
function Test-Interactive {
    if (-not $LoginOn) { return $false }
    try { return (-not [Console]::IsInputRedirected) -and (-not [Console]::IsOutputRedirected) } catch { return $false }
}

function Invoke-SignInOne([string] $Name, [string] $Exe, [string[]] $CmdArgs) {
    $ErrorActionPreference = 'Continue'
    & $Exe @CmdArgs
    if ($LASTEXITCODE -eq 0) {
        Write-SkillLine $Name 'signed in'
    } else {
        Write-SkillLine $Name "sign-in did not finish - repeat by hand: $Exe $($CmdArgs -join ' ')"
    }
}

function Invoke-SignIn {
    if (-not ($script:LoginClaude -or $script:LoginCodex)) { return }
    Write-Host 'Signing the agents in to Casefile (OAuth, no token on disk):' -ForegroundColor White
    if (Test-Interactive) {
        Write-Host '  A browser window may open; approve the sign-in there.'
        if ($script:LoginClaude) { Invoke-SignInOne 'Claude Code' 'claude' @('mcp', 'login', 'plugin:casefile:casefile') }
        if ($script:LoginCodex) { Invoke-SignInOne 'Codex' 'codex' @('mcp', 'login', 'casefile') }
    } else {
        Write-Host '  This needs a terminal; run once, in a terminal of yours:'
        if ($script:LoginClaude) { Write-Host '    claude mcp login plugin:casefile:casefile' }
        if ($script:LoginCodex) { Write-Host '    codex mcp login casefile' }
    }
    Write-Host ''
}

# Машина агента, которая только подключается к Casefile на сервере: ни Docker, ни каталога
# установки, ни токена (TRK-401#18). `return`, а не `exit`: `exit` закрыл бы окно, из
# которого скрипт запущен через `iex`.
if ($SkillOnly) {
    # Адрес сервера — `CASEFILE_URL`: с ним ставится плагин (скил и коннектор) и ведётся
    # вход OAuth, без него — тот же плагин с адресом по умолчанию ради скила, без входа, и
    # подсказка, как задать адрес (TRK-480).
    $script:PluginUrl = if ($env:CASEFILE_URL) { $env:CASEFILE_URL } else { '' }
    if (-not $script:PluginUrl) {
        $script:PluginUrl = $CodexPluginUrl
        $script:DefaultUrl = $true
        $script:DefaultNote = " (default address: your server's goes in CASEFILE_URL)"
    }
    if ($script:PluginUrl -and ($script:PluginUrl -notmatch '^https://.' -and
            $script:PluginUrl -notmatch '^http://(localhost|127\.0\.0\.1|\[::1\])([:/]|$)')) {
        Fail 'CASEFILE_URL must be an https:// address (http:// only for localhost): outside the local machine the service offers the OAuth sign-in over https only'
    }
    try { Install-Skills } catch { Write-Host "casefile: the skill step failed: $_" -ForegroundColor Red }
    if ($script:DefaultUrl -and -not $script:SkillSkipped) {
        Write-Host "The plugin carries the skill and points at the default address $($script:PluginUrl); no sign-in was started."
        Write-Host 'To connect Claude Code and Codex to your server, run this again with its address:'
        Write-Host '  curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh'
        Write-Host '(Windows PowerShell: $env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL=''https://casefile.example.com/mcp''; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex)'
    }
    Write-Host 'Other agents (Hermes and the like): docs/agent-install.md, "Joining an installation someone else runs"'
    Write-Host '(https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md).'
    return
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail 'Docker Desktop is required: https://docs.docker.com/desktop/setup/install/windows-install/'
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker Compose v2 is required (the 'docker compose' command)." }
& docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker is not running. Start Docker Desktop and run this again.' }

# Docker Desktop может быть переключён в режим Windows-контейнеров: тогда образы Linux
# не поднимутся, а человек увидит чужую ошибку пула вместо причины.
$osType = (& docker info --format '{{.OSType}}' 2>$null | Out-String).Trim()
if ($osType -eq 'windows') {
    Fail 'Docker Desktop is set to Windows containers, but Casefile needs Linux containers. Switch to Linux containers (right-click the Docker Desktop tray icon and choose "Switch to Linux containers...") and run this again.'
}

Write-AutoUpdateIntro

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Location $Dir

Write-Host "Installing Casefile into $Dir" -ForegroundColor White

# `.env` заводится один раз и дальше принадлежит человеку. Пишется без BOM: `Set-Content
# -Encoding UTF8` в PowerShell 5.1 ставит его в начало файла, и compose прочитал бы первую
# переменную с невидимым символом в имени. Реестр и выпуск — только если их назвали.
if (-not (Test-Path .env)) {
    $lines = @("COMPOSE_FILE=$Compose")
    if ($env:CASEFILE_REGISTRY) { $lines += "CASEFILE_REGISTRY=$env:CASEFILE_REGISTRY" }
    if ($env:CASEFILE_VERSION) { $lines += "CASEFILE_VERSION=$env:CASEFILE_VERSION" }
    # Порты и имя проекта (TRK-493): иначе обновлятор и `docker compose up` вернули бы 8080/8100 и `casefile`.
    if ($env:CASEFILE_PORT) { $lines += "CASEFILE_PORT=$env:CASEFILE_PORT" }
    if ($env:TRACKER_MCP_PORT) { $lines += "TRACKER_MCP_PORT=$env:TRACKER_MCP_PORT" }
    if ($env:COMPOSE_PROJECT_NAME) { $lines += "COMPOSE_PROJECT_NAME=$env:COMPOSE_PROJECT_NAME" }
    [System.IO.File]::WriteAllLines((Join-Path $Dir '.env'), $lines)
}

# Compose-файл лежит в образе выпуска (`docker/Dockerfile.prod`); тем же путём его берёт
# служба updater. Выбор образа тот же, что у compose: окружение, затем `.env`, затем
# умолчание файла. Файл копирует `docker cp` байт в байт: вывод внешней команды PowerShell
# перекодировал бы, и русские комментарии файла разошлись бы с файлом в образе.
$registry = if ($env:CASEFILE_REGISTRY) { $env:CASEFILE_REGISTRY } else { Get-Setting 'CASEFILE_REGISTRY' 'ghcr.io/azimov777' }
$version = if ($env:CASEFILE_VERSION) { $env:CASEFILE_VERSION } else { Get-Setting 'CASEFILE_VERSION' 'stable' }
$image = "$registry/casefile:$version"
& docker pull --quiet $image *> $null
if ($LASTEXITCODE -ne 0) { Fail "could not download $image; check the network, or the release name in CASEFILE_VERSION" }
$holder = (& docker create --pull never $image | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $holder) { Fail "could not open $image" }
& docker cp "${holder}:/app/$Compose" "$Compose.download" *> $null
$copied = $LASTEXITCODE
& docker rm $holder *> $null
if ($copied -ne 0) { Fail "$image carries no $Compose; releases before 0.2.0 cannot be installed this way" }
Move-Item -Force "$Compose.download" $Compose

# Обновлятор установки на время установщика стоит — как в `install.sh` (TRK-131): его
# проверка, пришедшаяся на `pull` и `up` установщика, звала бы свой `up`, и два compose
# останавливали бы контейнеры друг друга. Идущую проверку он доводит до конца: её видно по
# файлу `/tmp/checking` в контейнере, а у обновлятора прежних выпусков — по процессу
# `docker` в нём. Запускает его снова `up` установщика, а если установщик упал раньше —
# `finally`: остановленный руками контейнер Docker сам уже не поднимет.
# `Continue` внутри функции: stderr внешней команды при `Stop` в PowerShell 5.1 — исключение.
function Stop-Updater {
    $ErrorActionPreference = 'Continue'
    $id = (& docker compose ps -q updater 2>$null | Out-String).Trim()
    if (-not $id) { return '' }
    for ($i = 0; $i -lt 120; $i++) {
        & docker exec $id test -e /tmp/checking *> $null
        $busy = $LASTEXITCODE -eq 0
        if (-not $busy) {
            $busy = & docker top $id -o 'pid,comm' 2>$null | Select-Object -Skip 1 |
                Where-Object { ($_.Trim() -split '\s+')[1] -like 'docker*' }
        }
        if (-not $busy) { break }
        if ($i -eq 0) { Write-Host 'Waiting for the updater to finish its check...' -ForegroundColor White }
        Start-Sleep -Seconds 5
    }
    & docker stop $id *> $null
    return $id
}
$updater = Stop-Updater

try {
    Write-Host 'Starting Casefile (the first run downloads the images)...' -ForegroundColor White
    Invoke-Docker compose pull --quiet
    Invoke-Docker compose up -d --remove-orphans
} finally {
    if ($updater) { & docker start $updater *> $null; $global:LASTEXITCODE = 0 }
}

# Токен агента лежит в томе установки; читается разовым контейнером и попадает только в
# это окно — ни в журнал, ни в файл на диске.
$token = (& docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $token) {
    Fail 'the installation did not issue an agent token; see: docker compose logs agent-token'
}

# Адрес MCP спрашивается у самой установки, а не собирается из порта: правило адреса
# (`Settings.effective_mcp_public_url`, оно же отдаёт интерфейсу `GET
# /api/v1/installation`) живёт одним местом, и установщик не держит вторую его копию,
# которая разошлась бы при заданном `TRACKER_MCP_PUBLIC_URL` (TRK-71).
$mcpUrl = (& docker compose run --rm --no-deps -T --entrypoint python api -c `
    'from app.core.config import get_settings; print(get_settings().effective_mcp_public_url)' `
    | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $mcpUrl) {
    Fail 'the installation did not report its MCP address; see: docker compose logs api'
}
$script:PluginUrl = $mcpUrl

# Тот же порядок, что у compose и уже у `$registry`/`$version` выше: окружение, затем
# `.env`, затем умолчание (TRK-169: заданный установщику `CASEFILE_PORT` двигал реальную
# публикацию порта, а напечатанный адрес брался только из `.env`).
$uiPort = if ($env:CASEFILE_PORT) { $env:CASEFILE_PORT } else { Get-Setting 'CASEFILE_PORT' '8080' }

Write-Host ''
Write-Host 'Casefile is running.' -ForegroundColor Green
Write-Host ''
Write-Host "  Board:  http://localhost:$uiPort"
Write-Host "  MCP:    $mcpUrl"
Write-Host ''
if ($SkillOn) {
    try { Install-Skills } catch { Write-Host "casefile: the skill step failed; the installation itself is done. $_" -ForegroundColor Red }
}
# Подключение — по блоку на харнесс, как в `install.sh` (TRK-406, TRK-452). Claude Code и
# Codex подключены плагином и входят по OAuth: токена для них нет нигде. Ключ агента
# печатается только харнессам без OAuth. Команды дословно те же, что в `install.sh` и
# `docs/agent-install.md`; `tests/test_installers.py` сверяет их.
Write-Host 'Claude Code:' -ForegroundColor White
if ($script:SkillSkipped) {
    Write-Host '  The plugin is not installed: you skipped that step. It carries the skill and the connection'
    Write-Host "  to $mcpUrl; once installed, sign in with: claude mcp login plugin:casefile:casefile"
} else {
    Write-Host "  The plugin carries the skill and the connection to $mcpUrl; the sign-in is OAuth,"
    Write-Host '  no token in any file. If it did not run above: claude mcp login plugin:casefile:casefile'
}
Write-Host '  Without the installer: claude plugin marketplace add azimov777/casefile#plugin'
Write-Host "  claude plugin install casefile@casefile --scope user --config casefile_url=$mcpUrl"
Write-Host ''
Write-Host 'Codex:' -ForegroundColor White
if ($script:SkillSkipped) {
    Write-Host '  The plugin is not installed: you skipped that step. Once installed, sign in with: codex mcp login casefile'
} else {
    Write-Host "  The plugin carries the skill and the connection to $mcpUrl; the sign-in is OAuth."
    Write-Host '  If it did not run above: codex mcp login casefile'
}
Write-Host '  Without the installer: codex plugin marketplace add azimov777/casefile --ref plugin'
Write-Host '  codex plugin add casefile@casefile'
Write-Host ''
Write-Host 'Claude Desktop (the chat app on macOS and Windows; OAuth, no token):' -ForegroundColor White
Write-Host '  The Casefile extension: https://github.com/azimov777/casefile/releases/latest/download/casefile.mcpb'
Write-Host '  Double-click it (or Settings > Extensions > Advanced settings > Install Extension...), keep or set'
Write-Host "  the address $mcpUrl and sign in on the page its first connection opens; it works while"
Write-Host '  this installation runs. No Node.js needed: the extension runs on the one inside Claude Desktop.'
Write-Host ''
Write-Host 'Hermes (OAuth, no token):' -ForegroundColor White
Write-Host '  Add to ~/.hermes/config.yaml:'
Write-Host '    mcp_servers:'
Write-Host '      casefile:'
Write-Host "        url: `"$mcpUrl`""
Write-Host '        auth: oauth'
Write-Host '  The sign-in page opens on the first connection, or: hermes mcp login casefile'
Write-Host '  hermes skills install azimov777/casefile/skills/casefile'
Write-Host ''
Write-Host 'OpenCode (OAuth, no token):' -ForegroundColor White
Write-Host '  Add to opencode.json (or ~/.config/opencode/opencode.json):'
Write-Host "    {`"mcp`": {`"casefile`": {`"type`": `"remote`", `"url`": `"$mcpUrl`"}}}"
Write-Host '  Then sign in once: opencode mcp auth casefile'
if (-not $script:SkillSkipped) { Write-Host '  The skill is the one in ~/.agents/skills/casefile that the step above installed.' }
Write-Host ''
Write-Host 'Any other MCP client without OAuth (Cursor, ...), or a journal watcher between sessions:' -ForegroundColor White
Write-Host "  URL     $mcpUrl"
Write-Host "  Header  Authorization: Bearer $token"
Write-Host "  The key lives in the installation; read it again with (in $Dir):"
Write-Host '    docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token'
Write-Host '  npx skills add azimov777/casefile#stable'
Write-Host ''
Write-Host 'The skill teaches an agent how to work in Casefile. A running session picks up a new'
Write-Host 'plugin after a restart or /reload-plugins. Steps and updates: docs/agent-install.md'
Write-Host '(https://raw.githubusercontent.com/azimov777/casefile/main/docs/agent-install.md).'
Write-Host ''

# Текст двух фраз повторяет `app/domain/agent_phrases.py` (`AGENT_PHRASES`) дословно:
# это одна из копий, и сверяет их сплошная проверка множеств, а не вычитка
# (`docs/CONVENTIONS.md`, раздел про документацию; `tests/test_agent_phrases_everywhere.py`,
# TRK-367). Адрес в последней строке — тот же порт, что и строка `Board:` выше, плюс
# `/start`: там те же фразы стоят на языке человека, с копированием по кнопке.
Write-Host 'Tell your agent what to do:' -ForegroundColor White
Write-Host '  Have work to hand over? Say:'
Write-Host ('    File tasks in Casefile for my work: a project for it if there is none yet, and tasks with all their sections and checks, each small enough for one agent to finish in one go, each naming its environment in `context` ' + [char]0x2014 + ' where the work lives and how to check it is done. Don''t start the work itself; if I haven''t described it yet, ask me.')
Write-Host '  Then, in a new agent session, say:'
Write-Host '    Carry out the tasks for this work from the Casefile tracker. Hand them to agents, one task per agent, to save your own context, and give them cheaper models where those cope.'
Write-Host "  The same phrases with copy buttons, in your language: http://localhost:$uiPort/start"
Write-Host ''

Write-Host 'Another machine whose agents will connect to a Casefile server gets the plugin and the sign-in with'
Write-Host '(the address must be https unless it is localhost):'
Write-Host '  curl -fsSL https://raw.githubusercontent.com/azimov777/casefile/main/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=https://casefile.example.com/mcp sh'
Write-Host '  (Windows PowerShell: $env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL=''https://casefile.example.com/mcp''; irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex)'
Write-Host ''

Write-AutoUpdateOutro
