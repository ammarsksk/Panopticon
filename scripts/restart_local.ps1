[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [int[]]$ExtraPorts = @(3001, 3002, 3003),
    [switch]$SkipMigrations
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$LogDir = Join-Path $Root "logs"

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Stop-PortProcess {
    param([int]$Port)

    $processIds = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -gt 0 } |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($processId in $processIds) {
        try {
            $process = Get-Process -Id $processId -ErrorAction Stop
            Write-Host "Stopping PID $processId on port $Port ($($process.ProcessName))"
            Stop-Process -Id $processId -Force -ErrorAction Stop
        } catch {
            Write-Host "Port $Port process $processId was already stopped"
        }
    }
}

function Start-LoggedProcess {
    param(
        [string]$Name,
        [string]$WorkingDirectory,
        [string]$Command,
        [string]$StdOut,
        [string]$StdErr
    )

    Write-Host "Starting $Name..."
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $Command) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdOut `
        -RedirectStandardError $StdErr `
        -PassThru

    Write-Host "$Name PID: $($process.Id)"
    return $process
}

$ports = @($BackendPort, $FrontendPort) + $ExtraPorts
foreach ($port in $ports | Select-Object -Unique) {
    Stop-PortProcess -Port $port
}

if (-not $SkipMigrations) {
    Write-Host "Running database migrations..."
    Push-Location $BackendDir
    try {
        python -m alembic upgrade head
    } finally {
        Pop-Location
    }
}

$backendOut = Join-Path $LogDir "backend.out.log"
$backendErr = Join-Path $LogDir "backend.err.log"
$frontendOut = Join-Path $LogDir "frontend.out.log"
$frontendErr = Join-Path $LogDir "frontend.err.log"

Remove-Item -Path $backendOut, $backendErr, $frontendOut, $frontendErr -Force -ErrorAction SilentlyContinue

$backendCommand = "python -m uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort"
$frontendCommand = "npm.cmd run dev -- --hostname localhost --port $FrontendPort"

$backendProcess = Start-LoggedProcess `
    -Name "Panopticon backend" `
    -WorkingDirectory $BackendDir `
    -Command $backendCommand `
    -StdOut $backendOut `
    -StdErr $backendErr

$frontendProcess = Start-LoggedProcess `
    -Name "Panopticon frontend" `
    -WorkingDirectory $FrontendDir `
    -Command $frontendCommand `
    -StdOut $frontendOut `
    -StdErr $frontendErr

Start-Sleep -Seconds 5

Write-Host ""
Write-Host "Panopticon local stack started."
Write-Host "Backend:  http://127.0.0.1:$BackendPort"
Write-Host "Frontend: http://localhost:$FrontendPort"
Write-Host "Backend logs:  $backendOut"
Write-Host "Backend errors: $backendErr"
Write-Host "Frontend logs: $frontendOut"
Write-Host "Frontend errors: $frontendErr"
Write-Host ""
Write-Host "Backend PID:  $($backendProcess.Id)"
Write-Host "Frontend PID: $($frontendProcess.Id)"
