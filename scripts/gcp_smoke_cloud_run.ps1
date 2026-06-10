param(
    [string]$BackendUrl = "https://panopticon-backend-226094931757.us-central1.run.app",
    [string]$FrontendUrl = "https://panopticon-frontend-226094931757.us-central1.run.app"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigPath = Join-Path $Root "infrastructure\cloud-sql.env"

function Read-DotEnv($Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing $Path."
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

$cfg = Read-DotEnv $ConfigPath
$Token = $cfg["AGENT_RUNTIME_TOKEN"]
if (-not $Token -or $Token.StartsWith("CHANGE_ME")) {
    throw "Fill AGENT_RUNTIME_TOKEN in infrastructure\cloud-sql.env first."
}

$temp = Join-Path $env:TEMP "panopticon-cloudrun-smoke.json"
$payloadFile = Join-Path $env:TEMP "panopticon-mcp-payload.json"

Write-Host "Backend health"
curl.exe -s -f "$BackendUrl/health"
Write-Host ""

Write-Host "Frontend landing page"
curl.exe -s -I "$FrontendUrl" | Select-Object -First 1

Write-Host "AI integration status"
curl.exe -s -f "$BackendUrl/api/integrations/ai"
Write-Host ""

Write-Host "Authenticated tool list"
$status = curl.exe -s -o $temp -w "%{http_code}" -H "Authorization: Bearer $Token" "$BackendUrl/api/agent/tools"
Write-Host "HTTP $status"
if ($status -ne "200") {
    Get-Content -LiteralPath $temp
    exit 1
}
$json = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
Write-Host "tools=$($json.tools.Count)"

Write-Host "MCP tools/list"
[System.IO.File]::WriteAllText($payloadFile, '{"jsonrpc":"2.0","id":"smoke-tools","method":"tools/list","params":{}}')
$status = curl.exe -s -o $temp -w "%{http_code}" -H "Authorization: Bearer $Token" -H "Content-Type: application/json" --data-binary "@$payloadFile" "$BackendUrl/mcp"
Write-Host "HTTP $status"
if ($status -ne "200") {
    Get-Content -LiteralPath $temp
    exit 1
}
$json = Get-Content -LiteralPath $temp -Raw | ConvertFrom-Json
Write-Host "mcp_tools=$($json.result.tools.Count)"

Write-Host "OAuth redirect generation"
$googleStatus = curl.exe -s -o $temp -w "%{http_code}" "$BackendUrl/api/auth/google/start?redirect_after=$FrontendUrl/dashboard"
if ($googleStatus -ne "307") {
    Write-Host "google_oauth_start=HTTP $googleStatus"
    Get-Content -LiteralPath $temp
    exit 1
}
Write-Host "google_oauth_start=HTTP $googleStatus"

$gitlabStatus = curl.exe -s -o $temp -w "%{http_code}" -H "Authorization: Bearer $Token" "$BackendUrl/api/integrations/gitlab/connect?redirect_after=$FrontendUrl/projects"
if ($gitlabStatus -ne "307") {
    Write-Host "gitlab_oauth_connect=HTTP $gitlabStatus"
    Get-Content -LiteralPath $temp
    exit 1
}
Write-Host "gitlab_oauth_connect=HTTP $gitlabStatus"

$slackStatus = curl.exe -s -o $temp -w "%{http_code}" -H "Authorization: Bearer $Token" "$BackendUrl/api/integrations/slack/connect?redirect_after=$FrontendUrl/dashboard"
if ($slackStatus -ne "307") {
    Write-Host "slack_oauth_connect=HTTP $slackStatus"
    Get-Content -LiteralPath $temp
    exit 1
}
Write-Host "slack_oauth_connect=HTTP $slackStatus"
