[CmdletBinding()]
param(
    [switch]$SkipDemoSeed,
    [switch]$ResetDemoPassword,
    [int]$BackendPort = 0,
    [int]$FrontendPort = 0,
    [ValidateRange(10, 300)][int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$composeFile = Join-Path $projectRoot "deploy\app-compose.yml"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runDir = Join-Path $projectRoot ".tmp"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($ArgumentList -join ' ')"
    }
}

function Invoke-AppCompose {
    param([Parameter(Mandatory = $true)][string[]]$ArgumentList)

    $arguments = @("compose", "--env-file", $envFile, "-f", $composeFile) + $ArgumentList
    Invoke-Checked -FilePath "docker.exe" -ArgumentList $arguments
}

function Resolve-DevPort {
    param(
        [Parameter(Mandatory = $true)][int]$RequestedPort,
        [Parameter(Mandatory = $true)][string]$VariableName,
        [Parameter(Mandatory = $true)][int]$DefaultPort
    )

    $resolvedPort = $RequestedPort
    if ($resolvedPort -eq 0) {
        $pattern = "^\s*$([regex]::Escape($VariableName))\s*="
        $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match $pattern } | Select-Object -First 1
        if ($line) {
            $rawValue = ($line -split "=", 2)[1].Trim()
            if (-not [int]::TryParse($rawValue, [ref]$resolvedPort)) {
                throw "$VariableName must be a valid integer port."
            }
        }
        else {
            $resolvedPort = $DefaultPort
        }
    }
    if (($resolvedPort -lt 1) -or ($resolvedPort -gt 65535)) {
        throw "$VariableName must be between 1 and 65535."
    }
    return $resolvedPort
}

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$ExpectedCommand
    )

    if (-not (Test-Path -LiteralPath $PidFile)) {
        return
    }

    $rawProcessId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $processId = 0
    if ([int]::TryParse($rawProcessId, [ref]$processId)) {
        $managed = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if (($null -ne $managed) -and ($managed.CommandLine -match $ExpectedCommand)) {
            & taskkill.exe /PID $processId /T /F *> $null
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
}

function Assert-PortAvailable {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listeners) {
        $owners = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "Port $Port is already in use (PID: $owners). Stop that process and retry."
    }
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string[]]$LogFiles
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 750
        }
    }

    Write-Host "$Name did not become ready within $TimeoutSeconds seconds. Recent logs:"
    foreach ($logFile in $LogFiles) {
        if (Test-Path -LiteralPath $logFile) {
            Write-Host "--- $logFile"
            Get-Content -LiteralPath $logFile -Tail 40
        }
    }
    throw "$Name startup timed out."
}

if (-not (Test-Path -LiteralPath $envFile)) {
    throw "Missing .env. Run .\scripts\setup_windows.ps1 first."
}
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Missing .venv. Run .\scripts\setup_windows.ps1 first."
}
if ($null -eq (Get-Command "docker.exe" -ErrorAction SilentlyContinue)) {
    throw "docker.exe was not found. Install Docker Desktop first."
}
$npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
if ($null -eq $npm) {
    throw "npm.cmd was not found. Install Node.js 20.19+ or 22.12+."
}

$backendPort = Resolve-DevPort -RequestedPort $BackendPort -VariableName "APP_BACKEND_PORT" -DefaultPort 18000
$frontendPort = Resolve-DevPort -RequestedPort $FrontendPort -VariableName "APP_FRONTEND_PORT" -DefaultPort 5173

& docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is installed but its Linux engine is not running. Start Docker Desktop and retry."
}

Set-Location $projectRoot
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

Write-Host "[1/5] Starting PostgreSQL and Redis..."
Invoke-AppCompose -ArgumentList @("up", "-d")

