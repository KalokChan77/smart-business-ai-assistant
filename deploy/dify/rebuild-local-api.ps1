[CmdletBinding()]
param(
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location $PSScriptRoot

$composeFiles = @(
    "compose",
    "-f", "docker-compose.yaml",
    "-f", "docker-compose.smart-business.yaml",
    "--profile", "collaboration"
)

function Invoke-DifyCompose {
    param([Parameter(Mandatory = $true)][string[]]$ArgumentList)
    & docker.exe @composeFiles @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Dify Docker Compose command failed."
    }
}

Invoke-DifyCompose -ArgumentList @("config", "--quiet")
Invoke-DifyCompose -ArgumentList @("build", "api")
Invoke-DifyCompose -ArgumentList @(
    "up", "-d", "--no-deps", "--force-recreate",
    "api", "worker", "worker_beat", "api_websocket"
)
Invoke-DifyCompose -ArgumentList @("restart", "nginx")

$apiContainer = & docker.exe @composeFiles ps -q api
if (($LASTEXITCODE -ne 0) -or (-not $apiContainer)) {
    throw "Dify API container was not created."
}
$apiContainer = ([string]$apiContainer).Trim()

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$health = "none"
while ((Get-Date) -lt $deadline) {
    $health = & docker.exe inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" $apiContainer
    if (([string]$health).Trim() -eq "healthy") {
        break
    }
    Start-Sleep -Seconds 1
}

if (([string]$health).Trim() -ne "healthy") {
    & docker.exe logs --tail 120 $apiContainer
    throw "Dify API did not become healthy."
}

Invoke-DifyCompose -ArgumentList @(
    "exec", "-T", "api", "/app/api/.venv/bin/python",
    "-c", 'import jieba; print("jieba import: PASS")'
)
Invoke-DifyCompose -ArgumentList @("ps", "api", "worker", "worker_beat", "api_websocket", "nginx")
