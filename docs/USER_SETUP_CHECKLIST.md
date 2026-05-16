# User Setup Checklist

This is the concrete checklist for values you must create outside the codebase.

## Current Safe Local Mode

Your app can run safely with:

```text
DRY_RUN_ACTIONS=true
```

That means:

- Vertex Gemini is live.
- Dashboard works.
- Database works.
- GitLab comments are simulated.
- Slack messages are simulated.

Run the checker:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.check_setup
```

## 1. GitLab Token

Purpose:

- Fetch MR changes.
- Fetch pipeline jobs/logs.
- Fetch deployments.
- Post MR comments when `DRY_RUN_ACTIONS=false`.

Steps:

1. Open GitLab personal access tokens:
   `https://gitlab.com/-/user_settings/personal_access_tokens`
2. Create a token named `panopticon-local` or `panopticon-prod`.
3. Select scope `api`.
4. Copy the token once.
5. Add it to `backend\.env`:

```text
GITLAB_TOKEN=PASTE_TOKEN_HERE
```

Official docs:

- https://docs.gitlab.com/user/profile/personal_access_tokens/

## 2. GitLab Webhook Secret

Purpose:

- Proves incoming webhook requests really came from your GitLab webhook.

Steps:

1. Create a long random string.
2. Add it to `backend\.env`:

```text
GITLAB_WEBHOOK_SECRET=PASTE_LONG_RANDOM_SECRET_HERE
```

3. In your GitLab project, open:
   `Settings > Webhooks`
4. Add webhook URL:

```text
https://YOUR_BACKEND_PUBLIC_URL/webhooks/gitlab
```

5. Paste the same secret into `Secret token`.
6. Enable:
   - Merge request events
   - Pipeline events
   - Deployment events
   - Job events, optional

Official docs:

- https://docs.gitlab.com/user/project/integrations/webhooks/

## 3. Slack Incoming Webhook

Purpose:

- Send pipeline failure and incident alerts to a Slack channel.

Steps:

1. Open Slack apps:
   `https://api.slack.com/apps`
2. Create an app or select an existing app.
3. Go to `Incoming Webhooks`.
4. Turn on `Activate Incoming Webhooks`.
5. Click `Add New Webhook to Workspace`.
6. Choose a channel.
7. Copy the webhook URL.
8. Add it to `backend\.env`:

```text
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

9. Test the integration safely:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.check_slack
```

With `DRY_RUN_ACTIONS=true`, this prints a simulated Slack payload and does not send anything.

10. To send a real test message, temporarily set:

```text
DRY_RUN_ACTIONS=false
```

Then run:

```powershell
python -m app.scripts.check_slack
```

Set it back to safe mode after the test:

```text
DRY_RUN_ACTIONS=true
```

Official docs:

- https://docs.slack.dev/tools/java-slack-sdk/guides/incoming-webhooks/

## 4. Public Backend URL For GitLab

GitLab cannot call `localhost`. You need one of these:

- Cloud Run backend URL, recommended for production.
- A local tunnel for testing.

For production, follow:

```text
docs/PRODUCTION_SETUP.md
```

For local testing, use a tunnel such as Cloudflare Tunnel or ngrok, then set the GitLab webhook URL to:

```text
https://YOUR_TUNNEL_URL/webhooks/gitlab
```

## 5. Local PostgreSQL

Docker Desktop must be running before this step.

Start Postgres:

```powershell
$pid5432 = (netstat -ano | Select-String ':5432' | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique)
if ($pid5432) { $pid5432 | ForEach-Object { taskkill /PID $_ /F } }

cd C:\Users\LENOVO\Downloads\Panopticon\infrastructure
docker compose up -d postgres
```

Switch backend to Postgres:

```powershell
copy C:\Users\LENOVO\Downloads\Panopticon\backend\.env.local-postgres.example C:\Users\LENOVO\Downloads\Panopticon\backend\.env
```

Run migrations:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
alembic upgrade head
```

## 6. Turn On Real Actions

Do this only after the Action Queue looks correct.

In `backend\.env`:

```text
DRY_RUN_ACTIONS=false
```

Then restart backend.

## Local Run Commands

Backend:

```powershell
$pid8000 = (netstat -ano | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique)
if ($pid8000) { $pid8000 | ForEach-Object { taskkill /PID $_ /F } }

$env:CLOUDSDK_CONFIG="C:\Users\LENOVO\Downloads\Panopticon\.gcloud"
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.seed_demo --reset
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
$pid3000 = (netstat -ano | Select-String ':3000' | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -Unique)
if ($pid3000) { $pid3000 | ForEach-Object { taskkill /PID $_ /F } }

cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run dev
```
