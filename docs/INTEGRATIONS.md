# Panopticon Integrations

## Safety Defaults

Panopticon defaults to safe local behavior:

```text
DRY_RUN_ACTIONS=true
DISPATCH_ACTIONS=true
```

With these defaults, recommendations are dispatched through the same code path, but outbound GitLab and Slack writes are recorded as `dry_run`.

Set `DISPATCH_ACTIONS=false` to queue recommendations without attempting any channel dispatch.

## GitLab

Configure:

```text
GITLAB_BASE_URL=https://gitlab.com
GITLAB_TOKEN=<personal-access-token-or-project-token>
GITLAB_WEBHOOK_SECRET=<shared-webhook-secret>
```

Implemented GitLab capabilities:

- Verify incoming webhook token with `X-Gitlab-Token`
- Fetch merge request details
- Fetch merge request changes when webhook payload lacks changed-file context
- Fetch pipeline jobs
- Fetch failed job traces for pipeline failure analysis
- Fetch deployment records
- Publish merge request notes for risk recommendations

To allow real GitLab comments:

```text
DRY_RUN_ACTIONS=false
DISPATCH_ACTIONS=true
GITLAB_TOKEN=<token-with-api-scope>
```

## Slack

Configure:

```text
SLACK_WEBHOOK_URL=<incoming-webhook-url>
```

Implemented Slack capabilities:

- Send pipeline failure alerts
- Send incident/root-cause alerts
- Send structured Block Kit-style alert payloads through incoming webhooks
- Preserve dry-run behavior unless `DRY_RUN_ACTIONS=false`

Smoke test:

```powershell
cd backend
python -m app.scripts.check_slack
```

## Gemini / Vertex

Configure:

```text
GEMINI_ENABLED=true
GEMINI_MODEL=gemini-3-pro
GEMINI_API_KEY=
GOOGLE_API_KEY=
GOOGLE_GENAI_USE_VERTEXAI=false
GOOGLE_CLOUD_PROJECT=<project-id>
GOOGLE_CLOUD_LOCATION=us-central1
```

Panopticon uses the Google Gen AI SDK through `backend/app/agents/gemini.py`.

### Option A: Gemini Developer API

Use this for the fastest local setup with an API key from Google AI Studio.

```text
GEMINI_ENABLED=true
GOOGLE_GENAI_USE_VERTEXAI=false
GEMINI_API_KEY=<your-ai-studio-key>
GEMINI_MODEL=gemini-3-pro
```

If `gemini-3-pro` is not available to your key, use a model available in your account, for example:

```text
GEMINI_MODEL=gemini-2.5-flash
```

### Option B: Vertex AI

Use this for the hackathon production path on Google Cloud.

```text
GEMINI_ENABLED=true
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=<your-gcp-project-id>
GOOGLE_CLOUD_LOCATION=us-central1
GEMINI_MODEL=gemini-3-pro
```

You also need Google application default credentials:

```powershell
gcloud auth application-default login
gcloud config set project <your-gcp-project-id>
```

The account or service account needs the Vertex AI User role.

### Test Gemini

After setting `backend/.env`, run:

```powershell
cd backend
python -m app.scripts.check_gemini
```

If Gemini is live, the output should be a model-generated operations recommendation. If Gemini is disabled, it will print the local deterministic summary.

Prompt files:

- `prompts/deployment_risk.md`
- `prompts/pipeline_failure_analysis.md`
- `prompts/incident_timeline.md`
- `prompts/mr_bottleneck.md`
