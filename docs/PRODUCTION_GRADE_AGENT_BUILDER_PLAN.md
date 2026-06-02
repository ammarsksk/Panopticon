# Panopticon Production-Grade Agent Builder Plan

## Purpose

This document is the production hardening plan for Panopticon.

The goal is to move Panopticon from a local GitLab operations copilot into a multi-user, production-grade developer platform where every user or team has isolated data, connected GitLab projects, Slack workflows, repository-aware recommendations, safe code-change automation, and a Google Cloud managed agent runtime.

This plan intentionally focuses on production foundations, not new surface-level features.

## Target Product Standard

Panopticon should become a secure, evidence-backed engineering operations agent.

A production user should be able to:

1. Sign up or log in.
2. Create or join a workspace.
3. Connect GitLab through OAuth.
4. Select repositories to monitor.
5. Connect Slack through OAuth.
6. Let Panopticon sync GitLab activity and repository context.
7. Ask questions in chat.
8. Receive grounded recommendations using logs, diffs, code, history, and operational memory.
9. Approve safe actions.
10. Let Panopticon create GitLab comments, Slack messages, fix plans, branches, commits, and merge requests only inside approved boundaries.

The production loop is:

```text
Authenticate -> Connect -> Sync -> Index -> Retrieve -> Reason -> Validate -> Recommend -> Approve -> Act -> Audit -> Learn
```

## Google Agent Builder Requirement

Google's current production agent stack should be part of the plan.

Panopticon should use **Vertex AI Agent Builder** as the managed agent platform layer. Google describes Vertex AI Agent Builder as a suite for building, scaling, and governing production AI agents. It includes Agent Garden samples, built-in tools such as grounding/search/code execution, and managed runtime/deployment options through Agent Engine.

Panopticon should not be rebuilt as a no-code console-only bot. The existing FastAPI backend remains the product API and operational source of truth.

The correct architecture is:

```text
Next.js frontend
    |
FastAPI product backend
    |
PostgreSQL + Redis + repo index + integrations
    |
Panopticon MCP/REST tools
    |
Vertex AI Agent Builder / Agent Engine managed agent runtime
    |
Gemini model reasoning
```

### Why Agent Builder Fits

Agent Builder should provide:

- managed agent deployment
- managed sessions and runtime isolation
- tracing and observability for agent behavior
- governance over tools
- evaluation hooks
- production integration with Gemini models
- future compatibility with Google Cloud API Registry and MCP-style tool governance

Panopticon should provide:

- GitLab domain tools
- Slack approval tools
- repo context retrieval
- recommendation validators
- workspace security
- audit logs
- action execution boundaries

## Production Architecture

Recommended production services:

```text
frontend                 Next.js app
backend-api              FastAPI API
worker-gitlab-sync       GitLab project/MR/pipeline/job sync
worker-repo-indexer      clone/fetch/index repositories
worker-ai                recommendation and chat reasoning jobs
worker-dispatch          Slack/GitLab action dispatch
postgres                 primary relational database
redis                    queue/cache/rate-limit store
object-storage           repo archives, logs, artifacts if needed
vertex-agent-runtime     Agent Builder / Agent Engine deployment
```

On Google Cloud, the target deployment should be:

```text
Cloud Run                 frontend/backend/workers
Cloud SQL PostgreSQL      production database
Memorystore Redis         worker queue/cache
Secret Manager            GitLab, Slack, encryption, Vertex config
Cloud Storage             repo cache or agent deployment artifacts
Vertex AI                 Gemini and Agent Builder/Agent Engine
Cloud Logging             logs
Cloud Monitoring          metrics and alerts
```

## Phase 1: Authentication And Workspace Isolation

### Goal

Make Panopticon multi-user and multi-tenant.

Every user must belong to a workspace, and every project, recommendation, chat, action, fix plan, Slack install, and GitLab connection must belong to that workspace.

### Backend Work

Add tables:

```text
users
workspaces
workspace_members
user_sessions
oauth_connections
audit_logs
```

Add auth capabilities:

```text
signup
login
logout
session refresh
workspace selection
role checks
```

Use:

```text
HTTP-only secure cookies
bcrypt password hashing
JWT or opaque session IDs
CSRF protection
rate limiting
```

Roles:

```text
owner
admin
developer
viewer
```

### Frontend Work

Add:

