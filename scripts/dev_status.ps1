[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $projectRoot ".tmp"
$envFile = Join-Path $projectRoot ".env"
$composeFile = Join-Path $projectRoot "deploy\app-compose.yml"

function Get-DevPort {
    param(
        [Parameter(Mandatory = $true)][string]$VariableName,
        [Parameter(Mandatory = $true)][int]$DefaultPort
    )

    if (-not (Test-Path -LiteralPath $envFile)) {
        return $DefaultPort
    }
    $pattern = "^\s*$([regex]::Escape($VariableName))\s*="
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match $pattern } | Select-Object -First 1
    if (-not $line) {
        return $DefaultPort
    }
    $resolvedPort = 0
    $rawValue = ($line -split "=", 2)[1].Trim()
    if ([int]::TryParse($rawValue, [ref]$resolvedPort)) {
        return $resolvedPort
    }
    return $DefaultPort
}

$backendPort = Get-DevPort -VariableName "APP_BACKEND_PORT" -DefaultPort 18000
$frontendPort = Get-DevPort -VariableName "APP_FRONTEND_PORT" -DefaultPort 5173

Write-Host "== Docker dependencies =="
if ((Test-Path -LiteralPath $envFile) -and (Get-Command "docker.exe" -ErrorAction SilentlyContinue)) {
    & docker.exe compose --env-file $envFile -f $composeFile ps
}
else {
    Write-Host ".env or docker.exe is unavailable."
}

Write-Host ""
Write-Host "== Managed development processes =="
foreach ($name in @("backend", "frontend")) {
    $pidFile = Join-Path $runDir "$name.pid"
    $status = "stopped"
    if (Test-Path -LiteralPath $pidFile) {
        $rawProcessId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        $processId = 0
        if ([int]::TryParse($rawProcessId, [ref]$processId)) {
            if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
                $status = "running (PID $processId)"
            }
        }
    }
    Write-Host ("{0}: {1}" -f $name, $status)
}

Write-Host ""
Write-Host "== HTTP =="
foreach ($url in @(
    "http://127.0.0.1:$backendPort/api/v1/health",
    "http://127.0.0.1:$backendPort/api/v1/health/ready",
    "http://127.0.0.1:$frontendPort/"
)) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        Write-Host "$url -> HTTP $($response.StatusCode)"
    }
    catch {
        $statusCode = $null
        if ($_.Exception.PSObject.Properties.Name -contains "Response") {
            $response = $_.Exception.Response
            if (($null -ne $response) -and ($null -ne $response.StatusCode)) {
                $statusCode = [int]$response.StatusCode
            }
        }
        if ($statusCode) {
            Write-Host "$url -> HTTP $statusCode"
        }
        else {
            Write-Host "$url -> unavailable"
        }
    }
}
