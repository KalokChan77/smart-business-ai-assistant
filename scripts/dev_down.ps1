[CmdletBinding()]
param(
    [switch]$StopData
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $projectRoot ".tmp"

function Stop-ManagedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedCommand
    )

    if (-not (Test-Path -LiteralPath $PidFile)) {
        Write-Host "$Name is not managed by this script."
        return
    }

    $rawProcessId = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    $processId = 0
    if ([int]::TryParse($rawProcessId, [ref]$processId)) {
        $managed = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
        if (($null -ne $managed) -and ($managed.CommandLine -match $ExpectedCommand)) {
            & taskkill.exe /PID $processId /T /F *> $null
            Write-Host "Stopped $Name (PID $processId)."
        }
        elseif ($null -ne $managed) {
            Write-Warning "PID $processId no longer looks like the managed $Name process; it was not stopped."
        }
    }
    Remove-Item -LiteralPath $PidFile -Force
}

Stop-ManagedProcess -PidFile (Join-Path $runDir "backend.pid") -Name "FastAPI" -ExpectedCommand '(uvicorn|scripts\.run_dev_server)'
Stop-ManagedProcess -PidFile (Join-Path $runDir "frontend.pid") -Name "Vue" -ExpectedCommand 'npm(\.cmd)?"?\s+run\s+dev'

if ($StopData) {
    $envFile = Join-Path $projectRoot ".env"
    $composeFile = Join-Path $projectRoot "deploy\app-compose.yml"
    if (Test-Path -LiteralPath $envFile) {
        & docker.exe compose --env-file $envFile -f $composeFile stop
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to stop PostgreSQL/Redis."
        }
    }
}
else {
    Write-Host "PostgreSQL and Redis remain running. Add -StopData to stop them too."
}
