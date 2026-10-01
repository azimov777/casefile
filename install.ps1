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
# Обе последние записываются в `.env` новой установки; без них действует `.env`
# существующей установки, а без него — умолчания compose-файла.
#   CASEFILE_SKILL     0 — не ставить скил агентам этой машины (по умолчанию 1, TRK-408)
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

$ErrorActionPreference = 'Stop'

$Dir = if ($env:CASEFILE_DIR) { $env:CASEFILE_DIR } else { Join-Path $HOME 'casefile' }
$Compose = 'docker-compose.prod.yml'
$SkillOn = $env:CASEFILE_SKILL -ne '0'
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
    return $ok
}

function Write-SkillFailed([string] $Name, [string] $Retry) {
    Write-SkillLine $Name 'failed - repeat by hand:'
    Write-Host "                $Retry"
    ($script:SkillLog -split "`r?`n" | Where-Object { $_ } | Select-Object -Last 3) |
        ForEach-Object { Write-Host "                > $_" }
}

# `"autoUpdate": true` рядом с `source` в extraKnownMarketplaces.casefile: у сторонних
# маркетплейсов Claude Code обновляет плагин сам только с ним, а флага в CLI нет (TRK-406).
# Файл переписывается, только если ключа не было; без BOM.
function Set-ClaudeAutoUpdate {
    $dir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
    $file = Join-Path $dir 'settings.json'
    if (-not (Test-Path $file)) { return $false }
    try {
        $settings = [System.IO.File]::ReadAllText($file) | ConvertFrom-Json
        $entry = $settings.extraKnownMarketplaces.casefile
        if (-not $entry) { return $false }
        if ($entry.autoUpdate -eq $true) { return $true }
        $entry | Add-Member -NotePropertyName autoUpdate -NotePropertyValue $true -Force
        $json = $settings | ConvertTo-Json -Depth 20
        [System.IO.File]::WriteAllText($file, $json + "`n", (New-Object System.Text.UTF8Encoding($false)))
        return $true
    } catch {
        return $false
    }
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
            if ($flag -and (Invoke-SkillCmd claude mcp remove $name --scope $flag)) {
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
    $src = "${SkillSource}#stable"
    $retry = "claude plugin marketplace add $src --sparse .claude-plugin skills; claude plugin install casefile@casefile --scope user --config casefile_url=$($script:PluginUrl)"
    if (-not $script:DefaultUrl) { Remove-ClaudeEntries }
    $ok = (Invoke-SkillCmd claude plugin marketplace add $src --sparse .claude-plugin skills) -and
        (Invoke-SkillCmd claude plugin marketplace update casefile) -and
        (Invoke-SkillCmd claude plugin install casefile@casefile --scope user --config "casefile_url=$($script:PluginUrl)") -and
        (Invoke-SkillCmd claude plugin update casefile@casefile)
    if (-not $ok) { Write-SkillFailed 'Claude Code' $retry; return }
    $ErrorActionPreference = 'Continue'
    $text = & claude plugin list 2>$null | Out-String
    $m = [regex]::Match($text, 'casefile@casefile[^\r\n]*[\r\n]+\s*Version:\s*(\S+)[\s\S]*?Status:\s*([^\r\n]*)')
    if (-not ($m.Success -and $m.Groups[2].Value -match 'enabled')) { Write-SkillFailed 'Claude Code' $retry; return }
    $version = $m.Groups[1].Value
    if (-not $script:DefaultUrl) { $script:LoginClaude = $true }
    if (Set-ClaudeAutoUpdate) {
        Write-SkillLine 'Claude Code' "installed $version (updates itself), connected to $($script:PluginUrl)$($script:DefaultNote)"
    } else {
        Write-SkillLine 'Claude Code' "installed $version, connected to $($script:PluginUrl)$($script:DefaultNote) (automatic updates not switched on: add `"autoUpdate`": true inside extraKnownMarketplaces.casefile in settings.json)"
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
    $retry = "codex plugin marketplace add $SkillSource --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills; codex plugin add casefile@casefile"
    if (-not $script:DefaultUrl) { Remove-CodexEntries }
    $ok = (Invoke-SkillCmd codex plugin marketplace add $SkillSource --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills) -and
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

function Install-Skills {
    $script:SkillLog = ''
    Write-Host 'Installing the Casefile skill for the agents on this machine:' -ForegroundColor White
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
    if ($script:DefaultUrl) {
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
Write-Host "  The plugin carries the skill and the connection to $mcpUrl; the sign-in is OAuth,"
Write-Host '  no token in any file. If it did not run above: claude mcp login plugin:casefile:casefile'
Write-Host '  Without the installer: claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills'
Write-Host "  claude plugin install casefile@casefile --scope user --config casefile_url=$mcpUrl"
Write-Host ''
Write-Host 'Codex:' -ForegroundColor White
Write-Host "  The plugin carries the skill and the connection to $mcpUrl; the sign-in is OAuth."
Write-Host '  If it did not run above: codex mcp login casefile'
Write-Host '  Without the installer: codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills'
Write-Host '  codex plugin add casefile@casefile'
Write-Host ''
Write-Host 'Hermes (no OAuth: a key):' -ForegroundColor White
Write-Host '  Add to ~/.hermes/config.yaml:'
Write-Host '    mcp_servers:'
Write-Host '      casefile:'
Write-Host "        url: `"$mcpUrl`""
Write-Host '        headers:'
Write-Host "          Authorization: `"Bearer $token`""
Write-Host '  hermes skills install azimov777/casefile/skills/casefile'
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

Write-Host "Updates arrive by themselves: Casefile checks for a new release every hour. Files and data: $Dir"