Write-Host "[2/5] Waiting for PostgreSQL..."
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$databaseHealthy = $false
while ((Get-Date) -lt $deadline) {
    $health = & docker inspect --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" smart-business-postgres 2>$null
    if (($LASTEXITCODE -eq 0) -and (([string]$health).Trim() -eq "healthy")) {
        $databaseHealthy = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $databaseHealthy) {
    Invoke-AppCompose -ArgumentList @("ps")
    throw "PostgreSQL did not become healthy within $TimeoutSeconds seconds."
}

Write-Host "[3/5] Applying database migrations..."
Push-Location (Join-Path $projectRoot "backend")
try {
    Invoke-Checked -FilePath $venvPython -ArgumentList @("-m", "alembic", "upgrade", "head")
}
finally {
    Pop-Location
}

$skipSeed = $SkipDemoSeed -or ($env:SKIP_DEMO_SEED -eq "1")
if (-not $skipSeed) {
    Write-Host "[4/5] Creating or refreshing the four demo accounts..."
    if (-not $env:DEMO_PASSWORD) {
        Write-Host "You will be prompted for a shared demo password (minimum 8 characters)."
    }
    $seedArguments = @((Join-Path $projectRoot "backend\scripts\bootstrap_demo_tenant.py"))
    if ($ResetDemoPassword -or ($env:RESET_DEMO_PASSWORD -eq "1")) {
        $seedArguments += "--reset-password"
    }
    if ($env:DEMO_TENANT_ID) {
        $seedArguments += @("--tenant-id", $env:DEMO_TENANT_ID)
    }
    Invoke-Checked -FilePath $venvPython -ArgumentList $seedArguments
}
else {
    Write-Host "[4/5] Demo account initialization skipped."
}

Write-Host "[5/5] Starting FastAPI and Vue development servers..."
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "frontend\node_modules"))) {
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        Invoke-Checked -FilePath $npm.Source -ArgumentList @("ci")
    }
    finally {
        Pop-Location
    }
}

$backendPidFile = Join-Path $runDir "backend.pid"
$frontendPidFile = Join-Path $runDir "frontend.pid"
Stop-ManagedProcess -PidFile $backendPidFile -ExpectedCommand '(uvicorn|scripts\.run_dev_server)'
Stop-ManagedProcess -PidFile $frontendPidFile -ExpectedCommand 'npm(\.cmd)?"?\s+run\s+dev'
Start-Sleep -Milliseconds 500
Assert-PortAvailable -Port $backendPort
Assert-PortAvailable -Port $frontendPort

$backendOut = Join-Path $runDir "backend-dev.out.log"
$backendErr = Join-Path $runDir "backend-dev.err.log"
$frontendOut = Join-Path $runDir "frontend-dev.out.log"
$frontendErr = Join-Path $runDir "frontend-dev.err.log"
Remove-Item -LiteralPath $backendOut, $backendErr, $frontendOut, $frontendErr -Force -ErrorAction SilentlyContinue

$backendProcess = Start-Process `
    -FilePath $venvPython `
    -ArgumentList @("-m", "scripts.run_dev_server", "--port", ([string]$backendPort)) `
    -WorkingDirectory (Join-Path $projectRoot "backend") `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -WindowStyle Hidden `
    -PassThru
$backendProcess.Id | Set-Content -LiteralPath $backendPidFile -Encoding ascii

$previousProxyTarget = $env:VITE_API_PROXY_TARGET
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:$backendPort"
$frontendProcess = Start-Process `
    -FilePath $npm.Source `
    -ArgumentList @("run", "dev", "--", "--port", ([string]$frontendPort)) `
    -WorkingDirectory (Join-Path $projectRoot "frontend") `
    -RedirectStandardOutput $frontendOut `
    -RedirectStandardError $frontendErr `
    -WindowStyle Hidden `
    -PassThru
$env:VITE_API_PROXY_TARGET = $previousProxyTarget
$frontendProcess.Id | Set-Content -LiteralPath $frontendPidFile -Encoding ascii

Wait-ForHttp -Name "FastAPI" -Url "http://127.0.0.1:$backendPort/api/v1/health" -LogFiles @($backendOut, $backendErr)
Wait-ForHttp -Name "Vue" -Url "http://127.0.0.1:$frontendPort/" -LogFiles @($frontendOut, $frontendErr)

Write-Host ""
Write-Host "Local development stack is ready:"
Write-Host "  Frontend:  http://127.0.0.1:$frontendPort"
Write-Host "  API docs:  http://127.0.0.1:$backendPort/docs"
Write-Host "  Health:    http://127.0.0.1:$backendPort/api/v1/health"
Write-Host "  Readiness: http://127.0.0.1:$backendPort/api/v1/health/ready"
Write-Host "  Logs:      $runDir"
Write-Host ""
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File .\scripts\dev_down.ps1"
Write-Host "Dify remains a separate optional stack under dify-self-host."
