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

$ErrorActionPreference = 'Stop'

$Dir = if ($env:CASEFILE_DIR) { $env:CASEFILE_DIR } else { Join-Path $HOME 'casefile' }
$Compose = 'docker-compose.prod.yml'

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

$uiPort = Get-Setting 'CASEFILE_PORT' '8080'

Write-Host ''
Write-Host 'Casefile is running.' -ForegroundColor Green
Write-Host ''
Write-Host "  Board:  http://localhost:$uiPort"
Write-Host "  MCP:    $mcpUrl"
Write-Host ''
Write-Host 'Connect Claude Code:' -ForegroundColor White
Write-Host "  claude mcp add --transport http --scope user casefile $mcpUrl --header `"Authorization: Bearer $token`""
Write-Host ''
Write-Host 'Any other MCP client (Codex, Cursor, ...):' -ForegroundColor White
Write-Host "  URL     $mcpUrl"
Write-Host "  Header  Authorization: Bearer $token"
Write-Host ''
Write-Host "Updates arrive by themselves: Casefile checks for a new release every hour. Files and data: $Dir"
