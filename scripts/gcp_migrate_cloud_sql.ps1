Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigPath = Join-Path $Root "infrastructure\cloud-sql.env"
$BackendPath = Join-Path $Root "backend"

function Read-DotEnv($Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Path. Copy infrastructure\cloud-sql.env.example to infrastructure\cloud-sql.env and fill it first."
    }
    $values = @{}
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
        $parts = $line.Split("=", 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Require-Value($Values, $Name) {
    if (-not $Values.ContainsKey($Name) -or -not $Values[$Name] -or $Values[$Name].StartsWith("CHANGE_ME")) {
        throw "Fill $Name in infrastructure\cloud-sql.env first."
    }
    return $Values[$Name]
}

$cfg = Read-DotEnv $ConfigPath
$ConnectionName = Require-Value $cfg "CLOUD_SQL_CONNECTION_NAME"
$DatabaseName = Require-Value $cfg "DATABASE_NAME"
$DatabaseUser = Require-Value $cfg "DATABASE_USER"
$DatabasePassword = Require-Value $cfg "DATABASE_PASSWORD"
$ProxyPath = Require-Value $cfg "CLOUD_SQL_PROXY_PATH"
$ProxyPort = if ($cfg["CLOUD_SQL_PROXY_PORT"]) { [int]$cfg["CLOUD_SQL_PROXY_PORT"] } else { 5433 }

if (-not (Get-Command $ProxyPath -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path -LiteralPath $ProxyPath)) {
        throw "Cloud SQL Auth Proxy not found at '$ProxyPath'. Install it and set CLOUD_SQL_PROXY_PATH in infrastructure\cloud-sql.env."
    }
}

$existing = Get-NetTCPConnection -LocalPort $ProxyPort -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Starting Cloud SQL Auth Proxy on 127.0.0.1:$ProxyPort"
    Start-Process -FilePath $ProxyPath -ArgumentList "$ConnectionName --address 127.0.0.1 --port $ProxyPort" -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 5
}

$env:DATABASE_URL = "postgresql+psycopg://$DatabaseUser`:$DatabasePassword@127.0.0.1:$ProxyPort/$DatabaseName"
$env:APP_ENV = "development"

Push-Location $BackendPath
try {
    Write-Host "Running Alembic migrations against Cloud SQL"
    python -m alembic upgrade head
    Write-Host "Checking Cloud SQL database"
    python -m app.scripts.check_database
}
finally {
    Pop-Location
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:\APP_ENV -ErrorAction SilentlyContinue
}