```text
/login
/signup
/settings/workspace
protected route shell
user/workspace switcher
```

### Acceptance Criteria

- A user can log in and out.
- Every API request resolves a current user and workspace.
- Users cannot access another workspace's data.
- Admin-only actions are blocked for non-admin users.

## Phase 2: Workspace-Scoped Database Model

### Goal

Prevent data leakage and make every record belong to the right tenant.

### Backend Work

Add `workspace_id` to production tables:

```text
projects
project_sync_runs
merge_request_signals
pipeline_insights
risks
recommendations
action_dispatches
fix_plans
observability_events
incident_correlations
engineering_metric_snapshots
memory_records
chat_threads
chat_messages
repository_indexes
```

All queries must filter by the current workspace:

```text
WHERE workspace_id = current_workspace_id
```

### Acceptance Criteria

- Workspace A cannot see Workspace B records.
- Tests prove cross-workspace access is rejected.
- Existing demo/local records are assigned to a local development workspace.

## Phase 3: GitLab OAuth And Project Ownership

### Goal

Replace manual GitLab tokens with per-user GitLab OAuth.

### Required GitLab Capabilities

OAuth scopes should support:

```text
read_api
read_repository
write_repository
api
```

`api` is needed for comments, branches, commits, and merge requests.

### Backend Work

Add:

```text
GET /api/integrations/gitlab/connect
GET /api/integrations/gitlab/callback
GET /api/integrations/gitlab/projects
POST /api/integrations/gitlab/projects/enable
POST /api/integrations/gitlab/projects/{id}/webhook
```

Store encrypted:

```text
access_token
refresh_token
expires_at
gitlab_user_id
gitlab_instance_url
```

### Acceptance Criteria

- User connects GitLab without editing `.env`.
- User can choose which projects Panopticon monitors.
- Project records are workspace-scoped.
- GitLab token refresh works.
- GitLab webhooks validate secret tokens.

## Phase 4: Slack OAuth And Workspace Collaboration

### Goal

Make Slack installation per workspace instead of global `.env` configuration.

### Backend Work

Add:

```text
GET /api/integrations/slack/connect
GET /api/integrations/slack/callback
GET /api/integrations/slack/channels
POST /api/integrations/slack/default-channel
```

Store encrypted:

```text
bot_token
team_id
team_name
default_channel_id
default_channel_name
```

Keep global signing secret in Secret Manager for Slack request verification.

### Acceptance Criteria

- Each workspace can connect its own Slack workspace.
- Slack alerts go only to the configured workspace/channel.
- Slack approvals map back to the correct workspace and action.

## Phase 5: Repository Context Ingestion

### Goal

Give Panopticon the full repository context needed for correct recommendations and safe code changes.

### Backend Work

Add repo indexing tables:

```text
repositories
repository_branches
repository_commits
repository_files
repository_symbols
repository_merge_request_diffs
repository_job_logs
repository_embeddings
repository_index_jobs
```

Add workers:

```text
clone repository
fetch latest refs
index file tree
index default branch
index MR diffs
index CI config
index failed job logs
embed relevant files/docs
```

### Context Included Per Repo

Index:

```text
README files
source files
test files
.gitlab-ci.yml
Dockerfiles
Kubernetes manifests
Terraform files
deployment scripts
runbooks
owner files
recent failed job logs
recent MR diffs
```

### Acceptance Criteria

- Panopticon can retrieve relevant files for a pipeline, MR, or chat question.
- The app does not send the entire repo to Gemini.
- Retrieval returns compact evidence bundles.
- Repo indexing runs in background workers.

## Phase 6: Retrieval And Grounded Recommendation Engine

### Goal

Make recommendations evidence-backed instead of generic.

### Recommendation Pipeline

```text
1. Collect deterministic facts
2. Classify issue type
3. Retrieve code/log/diff context
4. Build evidence bundle
5. Ask Gemini through managed reasoner
6. Validate output against evidence
7. Score confidence
8. Create recommended actions
9. Require approval for external changes
```

### Retrieval Methods

Use:

```text
path heuristics
Git diff analysis
full-text search
symbol search
pgvector semantic search
recent incident similarity
project memory
```

### Acceptance Criteria

- Recommendations name actual files, jobs, commits, MRs, and evidence.
- If evidence is weak, the agent says it cannot determine the root cause.
- Gemini output is validated before being shown as a recommendation.
- Confidence reflects evidence quality.

