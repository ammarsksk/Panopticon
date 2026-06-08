# Cloud SQL Migration Plan

This is the first production-grade database step for Panopticon.

Target:

- Google Cloud SQL for PostgreSQL 16
- Project: `panopticon-495816`
- Region: `us-central1`
- Instance: `panopticon-postgres`
- Database: `panopticon`
- User: `panopticon`

## Why Cloud SQL First

Panopticon already uses SQLAlchemy, Alembic, and PostgreSQL-compatible models. Cloud SQL gives us a production-grade managed PostgreSQL database without rewriting the backend.

Use Cloud SQL now. Consider AlloyDB later if the agent memory, repository context, and analytics workloads outgrow Cloud SQL.

## What Was Added

- Cloud SQL production env template:
  - `backend/.env.production.example`
  - `backend/.env.cloud-sql-local.example`
- Google Cloud setup values template:
  - `infrastructure/cloud-sql.env.example`
- Google Cloud provisioning script:
  - `scripts/gcp_setup_cloud_sql.ps1`
- Cloud SQL migration script:
  - `scripts/gcp_migrate_cloud_sql.ps1`
- Database verification script:
  - `backend/app/scripts/check_database.py`
- Cloud Run backend manifest now attaches the Cloud SQL instance and pulls required secrets from Secret Manager:
  - `infrastructure/cloud-run-backend.yaml`

## Step 1: Create The Local Cloud SQL Config

Copy the template:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
copy infrastructure\cloud-sql.env.example infrastructure\cloud-sql.env
```

Fill `infrastructure\cloud-sql.env`.

Minimum required values:

```text
PROJECT_ID=panopticon-495816
REGION=us-central1
CLOUD_SQL_INSTANCE=panopticon-postgres
CLOUD_SQL_CONNECTION_NAME=panopticon-495816:us-central1:panopticon-postgres
DATABASE_NAME=panopticon
DATABASE_USER=panopticon
DATABASE_PASSWORD=<strong password>
BACKEND_DOMAIN=https://YOUR_BACKEND_DOMAIN
FRONTEND_DOMAIN=https://YOUR_FRONTEND_DOMAIN
GITLAB_TOKEN=<token>
GITLAB_WEBHOOK_SECRET=<secret>
GOOGLE_OAUTH_CLIENT_ID=<id>
GOOGLE_OAUTH_CLIENT_SECRET=<secret>
GITLAB_OAUTH_CLIENT_ID=<id>
GITLAB_OAUTH_CLIENT_SECRET=<secret>
SLACK_SIGNING_SECRET=<secret>
SLACK_OAUTH_CLIENT_ID=<id>
SLACK_OAUTH_CLIENT_SECRET=<secret>
OAUTH_TOKEN_ENCRYPTION_KEY=<fernet key>
AGENT_RUNTIME_TOKEN=<long random token>
```

Generate a Fernet key:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Step 2: Create Cloud SQL And Secrets

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\gcp_setup_cloud_sql.ps1
```

This script:

- Enables required Google Cloud APIs.
- Creates or reuses the `panopticon-runtime` service account.
- Grants Vertex AI, Secret Manager, and Cloud SQL Client roles.
- Creates a regional Cloud SQL PostgreSQL instance.
- Creates the `panopticon` database and user.
- Stores the production `DATABASE_URL` and OAuth/action secrets in Secret Manager.

If you create the Cloud SQL instance manually in the Google Cloud Console, run the script in safe mode after sign-in:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\gcp_setup_cloud_sql.ps1 -SkipCloudSqlCreation
```

This skips instance/database/user creation and only configures APIs, IAM roles, and Secret Manager values from `infrastructure\cloud-sql.env`.

Manual Cloud SQL settings to use in the console:

```text
Engine: PostgreSQL
Version: PostgreSQL 16
Instance ID: panopticon-postgres
Region: us-central1
Edition: Enterprise
Availability: Regional / High availability
Machine type: db-custom-1-3840
Storage: SSD, 20 GB, automatic storage increase enabled
Backups: enabled
Point-in-time recovery: enabled
Database name: panopticon
Database user: panopticon
Database password: same DATABASE_PASSWORD from infrastructure\cloud-sql.env
```

## Step 3: Install Cloud SQL Auth Proxy

Download the Windows Cloud SQL Auth Proxy binary and set this in `infrastructure\cloud-sql.env`:

```text
CLOUD_SQL_PROXY_PATH=C:\path\to\cloud-sql-proxy.exe
CLOUD_SQL_PROXY_PORT=5433
```

## Step 4: Run Migrations Against Cloud SQL

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\gcp_migrate_cloud_sql.ps1
```

This script:

- Starts Cloud SQL Auth Proxy locally.
- Points Alembic at Cloud SQL through `127.0.0.1:5433`.
- Runs:

```powershell
python -m alembic upgrade head
```

- Verifies the active database with:

```powershell
python -m app.scripts.check_database
```

Expected output includes:

```text
database_url_type=local_or_proxy_postgres
database=panopticon
user=panopticon
alembic_version=<latest migration>
postgres_version=PostgreSQL 16...
```

## Step 5: Keep Local Development Optional

After the Cloud SQL migration, you can still use local PostgreSQL for development.

Local DB:

```text
backend/.env.local-postgres.example
```

Cloud SQL through proxy:

```text
backend/.env.cloud-sql-local.example
```

Production Cloud Run:

```text
backend/.env.production.example
infrastructure/cloud-run-backend.yaml
```

## Step 6: Only Then Deploy Backend

The backend Cloud Run manifest is now Cloud SQL-ready, but deployment should happen after:

- Cloud SQL instance exists.
- Secrets exist in Secret Manager.
- Alembic migrations pass.
- OAuth redirect URLs are changed from localhost to production Cloud Run URLs.

Deployment comes after this database migration step.
