# Casefile installer for Windows (PowerShell 5.1 and 7):
#
#   irm https://raw.githubusercontent.com/azimov777/casefile/main/install.ps1 | iex
#
# Близнец `install.sh`: те же шаги в том же порядке — кладёт `docker-compose.prod.yml` в
# каталог установки (`%USERPROFILE%\casefile`), поднимает контур и печатает, куда открыть
# интерфейс и чем подключить агента. Повторный запуск — это обновление.
#
# Переменные (все необязательны):
#   CASEFILE_DIR     каталог установки
#   CASEFILE_SOURCE  откуда брать файлы установки, по умолчанию raw-адрес main на GitHub

$ErrorActionPreference = 'Stop'

$Dir = if ($env:CASEFILE_DIR) { $env:CASEFILE_DIR } else { Join-Path $HOME 'casefile' }
$Source = if ($env:CASEFILE_SOURCE) { $env:CASEFILE_SOURCE } else { 'https://raw.githubusercontent.com/azimov777/casefile/main' }
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

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
Set-Location $Dir

Write-Host "Installing Casefile into $Dir" -ForegroundColor White
$ProgressPreference = 'SilentlyContinue'
Invoke-WebRequest -UseBasicParsing -Uri "$Source/$Compose" -OutFile "$Compose.download"
Move-Item -Force "$Compose.download" $Compose

# `.env` заводится один раз и дальше принадлежит человеку. Пишется без BOM: `Set-Content
# -Encoding UTF8` в PowerShell 5.1 ставит его в начало файла, и compose прочитал бы первую
# переменную с невидимым символом в имени.
if (-not (Test-Path .env)) {
    $lines = @("COMPOSE_FILE=$Compose", "CASEFILE_COMPOSE_URL=$Source/$Compose")
    [System.IO.File]::WriteAllLines((Join-Path $Dir '.env'), $lines)
}

Write-Host 'Starting Casefile (the first run downloads the images)...' -ForegroundColor White
Invoke-Docker compose pull --quiet
Invoke-Docker compose up -d --remove-orphans

# Токен агента лежит в томе установки; читается разовым контейнером и попадает только в
# это окно — ни в журнал, ни в файл на диске.
$token = (& docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $token) {
    Fail 'the installation did not issue an agent token; see: docker compose logs agent-token'
}

$uiPort = Get-Setting 'CASEFILE_PORT' '8080'
$mcpPort = Get-Setting 'TRACKER_MCP_PORT' '8100'

Write-Host ''
Write-Host 'Casefile is running.' -ForegroundColor Green
Write-Host ''
Write-Host "  Board:  http://localhost:$uiPort"
Write-Host "  MCP:    http://localhost:$mcpPort/mcp"
Write-Host ''
Write-Host 'Connect Claude Code:' -ForegroundColor White
Write-Host "  claude mcp add --transport http --scope user casefile http://localhost:$mcpPort/mcp --header `"Authorization: Bearer $token`""
Write-Host ''
Write-Host 'Any other MCP client (Codex, Cursor, ...):' -ForegroundColor White
Write-Host "  URL     http://localhost:$mcpPort/mcp"
Write-Host "  Header  Authorization: Bearer $token"
Write-Host ''
Write-Host "Updates arrive by themselves every time Docker starts. Files and data: $Dir"