## Phase 7: Safe Code-Changing System

### Goal

Let Panopticon prepare useful code changes without risking production branches.

### Required Safety Rules

```text
never commit to main/default branch
never edit secrets or .env files
never delete large file sets without explicit approval
always show diff before approval
always create a branch
always open a merge request
always record audit logs
always run configured tests when possible
```

### Backend Work

Expand fix-plan flow:

```text
create fix plan
retrieve context
generate patch
validate patch
run tests
show diff
approve
create branch
commit
open GitLab MR
```

### Acceptance Criteria

- Code changes are branch-only.
- Every generated patch has evidence and a rollback explanation.
- Users approve before GitLab write operations.
- MR description includes evidence, tests run, and risk notes.

## Phase 8: Vertex AI Agent Builder Packaging

### Goal

Deploy Panopticon's agent orchestration layer to Google Cloud's managed agent runtime while keeping FastAPI as the product backend.

### Runtime Direction

Create a dedicated agent entrypoint that can run outside FastAPI:

```text
panopticon_agent/
  agent.py
  tools.py
  prompts.py
  schemas.py
  runtime.py
```

The agent should call Panopticon tools through:

```text
REST tool endpoints
MCP-compatible endpoint
workspace-scoped auth token
```

### Agent Builder Responsibilities

Use Agent Builder / Agent Engine for:

```text
managed deployment
agent sessions
tool governance
tracing
runtime monitoring
Gemini model orchestration
evaluation hooks
```

### Panopticon Responsibilities

Keep in FastAPI/backend:

```text
auth
workspace isolation
GitLab OAuth
Slack OAuth
database writes
repo indexing
action approval
audit logs
safe execution
```

### Required Work

Add:

```text
agent runtime entrypoint
agent deployment requirements file
Agent Engine deployment script
tool manifest
MCP tool compatibility tests
managed-runtime smoke test
agent tracing metadata
```

### Implemented Phase 8 Shape

Panopticon now includes a dedicated managed-agent package:

```text
panopticon_agent/
  agent.py                 Agent Engine entrypoint exposing root_agent
  runtime.py               query/list_tools/call_tool/smoke_check runtime
  tools.py                 MCP JSON-RPC client for the FastAPI backend
  prompts.py               Panopticon agent instructions
  schemas.py               runtime request/response dataclasses
  tool_manifest.json       governed tool contract
```

The managed runtime calls FastAPI through `/mcp` using:

```text
Authorization: Bearer ${PANOPTICON_AGENT_TOKEN}
X-Panopticon-Agent-Runtime: vertex-agent-engine
X-Panopticon-Agent-Trace-Id: ${trace_id}
```

FastAPI accepts this only when the bearer token matches:

```text
AGENT_RUNTIME_TOKEN
```

The token resolves to:

```text
AGENT_RUNTIME_WORKSPACE_SLUG
AGENT_RUNTIME_USER_EMAIL
```

Every MCP `tools/call` request is written to `audit_logs` with event type:

```text
agent.tool_call
```

Deployment assets:

```text
requirements-agent.txt
scripts/deploy_agent_engine.py
scripts/smoke_agent_runtime.py
```

Local smoke test:

```powershell
$env:PANOPTICON_API_BASE_URL="http://127.0.0.1:8000"
$env:PANOPTICON_AGENT_TOKEN="<same value as backend AGENT_RUNTIME_TOKEN>"
python scripts/smoke_agent_runtime.py --list-tools
python scripts/smoke_agent_runtime.py --question "Which risks should I inspect first?"
```

Agent Engine dry-run:

```powershell
$env:GOOGLE_CLOUD_PROJECT="panopticon-495816"
$env:GOOGLE_CLOUD_LOCATION="us-central1"
$env:PANOPTICON_API_BASE_URL="https://YOUR_BACKEND_DOMAIN"
$env:PANOPTICON_AGENT_TOKEN="<same value as backend AGENT_RUNTIME_TOKEN>"
python scripts/deploy_agent_engine.py --dry-run
```

Agent Engine deploy:

```powershell
python -m pip install -r requirements-agent.txt
python scripts/deploy_agent_engine.py
```

### Acceptance Criteria

