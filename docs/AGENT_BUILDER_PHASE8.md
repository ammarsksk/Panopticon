# Phase 8: Vertex AI Agent Builder Runtime

## What This Adds

Phase 8 packages Panopticon as a Google Vertex AI Agent Engine compatible runtime while keeping FastAPI as the product backend and source of truth.

The managed agent does not connect directly to PostgreSQL, GitLab, or Slack. It calls Panopticon's workspace-scoped MCP tools, so every operation still passes through authentication, workspace filtering, approval rules, and audit logs.

## Architecture

```text
Vertex AI Agent Builder / Agent Engine
  -> panopticon_agent.root_agent
  -> Panopticon MCP JSON-RPC client
  -> FastAPI /mcp
  -> workspace-scoped tools
  -> PostgreSQL, GitLab OAuth, Slack OAuth, repo index, fix plans
```

## Runtime Files

```text
panopticon_agent/agent.py
panopticon_agent/runtime.py
panopticon_agent/tools.py
panopticon_agent/prompts.py
panopticon_agent/schemas.py
panopticon_agent/tool_manifest.json
requirements-agent.txt
scripts/smoke_agent_runtime.py
scripts/deploy_agent_engine.py
```

## Required Environment Variables

Backend `.env`:

```text
AGENT_RUNTIME_TOKEN=<long random shared runtime token>
AGENT_RUNTIME_WORKSPACE_SLUG=<workspace slug the managed agent may access>
AGENT_RUNTIME_USER_EMAIL=agent@panopticon.dev
PANOPTICON_API_BASE_URL=http://127.0.0.1:8000
PANOPTICON_AGENT_TOKEN=<same value as AGENT_RUNTIME_TOKEN>
```

Agent runtime environment:

```text
PANOPTICON_API_BASE_URL=https://YOUR_BACKEND_DOMAIN
PANOPTICON_AGENT_TOKEN=<same value as AGENT_RUNTIME_TOKEN>
GOOGLE_CLOUD_PROJECT=panopticon-495816
GOOGLE_CLOUD_LOCATION=us-central1
```

`PANOPTICON_AGENT_TOKEN` and `AGENT_RUNTIME_TOKEN` must match. Local scripts automatically read `backend/.env`, so you do not need to pass these variables through PowerShell.

## Local Run Commands

Clear backend/frontend ports first:

```powershell
$ports = @(8000,3000,3001); foreach ($port in $ports) { $pids = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique; foreach ($pid in $pids) { if ($pid) { taskkill /PID $pid /F } } }
```

Start backend:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Smoke test the managed-agent package:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python scripts/smoke_agent_runtime.py --list-tools
python scripts/smoke_agent_runtime.py --question "Which risks should I inspect first?"
```

Dry-run Agent Engine deployment config:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python scripts/deploy_agent_engine.py --dry-run
```

Deploy after installing Agent Engine dependencies:

```powershell
python -m pip install -r requirements-agent.txt
python scripts/deploy_agent_engine.py
```

## Security Rules

- The managed runtime can only access one configured workspace.
- Tool calls are audited as `agent.tool_call`.
- GitLab and Slack writes still require existing approval-gated backend flows.
- The agent runtime never receives database credentials.
- The agent runtime never receives GitLab or Slack OAuth tokens directly.

## Tests

Phase 8 tests cover:

```text
agent bearer token workspace auth
cross-workspace isolation for runtime token
MCP tool-call audit logs
agent runtime query orchestration
tool manifest contract
```

Run:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
python -m pytest backend/tests/test_agent_builder_phase8.py -q
python -m pytest -q
```

## Google Cloud Notes

Google's Agent Engine deployment flow supports source-file deployment with:

```text
source_packages
entrypoint_module
entrypoint_object
class_methods
requirements_file
```

Panopticon uses:

```text
entrypoint_module = panopticon_agent.agent
entrypoint_object = root_agent
```

The exposed class methods are:

```text
query
list_tools
call_tool
smoke_check
```
