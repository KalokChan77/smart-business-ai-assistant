[CmdletBinding()]
param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"

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

function New-Python312VirtualEnvironment {
    param([Parameter(Mandatory = $true)][string]$Destination)

    $launcherCandidates = @()
    $launcherCommand = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $launcherCommand) {
        $launcherCandidates += $launcherCommand.Source
    }

    $knownLauncher = Join-Path $env:LOCALAPPDATA "Programs\Python\Launcher\py.exe"
    if ((Test-Path -LiteralPath $knownLauncher) -and ($launcherCandidates -notcontains $knownLauncher)) {
        $launcherCandidates += $knownLauncher
    }

    foreach ($launcher in $launcherCandidates) {
        & $launcher -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Invoke-Checked -FilePath $launcher -ArgumentList @("-3.12", "-m", "venv", $Destination)
            return
        }
    }

    foreach ($name in @("python3.12.exe", "python.exe")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -eq $command) {
            continue
        }
        $version = & $command.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if (($LASTEXITCODE -eq 0) -and (([string]$version).Trim() -eq "3.12")) {
            Invoke-Checked -FilePath $command.Source -ArgumentList @("-m", "venv", $Destination)
            return
        }
    }

    throw @"
Python 3.12 was not found. Install it, reopen PowerShell, and rerun this script:
  winget install --id Python.Python.3.12 --exact --scope user
"@
}

function New-RandomHex {
    param([int]$ByteCount = 24)

    $bytes = New-Object byte[] $ByteCount
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    }
    finally {
        $generator.Dispose()
    }
    return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

Write-Host "[1/4] Preparing Python 3.12 virtual environment..."
if (-not (Test-Path -LiteralPath $venvPython)) {
    New-Python312VirtualEnvironment -Destination $venvDir
}

Invoke-Checked -FilePath $venvPython -ArgumentList @("-m", "pip", "install", "--upgrade", "pip")
Invoke-Checked -FilePath $venvPython -ArgumentList @(
    "-m", "pip", "install", "--editable", ((Join-Path $projectRoot "backend") + "[dev]")
)

Write-Host "[2/4] Preparing local environment file..."
$envFile = Join-Path $projectRoot ".env"
if (-not (Test-Path -LiteralPath $envFile)) {
    $postgresPassword = New-RandomHex 18
    $redisPassword = New-RandomHex 18
    $jwtSecret = New-RandomHex 32
    $envContent = Get-Content -LiteralPath (Join-Path $projectRoot ".env.example") -Raw -Encoding utf8
    $envContent = $envContent -replace '(?m)^APP_POSTGRES_PASSWORD=.*$', "APP_POSTGRES_PASSWORD=$postgresPassword"
    $envContent = $envContent -replace '(?m)^APP_REDIS_PASSWORD=.*$', "APP_REDIS_PASSWORD=$redisPassword"
    $envContent = $envContent -replace '(?m)^DATABASE_URL=.*$', "DATABASE_URL=postgresql+psycopg://smart_business_ai:${postgresPassword}@127.0.0.1:15432/smart_business_ai"
    $envContent = $envContent -replace '(?m)^REDIS_URL=.*$', "REDIS_URL=redis://:${redisPassword}@127.0.0.1:16379/0"
    $envContent = $envContent -replace '(?m)^JWT_SECRET_KEY=.*$', "JWT_SECRET_KEY=$jwtSecret"
    Write-Utf8NoBom -Path $envFile -Content $envContent
    Write-Host "Created .env with random local database, Redis, and JWT secrets."
}
else {
    Write-Host "Keeping the existing .env unchanged."
}

Write-Host "[3/4] Checking Docker CLI..."
if ($null -eq (Get-Command "docker.exe" -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is not installed or docker.exe is not on PATH."
}
& docker compose version
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose is unavailable."
}

Write-Host "[4/4] Preparing frontend dependencies..."
if (-not $SkipFrontend) {
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $npm) {
        throw "npm.cmd was not found. Install Node.js 20.19+ or 22.12+."
    }
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        Invoke-Checked -FilePath $npm.Source -ArgumentList @("ci")
    }
    finally {
        Pop-Location
    }
}
else {
    Write-Host "Frontend dependency installation was skipped."
}

Write-Host ""
Write-Host "Windows setup is complete."
Write-Host "Before using AI/Dify features, edit .env and add the required API keys."
Write-Host "Start the local stack with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\dev_up.ps1"