- Local FastAPI chat still works.
- Managed Agent Builder runtime can call Panopticon tools.
- Agent calls are workspace-scoped.
- Tool calls are audited.
- Managed agent answers match or improve local agent answers.

## Phase 9: Evaluation, Testing, And Quality Gates

### Goal

Make recommendation and code-change quality measurable.

### Evaluation Dataset

Create test cases for:

```text
failed pipeline with timeout
risky auth MR
deployment config change without tests
observability alert after deployment
flaky test signature
missing rollback plan
safe code fix proposal
unsafe code fix rejection
```

Each case should define:

```text
input records
repo context
expected root cause
required evidence
allowed recommendation types
forbidden claims
expected confidence range
```

### Quality Gates

Before production release:

```text
backend unit tests
frontend build
integration tests
cross-workspace isolation tests
GitLab OAuth tests
Slack OAuth tests
repo indexing tests
retrieval quality tests
LLM evaluation suite
safe patch tests
Agent Builder runtime smoke test
```

### Acceptance Criteria

- Bad recommendations fail tests.
- Hallucinated file/job names fail tests.
- Unsafe patches fail tests.
- Agent Builder deployment has a smoke test.

## Phase 10: Production Security And Operations

### Goal

Make the system safe to operate for real teams.

### Security Requirements

```text
encrypt integration tokens
store secrets in Google Secret Manager
use secure HTTP-only cookies
enable CSRF protection
rate limit auth and AI endpoints
validate webhook signatures
redact secrets in logs
isolate workspaces
log every external action
require approval for live actions
```

### Observability Requirements

Track:

```text
request latency
worker job status
GitLab API rate limits
Slack dispatch status
Gemini latency
Gemini errors
token usage
Agent Builder traces
repo indexing failures
recommendation acceptance rate
action success rate
```

### Acceptance Criteria

- Admins can inspect integration health.
- Failed workers retry safely.
- Secrets do not appear in logs.
- Every external action has an audit event.

## Recommended Implementation Order

Build in this order:

1. Authentication and workspace isolation
2. Workspace-scoped database migration
3. GitLab OAuth and project ownership
4. Slack OAuth and per-workspace collaboration
5. Repository context ingestion
6. Retrieval and grounded recommendation engine
7. Safe code-changing system
8. Vertex AI Agent Builder packaging
9. Evaluation and quality gates
10. Production security and operations

This order matters.

Agent Builder should come after workspace isolation, integrations, tools, and repository context are solid. A managed agent runtime is only useful if the tools it calls are secure, scoped, and grounded in real data.

## Immediate Next Sprint

The current completed sprint is:

```text
Phase 1: Authentication And Workspace Isolation
Phase 2: Workspace-Scoped Database Model
Phase 3: GitLab OAuth And Project Ownership groundwork
Phase 4: Slack OAuth And Workspace Collaboration groundwork
Google OAuth login groundwork
```

Implemented deliverables:

```text
users/workspaces/session tables
auth service
login/signup/logout endpoints
workspace-scoped API dependency
login/signup frontend routes
basic audit log table
tests for cross-user isolation
workspace_id columns on production data tables
per-workspace GitLab project uniqueness
local development workspace fallback
legacy unscoped record claiming for local data
oauth_states table for CSRF-safe OAuth callbacks
oauth_connections table for encrypted provider tokens
Google OAuth login start/callback endpoints
GitLab OAuth connect/callback/status endpoints
workspace GitLab project sync uses connected GitLab OAuth token first
GitLab fix-plan branch/MR actions use workspace OAuth token first
GitLab comment dispatch uses workspace OAuth token first
Slack OAuth install/callback/status endpoints
Slack alert dispatch can use workspace OAuth incoming webhook first
login screen includes Google OAuth entry point
projects screen includes GitLab OAuth connection status and connect action
dashboard includes Slack OAuth connection action
AUTH_REQUIRED enabled in local backend environment
```

After that, implement:

```text
Phase 5: repository context ingestion
Phase 8: Agent Builder packaging
```

## Official Google References

- Vertex AI Agent Builder documentation: https://docs.cloud.google.com/agent-builder
- Vertex AI Agent Builder overview: https://docs.cloud.google.com/agent-builder/overview
- Vertex AI Agent Engine overview: https://cloud.google.com/agent-builder/agent-engine/overview
- Agent Engine deployment documentation: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/deploy
