# Panopticon Production Setup

This guide promotes Panopticon from local demo mode to a production-ready deployment on Google Cloud using:

- Cloud Run for backend and frontend containers
- Cloud SQL for PostgreSQL
- Secret Manager for sensitive values
- Vertex AI Gemini through a Cloud Run service account
- GitLab webhooks and API token
- Slack incoming webhook

Project ID used in this workspace:

```text
panopticon-495816
```

## What You Must Provide

You must create or provide these values:

```text
GITLAB_TOKEN
GITLAB_WEBHOOK_SECRET
SLACK_WEBHOOK_URL
DATABASE_URL
FRONTEND_DOMAIN
BACKEND_DOMAIN
```

Keep `DRY_RUN_ACTIONS=true` until GitLab and Slack outputs have been verified.

## Local Run Commands

Every local run starts by clearing the port.

### Backend

```powershell
$pid8000 = (netstat -ano | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique)
if ($pid8000) { $pid8000 | ForEach-Object { taskkill /PID $_ /F } }

$env:CLOUDSDK_CONFIG="C:\Users\LENOVO\Downloads\Panopticon\.gcloud"
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.seed_demo --reset
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```powershell
$pid3000 = (netstat -ano | Select-String ':3000' | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique)
if ($pid3000) { $pid3000 | ForEach-Object { taskkill /PID $_ /F } }

cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run dev
```

## Local Tests

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python -m pytest -q
```

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run build
npm.cmd audit --omit=dev
```

```powershell
$env:CLOUDSDK_CONFIG="C:\Users\LENOVO\Downloads\Panopticon\.gcloud"
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.check_gemini
```

## Google Cloud Setup

Set project:

```powershell
$env:CLOUDSDK_CONFIG="C:\Users\LENOVO\Downloads\Panopticon\.gcloud"
gcloud.cmd config set project panopticon-495816
```

Enable APIs:

```powershell
gcloud.cmd services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com aiplatform.googleapis.com --project panopticon-495816
```

Create runtime service account:

```powershell
gcloud.cmd iam service-accounts create panopticon-runtime --display-name="Panopticon Runtime" --project panopticon-495816
```

Grant Vertex AI access:

```powershell
gcloud.cmd projects add-iam-policy-binding panopticon-495816 --member="serviceAccount:panopticon-runtime@panopticon-495816.iam.gserviceaccount.com" --role="roles/aiplatform.user"
```

Grant Secret Manager access:

```powershell
gcloud.cmd projects add-iam-policy-binding panopticon-495816 --member="serviceAccount:panopticon-runtime@panopticon-495816.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

## Cloud SQL PostgreSQL

The production database migration flow is now maintained in:

```text
docs/CLOUD_SQL_MIGRATION.md
```

Use that document first. It creates Cloud SQL, configures Secret Manager, runs Alembic, and verifies the active database.

Manual commands are kept here for reference only.

Create an instance:

```powershell
gcloud.cmd sql instances create panopticon-postgres --database-version=POSTGRES_16 --region=us-central1 --tier=db-custom-1-3840 --availability-type=REGIONAL --storage-size=20 --storage-type=SSD --enable-point-in-time-recovery --backup-start-time=03:00 --project panopticon-495816
```

Create DB and user:

```powershell
gcloud.cmd sql databases create panopticon --instance=panopticon-postgres --project panopticon-495816
gcloud.cmd sql users create panopticon --instance=panopticon-postgres --password="CHANGE_ME_STRONG_PASSWORD" --project panopticon-495816
```

Cloud Run Unix socket `DATABASE_URL` format:

```text
postgresql+psycopg://panopticon:CHANGE_ME_STRONG_PASSWORD@/panopticon?host=/cloudsql/panopticon-495816:us-central1:panopticon-postgres
```

## Secret Manager

Create secrets:

```powershell
"DATABASE_URL_VALUE" | gcloud.cmd secrets create panopticon-database-url --data-file=- --project panopticon-495816
"GITLAB_TOKEN_VALUE" | gcloud.cmd secrets create panopticon-gitlab-token --data-file=- --project panopticon-495816
"GITLAB_WEBHOOK_SECRET_VALUE" | gcloud.cmd secrets create panopticon-gitlab-webhook-secret --data-file=- --project panopticon-495816
"SLACK_WEBHOOK_URL_VALUE" | gcloud.cmd secrets create panopticon-slack-webhook-url --data-file=- --project panopticon-495816
```

For the current production manifest, also create these secrets:

```text
panopticon-google-oauth-client-id
panopticon-google-oauth-client-secret
panopticon-gitlab-oauth-client-id
panopticon-gitlab-oauth-client-secret
panopticon-slack-signing-secret
panopticon-slack-oauth-client-id
panopticon-slack-oauth-client-secret
panopticon-oauth-token-encryption-key
panopticon-agent-runtime-token
```

