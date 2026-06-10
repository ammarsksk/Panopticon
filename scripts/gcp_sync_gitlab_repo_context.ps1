param(
    [int]$Limit = 20,
    [int]$MergeRequestLimit = 20,
    [int]$PipelineLimit = 10,
    [int]$JobLimit = 20,
    [int]$RepoFileLimit = 120
)

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
$GitLabToken = Require-Value $cfg "GITLAB_TOKEN"
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

$env:APP_ENV = "development"
$env:DATABASE_URL = "postgresql+psycopg://$DatabaseUser`:$DatabasePassword@127.0.0.1:$ProxyPort/$DatabaseName"
$env:GITLAB_TOKEN = $GitLabToken
$env:REPO_INDEX_ON_SYNC = "true"
$env:REPO_INDEX_FILE_LIMIT = "$RepoFileLimit"
$env:REPO_INDEX_CHUNK_CHARS = "2800"
$env:REPO_INDEX_MAX_CHUNKS_PER_FILE = "24"
$env:REPO_EMBEDDING_PROVIDER = "vertex"
$env:REPO_EMBEDDING_MODEL = "gemini-embedding-001"
$env:REPO_EMBEDDING_DIMENSIONS = "768"
$env:REPO_EMBEDDING_FALLBACK_TO_LOCAL = "false"
$env:REPO_PGVECTOR_ENABLED = "true"
$env:GOOGLE_GENAI_USE_VERTEXAI = "true"
$env:GOOGLE_CLOUD_PROJECT = if ($cfg["PROJECT_ID"]) { $cfg["PROJECT_ID"] } else { "panopticon-495816" }
$env:GOOGLE_CLOUD_LOCATION = "global"

Push-Location $BackendPath
try {
    python -m app.scripts.sync_gitlab_repo_context `
        --limit $Limit `
        --merge-request-limit $MergeRequestLimit `
        --pipeline-limit $PipelineLimit `
        --job-limit $JobLimit
}
finally {
    Pop-Location
    foreach ($name in @(
        "APP_ENV",
        "DATABASE_URL",
        "GITLAB_TOKEN",
        "REPO_INDEX_ON_SYNC",
        "REPO_INDEX_FILE_LIMIT",
        "REPO_INDEX_CHUNK_CHARS",
        "REPO_INDEX_MAX_CHUNKS_PER_FILE",
        "REPO_EMBEDDING_PROVIDER",
        "REPO_EMBEDDING_MODEL",
        "REPO_EMBEDDING_DIMENSIONS",
        "REPO_EMBEDDING_FALLBACK_TO_LOCAL",
        "REPO_PGVECTOR_ENABLED",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION"
    )) {
        Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
    }
}
