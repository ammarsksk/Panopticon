param(
    [string]$BackendUrl = "https://panopticon-backend-226094931757.us-central1.run.app"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RunId = [Guid]::NewGuid().ToString("N").Substring(0, 12)
$TempDir = Join-Path $env:TEMP "panopticon-auth-smoke-$RunId"
New-Item -ItemType Directory -Path $TempDir | Out-Null

$CookieJar = Join-Path $TempDir "cookies.txt"
$BodyPath = Join-Path $TempDir "body.json"
$HeadersPath = Join-Path $TempDir "headers.txt"
$PayloadPath = Join-Path $TempDir "payload.json"

function Invoke-CurlJson {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$CsrfToken = "",
        [object]$Payload = $null,
        [int[]]$ExpectedStatus = @(200)
    )

    if (Test-Path -LiteralPath $BodyPath) { Remove-Item -LiteralPath $BodyPath -Force }
    if (Test-Path -LiteralPath $HeadersPath) { Remove-Item -LiteralPath $HeadersPath -Force }

    $args = @(
        "-s", "-S",
        "-X", $Method,
        "-D", $HeadersPath,
        "-o", $BodyPath,
        "-w", "%{http_code}",
        "-c", $CookieJar,
        "-b", $CookieJar
    )

    if ($Payload -ne $null) {
        $json = $Payload | ConvertTo-Json -Depth 8 -Compress
        [System.IO.File]::WriteAllText($PayloadPath, $json)
        $args += @("-H", "Content-Type: application/json", "--data-binary", "@$PayloadPath")
    }
    elseif ($Method -in @("POST", "PUT", "PATCH")) {
        $args += @("-H", "Content-Type: application/json", "--data-raw", "{}")
    }

    if ($CsrfToken) {
        $args += @("-H", "X-Panopticon-CSRF: $CsrfToken")
    }

    $args += "$BackendUrl$Path"
    $status = & curl.exe @args
    $statusCode = [int]$status

    if ($ExpectedStatus -notcontains $statusCode) {
        Write-Host "Unexpected HTTP $statusCode for $Method $Path"
        if (Test-Path -LiteralPath $HeadersPath) { Get-Content -LiteralPath $HeadersPath }
        if (Test-Path -LiteralPath $BodyPath) { Get-Content -LiteralPath $BodyPath }
        throw "Auth smoke failed."
    }

    $raw = ""
    if (Test-Path -LiteralPath $BodyPath) {
        $raw = Get-Content -LiteralPath $BodyPath -Raw
    }
    $headers = ""
    if (Test-Path -LiteralPath $HeadersPath) {
        $headers = Get-Content -LiteralPath $HeadersPath -Raw
    }

    $jsonBody = $null
    if ($raw.Trim()) {
        $jsonBody = $raw | ConvertFrom-Json
    }

    return @{
        Status = $statusCode
        Body = $jsonBody
        RawBody = $raw
        Headers = $headers
    }
}

function Assert-HeaderContains {
    param(
        [string]$Headers,
        [string]$Needle,
        [string]$Message
    )
    if (-not $Headers.ToLowerInvariant().Contains($Needle.ToLowerInvariant())) {
        Write-Host $Headers
        throw $Message
    }
}

try {
    Write-Host "Production auth smoke: $BackendUrl"

    $csrfResponse = Invoke-CurlJson -Method "GET" -Path "/api/auth/csrf"
    $csrf = $csrfResponse.Body.csrf_token
    if (-not $csrf) { throw "CSRF endpoint did not return csrf_token." }
    Assert-HeaderContains $csrfResponse.Headers "panopticon_csrf=" "CSRF cookie was not set."
    Assert-HeaderContains $csrfResponse.Headers "samesite=none" "CSRF cookie must use SameSite=None for Cloud Run frontend/backend domains."
    Assert-HeaderContains $csrfResponse.Headers "secure" "CSRF cookie must be Secure in production."
    Write-Host "csrf_cookie=ok"

    $email = "panopticon-smoke-$RunId@example.test"
    $password = "PanopticonSmoke-$RunId!"
    $signup = Invoke-CurlJson `
        -Method "POST" `
        -Path "/api/auth/signup" `
        -CsrfToken $csrf `
        -Payload @{
            email = $email
            password = $password
            name = "Panopticon Smoke"
            workspace_name = "Smoke Workspace"
        }

    Assert-HeaderContains $signup.Headers "panopticon_session=" "Signup did not set a session cookie."
    Assert-HeaderContains $signup.Headers "httponly" "Session cookie must be HttpOnly."
    Assert-HeaderContains $signup.Headers "samesite=none" "Session cookie must use SameSite=None for Cloud Run frontend/backend domains."
    Assert-HeaderContains $signup.Headers "secure" "Session cookie must be Secure in production."
    Write-Host "signup_session=ok email=$email"

    $me = Invoke-CurlJson -Method "GET" -Path "/api/auth/me"
    if ($me.Body.user.email -ne $email) {
        throw "Session lookup returned $($me.Body.user.email), expected $email."
    }
    Write-Host "session_lookup=ok workspace=$($me.Body.workspace.name)"

    Invoke-CurlJson -Method "POST" -Path "/api/auth/logout" -CsrfToken $csrf | Out-Null
    Invoke-CurlJson -Method "GET" -Path "/api/auth/me" -ExpectedStatus @(401) | Out-Null
    Write-Host "logout=ok"

    $csrfResponse = Invoke-CurlJson -Method "GET" -Path "/api/auth/csrf"
    $csrf = $csrfResponse.Body.csrf_token

    $login = Invoke-CurlJson `
        -Method "POST" `
        -Path "/api/auth/login" `
        -CsrfToken $csrf `
        -Payload @{
            email = $email
            password = $password
        }
    Assert-HeaderContains $login.Headers "panopticon_session=" "Login did not set a session cookie."

    $me = Invoke-CurlJson -Method "GET" -Path "/api/auth/me"
    if ($me.Body.user.email -ne $email) {
        throw "Login session lookup returned $($me.Body.user.email), expected $email."
    }
    Write-Host "login_session=ok"

    Invoke-CurlJson -Method "POST" -Path "/api/auth/logout" -CsrfToken $csrf | Out-Null
    Write-Host "auth_smoke=passed"
}
finally {
    if (Test-Path -LiteralPath $TempDir) {
        Remove-Item -LiteralPath $TempDir -Recurse -Force
    }
}