The recommended way is to fill `infrastructure\cloud-sql.env` and run:

```powershell
.\scripts\gcp_setup_cloud_sql.ps1
```

## Build Images

Create Artifact Registry repository:

```powershell
gcloud.cmd artifacts repositories create panopticon --repository-format=docker --location=us-central1 --project panopticon-495816
```

Build backend:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
gcloud.cmd builds submit .\backend --tag us-central1-docker.pkg.dev/panopticon-495816/panopticon/backend:latest --project panopticon-495816
```

Build frontend:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
gcloud.cmd builds submit .\frontend --tag us-central1-docker.pkg.dev/panopticon-495816/panopticon/frontend:latest --project panopticon-495816
```

## Deploy Backend

```powershell
gcloud.cmd run deploy panopticon-backend `
  --image us-central1-docker.pkg.dev/panopticon-495816/panopticon/backend:latest `
  --region us-central1 `
  --service-account panopticon-runtime@panopticon-495816.iam.gserviceaccount.com `
  --add-cloudsql-instances panopticon-495816:us-central1:panopticon-postgres `
  --set-env-vars APP_ENV=production,ALLOWED_ORIGINS=https://YOUR_FRONTEND_DOMAIN,GEMINI_ENABLED=true,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=panopticon-495816,GOOGLE_CLOUD_LOCATION=global,GEMINI_MODEL=gemini-2.5-pro,DRY_RUN_ACTIONS=true,DISPATCH_ACTIONS=true `
  --set-secrets DATABASE_URL=panopticon-database-url:latest,GITLAB_TOKEN=panopticon-gitlab-token:latest,GITLAB_WEBHOOK_SECRET=panopticon-gitlab-webhook-secret:latest,SLACK_WEBHOOK_URL=panopticon-slack-webhook-url:latest `
  --allow-unauthenticated `
  --project panopticon-495816
```

After deploy, copy the backend URL:

```powershell
gcloud.cmd run services describe panopticon-backend --region us-central1 --format="value(status.url)" --project panopticon-495816
```

## Deploy Frontend

Build the frontend with the backend URL:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\frontend
$env:NEXT_PUBLIC_API_BASE_URL="https://YOUR_BACKEND_DOMAIN"
cd ..
gcloud.cmd builds submit .\frontend --tag us-central1-docker.pkg.dev/panopticon-495816/panopticon/frontend:latest --project panopticon-495816
```

Deploy:

```powershell
gcloud.cmd run deploy panopticon-frontend `
  --image us-central1-docker.pkg.dev/panopticon-495816/panopticon/frontend:latest `
  --region us-central1 `
  --allow-unauthenticated `
  --project panopticon-495816
```

Then update backend `ALLOWED_ORIGINS` to the real frontend URL and redeploy backend.

## GitLab Setup

Create a GitLab token with API access for the project. Store it in Secret Manager as `panopticon-gitlab-token`.

In GitLab project:

```text
Settings > Webhooks > Add new webhook
```

URL:

```text
https://YOUR_BACKEND_DOMAIN/webhooks/gitlab
```

Secret token:

```text
same value as GITLAB_WEBHOOK_SECRET
```

Enable triggers:

- Merge request events
- Pipeline events
- Deployment events
- Job events if you want deeper CI trace enrichment

## Slack Setup

Create a Slack app, enable Incoming Webhooks, add a webhook for the target channel, and store the generated URL in Secret Manager as `panopticon-slack-webhook-url`.

Configure the Slack app request URLs:

```text
Slash command: https://YOUR_BACKEND_DOMAIN/slack/commands
Interactivity: https://YOUR_BACKEND_DOMAIN/slack/interactions
Events:        https://YOUR_BACKEND_DOMAIN/slack/events
```

Store these backend environment values:

```text
SLACK_SIGNING_SECRET=<Slack app signing secret>
SLACK_BOT_TOKEN=<xoxb-token if bot posting is enabled>
SLACK_DEFAULT_CHANNEL=#panopticon
```

The first supported slash commands are:

```text
/panopticon risks
/panopticon project checkout-service
/panopticon ask why did the latest pipeline fail
/panopticon actions
```

## Go Live

Start with:

```text
DRY_RUN_ACTIONS=true
```

Verify:

- GitLab webhooks arrive
- dashboard shows events
- action dispatches are `dry_run`
- Vertex Gemini text appears
- action payloads look correct

Then redeploy backend with:

```text
DRY_RUN_ACTIONS=false
```

## Production Guarantees Added

- Production startup validation
- Explicit CORS
- PostgreSQL-only production validation
- Vertex-only production validation
- GitLab webhook token validation
- Webhook idempotency receipts
- Action dispatch audit records
- Alembic migration baseline
- Cloud Run-ready backend and frontend containers
- Secret Manager-oriented deployment
