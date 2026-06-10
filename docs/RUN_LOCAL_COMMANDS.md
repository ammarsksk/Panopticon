# Local Run Commands

Run these from PowerShell.

## 0. Restart Everything

This clears the backend/frontend ports, runs migrations, starts both services in the background, and writes logs to `logs\`.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\restart_local.ps1
```

Open:

```text
http://localhost:3000
```

## 1. Start Backend

```powershell
$ports = @(8000); foreach ($port in $ports) { $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique; foreach ($pid in $pids) { if ($pid) { taskkill /PID $pid /F } } }

cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Backend URL:

```text
http://127.0.0.1:8000
```

## 2. Start Frontend

```powershell
$ports = @(3000,3001); foreach ($port in $ports) { $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique; foreach ($pid in $pids) { if ($pid) { taskkill /PID $pid /F } } }

cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run dev
```

Frontend URL:

```text
http://localhost:3000
```

If Next.js says port `3000` is busy and starts on `3001`, open:

```text
http://localhost:3001
```

## 3. Optional Agent Runtime Smoke Test

Run after the backend is already running.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python scripts/smoke_agent_runtime.py --list-tools
python scripts/smoke_agent_runtime.py --question "Which risks should I inspect first?"
```

## 4. Cloud SQL Migration

Use this when moving from local PostgreSQL to production Cloud SQL.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
copy infrastructure\cloud-sql.env.example infrastructure\cloud-sql.env
```

Fill `infrastructure\cloud-sql.env`, then run:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\gcp_setup_cloud_sql.ps1
.\scripts\gcp_migrate_cloud_sql.ps1
```

If you create the Cloud SQL instance manually in Google Cloud Console, use safe mode:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
.\scripts\gcp_setup_cloud_sql.ps1 -SkipCloudSqlCreation
.\scripts\gcp_migrate_cloud_sql.ps1
```

Full details:

```text
docs/CLOUD_SQL_MIGRATION.md
```

## 5. Create Real GitLab Showcase Projects

Run this when you want Panopticon demo projects to exist on GitLab first, with real repositories, merge requests, CI files, pipelines, and failed jobs. After creating them, the script runs the normal Panopticon GitLab sync so the dashboard data comes from GitLab.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.create_gitlab_showcase_projects
```

The script uses your connected GitLab OAuth account from Panopticon. If OAuth is not connected, it uses `GITLAB_TOKEN` from `backend\.env`.

If GitLab returns `Identity verification is required in order to run CI jobs`, the repositories and merge requests were created correctly, but GitLab will not create runnable CI jobs until the GitLab account completes identity verification.

Useful follow-up commands:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.report_gitlab_showcase_projects --project ammarsaifeek/panopticon-showcase-checkout-core --pipeline-limit 3
python -m app.scripts.repair_gitlab_showcase_ci
python -m app.scripts.trigger_gitlab_showcase_pipelines --no-wait --no-sync
```

## 6. Local-Only Showcase Data

Run this when you want reliable demo projects with real failed jobs, classified traces, repo context, incidents, actions, and fix plans.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.seed_showcase
```

This command creates local database records only. Those projects do not appear on GitLab.

## 7. Chat Evaluation Suite

Run this before changing chatbot behavior. It resets local showcase data, runs the seed evaluation cases, and writes the weak-point report.

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.run_chat_eval --seed-showcase
```

Reports:

```text
C:\Users\LENOVO\Downloads\Panopticon\artifacts\chat_eval\latest.md
C:\Users\LENOVO\Downloads\Panopticon\artifacts\chat_eval\latest.json
```

To test live Gemini answers instead of deterministic draft mode:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.run_chat_eval --seed-showcase --live-gemini
```
