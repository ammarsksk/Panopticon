param(
    [switch]$SkipCloudSqlCreation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ConfigPath = Join-Path $Root "infrastructure\cloud-sql.env"

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
    if (-not $Values.ContainsKey($Name) -or -not $Values[$Name] -or $Values[$Name].StartsWith("CHANGE_ME") -or $Values[$Name].StartsWith("https://YOUR_")) {
        throw "Fill $Name in infrastructure\cloud-sql.env first."
    }
    return $Values[$Name]
}

function Ensure-Secret($ProjectId, $Name, $Value) {
    $exists = & gcloud.cmd secrets describe $Name --project $ProjectId --format="value(name)" 2>$null
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $Value)
    if (-not $exists) {
        & gcloud.cmd secrets create $Name --data-file=$tempFile --replication-policy=automatic --project $ProjectId | Out-Null
        Remove-Item -LiteralPath $tempFile -Force
        Write-Host "created secret: $Name"
        return
    }
    & gcloud.cmd secrets versions add $Name --data-file=$tempFile --project $ProjectId | Out-Null
    Remove-Item -LiteralPath $tempFile -Force
    Write-Host "added secret version: $Name"
}

$cfg = Read-DotEnv $ConfigPath
$ProjectId = Require-Value $cfg "PROJECT_ID"
$Region = Require-Value $cfg "REGION"
$Instance = Require-Value $cfg "CLOUD_SQL_INSTANCE"
$ConnectionName = Require-Value $cfg "CLOUD_SQL_CONNECTION_NAME"
$DatabaseName = Require-Value $cfg "DATABASE_NAME"
$DatabaseUser = Require-Value $cfg "DATABASE_USER"
$DatabasePassword = Require-Value $cfg "DATABASE_PASSWORD"
$Tier = if ($cfg["CLOUD_SQL_TIER"]) { $cfg["CLOUD_SQL_TIER"] } else { "db-custom-1-3840" }
$StorageGb = if ($cfg["CLOUD_SQL_STORAGE_GB"]) { $cfg["CLOUD_SQL_STORAGE_GB"] } else { "20" }
$BackupStart = if ($cfg["CLOUD_SQL_BACKUP_START_TIME"]) { $cfg["CLOUD_SQL_BACKUP_START_TIME"] } else { "03:00" }

Write-Host "Configuring Google Cloud project $ProjectId"
& gcloud.cmd config set project $ProjectId | Out-Null

Write-Host "Enabling required APIs"
& gcloud.cmd services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com --project $ProjectId | Out-Null

$ServiceAccount = "panopticon-runtime@$ProjectId.iam.gserviceaccount.com"
$ServiceAccountExists = & gcloud.cmd iam service-accounts describe $ServiceAccount --project $ProjectId --format="value(email)" 2>$null
if (-not $ServiceAccountExists) {
    & gcloud.cmd iam service-accounts create panopticon-runtime --display-name="Panopticon Runtime" --project $ProjectId | Out-Null
    Write-Host "created service account: $ServiceAccount"
}

Write-Host "Granting runtime service account roles"
foreach ($role in @("roles/aiplatform.user", "roles/secretmanager.secretAccessor", "roles/cloudsql.client")) {
    & gcloud.cmd projects add-iam-policy-binding $ProjectId --member="serviceAccount:$ServiceAccount" --role=$role --condition=None | Out-Null
}

if ($SkipCloudSqlCreation) {
    Write-Host "Skipping Cloud SQL instance/database/user creation by request."
} else {
    $InstanceExists = & gcloud.cmd sql instances describe $Instance --project $ProjectId --format="value(name)" 2>$null
    if (-not $InstanceExists) {
        Write-Host "Creating Cloud SQL PostgreSQL instance: $Instance"
        & gcloud.cmd sql instances create $Instance `
            --database-version=POSTGRES_16 `
            --edition=ENTERPRISE `
            --region=$Region `
            --tier=$Tier `
            --storage-size=$StorageGb `
            --storage-type=SSD `
            --availability-type=REGIONAL `
            --backup-start-time=$BackupStart `
            --enable-point-in-time-recovery `
            --database-flags=cloudsql.iam_authentication=on `
            --project $ProjectId | Out-Null
    } else {
        Write-Host "Cloud SQL instance already exists: $Instance"
    }

    $DbExists = & gcloud.cmd sql databases list --instance=$Instance --project $ProjectId --filter="name=$DatabaseName" --format="value(name)" 2>$null
    if (-not $DbExists) {
        & gcloud.cmd sql databases create $DatabaseName --instance=$Instance --project $ProjectId | Out-Null
        Write-Host "created database: $DatabaseName"
    }

    $UserExists = & gcloud.cmd sql users list --instance=$Instance --project $ProjectId --filter="name=$DatabaseUser" --format="value(name)" 2>$null
    if (-not $UserExists) {
        & gcloud.cmd sql users create $DatabaseUser --instance=$Instance --password=$DatabasePassword --project $ProjectId | Out-Null
        Write-Host "created database user: $DatabaseUser"
    } else {
        & gcloud.cmd sql users set-password $DatabaseUser --instance=$Instance --password=$DatabasePassword --project $ProjectId | Out-Null
        Write-Host "updated database user password: $DatabaseUser"
    }
}

$DatabaseUrl = "postgresql+psycopg://$DatabaseUser`:$DatabasePassword@/$DatabaseName`?host=/cloudsql/$ConnectionName"
Ensure-Secret $ProjectId "panopticon-database-url" $DatabaseUrl
Ensure-Secret $ProjectId "panopticon-gitlab-token" (Require-Value $cfg "GITLAB_TOKEN")
Ensure-Secret $ProjectId "panopticon-gitlab-webhook-secret" (Require-Value $cfg "GITLAB_WEBHOOK_SECRET")
Ensure-Secret $ProjectId "panopticon-google-oauth-client-id" (Require-Value $cfg "GOOGLE_OAUTH_CLIENT_ID")
Ensure-Secret $ProjectId "panopticon-google-oauth-client-secret" (Require-Value $cfg "GOOGLE_OAUTH_CLIENT_SECRET")
Ensure-Secret $ProjectId "panopticon-gitlab-oauth-client-id" (Require-Value $cfg "GITLAB_OAUTH_CLIENT_ID")
Ensure-Secret $ProjectId "panopticon-gitlab-oauth-client-secret" (Require-Value $cfg "GITLAB_OAUTH_CLIENT_SECRET")
Ensure-Secret $ProjectId "panopticon-slack-signing-secret" (Require-Value $cfg "SLACK_SIGNING_SECRET")
Ensure-Secret $ProjectId "panopticon-slack-oauth-client-id" (Require-Value $cfg "SLACK_OAUTH_CLIENT_ID")
Ensure-Secret $ProjectId "panopticon-slack-oauth-client-secret" (Require-Value $cfg "SLACK_OAUTH_CLIENT_SECRET")
Ensure-Secret $ProjectId "panopticon-oauth-token-encryption-key" (Require-Value $cfg "OAUTH_TOKEN_ENCRYPTION_KEY")
Ensure-Secret $ProjectId "panopticon-agent-runtime-token" (Require-Value $cfg "AGENT_RUNTIME_TOKEN")

Write-Host "Cloud SQL and production secrets are configured."
Write-Host "Next: run scripts\gcp_migrate_cloud_sql.ps1, then deploy Cloud Run."
