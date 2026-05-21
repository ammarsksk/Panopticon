# Panopticon Next-Level Roadmap

## Purpose

This document is the implementation contract for turning Panopticon from a working MVP into a developer-facing GitLab operations copilot.

The goal is not to add random AI features. The goal is to build a product developers would actually keep open during real work: a console that understands GitLab activity, explains delivery risk, recommends next actions, coordinates through Slack, and can safely prepare changes through GitLab merge requests.

## Product Vision

Panopticon should become an agentic GitLab operations assistant.

It should continuously:

1. Observe engineering activity from GitLab.
2. Build project-level operational context.
3. Detect risks, failures, and bottlenecks.
4. Explain what happened in plain language.
5. Recommend concrete next actions.
6. Ask for human approval when an action changes external systems.
7. Execute approved actions through GitLab and Slack.
8. Learn from feedback and prior incidents.

The long-term loop is:

```text
Observe -> Analyze -> Remember -> Recommend -> Approve -> Act -> Learn
```

## Agent Runtime Direction

Panopticon currently runs as a FastAPI application with:

- a Vertex Gemini reasoner
- REST agent tools
- an MCP-compatible JSON-RPC endpoint at `/mcp`
- approval-gated GitLab and Slack actions

This is the correct local product architecture while the app is still evolving quickly.

Vertex AI Agent Builder should be used as the production agent platform layer, not as a replacement for the Panopticon app. The planned path is:

1. Keep Panopticon tools available through REST and MCP.
2. Package the reasoning/orchestration layer so it can run under Vertex AI Agent Engine.
3. Register or expose Panopticon MCP tools to the managed agent runtime.
4. Use Agent Builder/Agent Engine for managed sessions, memory, tracing, monitoring, and governance.
5. Keep the FastAPI backend as the product API and source of operational truth.

This means Panopticon already has the MCP server shape needed for Agent Builder compatibility, and the next runtime-focused phase should package and deploy the agent rather than rebuilding the product inside the Google Cloud console.

## Guiding Principles

### 1. GitLab is the source of truth

GitLab should drive the core product state:

- projects
- merge requests
- commits
- branches
- pipelines
- jobs
- deployments
- approvals
- comments
- webhook events

The dashboard should not depend only on incoming demo events. A real user should connect GitLab and immediately see useful project data.

### 2. Slack is the collaboration surface

Slack should start as an alert destination, then evolve into an interactive control plane.

The product should support:

- structured alerts
- slash commands
- action buttons
- approval modals
- incident updates
- on-call coordination

Slack should not replace the dashboard. It should bring important Panopticon workflows into the place where developers already coordinate.

### 3. Human approval before external action

Panopticon may recommend actions automatically, but it must not make risky external changes without approval.

Actions that require approval include:

- posting GitLab comments
- sending live Slack alerts
- retrying pipelines
- opening issues
- creating branches
- committing code
- opening merge requests
- changing deployment state

Dry-run remains the default for local development.

### 4. Deterministic analysis before LLM reasoning

The app should use deterministic analyzers for repeatable facts:

- files changed
- pipeline status
- missing tests
- sensitive paths
- rollback events
- blocked review state
- failed job signatures

Gemini should then improve explanation, summarization, prioritization, and recommendations.

This keeps the app reliable and avoids making Gemini responsible for basic facts.

### 5. Every recommendation must be actionable

A recommendation should answer:

- What happened?
- Why does it matter?
- What evidence supports it?
- What should happen next?
- Can Panopticon execute it?
- Does it require approval?
- How confident is the agent?

Avoid vague recommendations like "investigate the issue" unless they include a concrete first step.

### 6. The dashboard should be an operations console

The frontend should feel like a real engineering tool:

- dense but readable
- project-centered
- status-driven
- evidence-first
- no raw AI blobs
- no duplicate cards
- no half-filled cards
- clear action states

### 7. Operational memory is a first-class feature

Panopticon should remember:

- recurring pipeline failures
- repeated risky paths
- project-specific sensitive files
- prior incident causes
- false positives
- helpful recommendations
- ignored recommendations
- team-specific rules

Memory should make the product better over time.

## Target Product Shape

The next major version should include these primary surfaces:

```text
/dashboard
/projects
/projects/[projectId]
/projects/[projectId]/merge-requests
/projects/[projectId]/pipelines
/projects/[projectId]/incidents
/actions
/chat
/fix-plans
/observability
/metrics
/settings/integrations
```

## Data Model Direction

The current database already has operational events, risks, pipelines, incidents, recommendations, dispatches, and memory records.

Next we should add or evolve toward these concepts:

- `projects`
- `project_sync_runs`
- `merge_request_snapshots`
- `pipeline_snapshots`
- `job_snapshots`
- `recommendation_feedback`
- `agent_actions`
- `action_approvals`
- `chat_threads`
- `chat_messages`
- `fix_plans`
- `fix_plan_approvals`
- `observability_events`
- `incident_correlations`
- `engineering_metric_snapshots`
- `integration_status`
- `project_rules`

Schema changes should be introduced through Alembic migrations once the product direction is stable for each phase.

## Phase 1: GitLab Project Sync

### Goal

Make Panopticon automatically load real GitLab projects and current delivery state.

The user should not need to wait for webhooks to see useful data.

### Backend Work

Add GitLab sync services:

```text
GET /api/gitlab/projects
POST /api/gitlab/projects/sync
GET /api/projects
GET /api/projects/{project_id}
GET /api/projects/{project_id}/merge-requests
GET /api/projects/{project_id}/pipelines
GET /api/projects/{project_id}/jobs
```

Add database tables:

- projects
- project sync runs
- merge request snapshots
- pipeline snapshots
- job snapshots

GitLab data to sync:

- project id
- project path
- project web URL
- default branch
- visibility
- last activity
- open merge requests
- latest pipelines
- failed jobs
- pipeline web URLs
- merge request web URLs

### Frontend Work

Add a Projects page:

```text
/projects
```

Show:

- project name
- namespace
- last activity
- open MRs
- failed pipelines
- current risk count
- last sync time
- integration status

Add a sync button:

```text
Sync GitLab Projects
```

### Acceptance Criteria

- A user can click one button and load GitLab projects.
- Projects are stored in PostgreSQL.
- The dashboard can show real project counts.
- The app handles GitLab token errors gracefully.
- The frontend does not require demo events to show project data.

## Phase 2: Project Detail Workspace

### Goal

Give every GitLab project a useful operations workspace.

### Backend Work

Add project summary endpoint:

```text
GET /api/projects/{project_id}/summary
```

Return:

- project metadata
- open MR count
- failed pipeline count
- active risks
- recent incidents
- latest recommendations
- recent actions
- recurring failure signatures

### Frontend Work

Add:

```text
/projects/[projectId]
```

Sections:

- Project Overview
- Open Merge Requests
- Pipeline Health
- Deployment Risk
- Incidents
- Recommendations
- Operational Memory

### Acceptance Criteria

- A developer can open one project and understand what needs attention.
- MRs, pipelines, incidents, risks, and recommendations are grouped by project.
- Empty states are clean and useful.
- Cards link back to GitLab where possible.

## Phase 3: Recommendation Engine V2

### Goal

Move from plain recommendations to ranked, structured, executable recommendations.

### Recommendation Shape

Target structure:

```json
{
  "title": "Add missing checkout auth tests before merge",
  "summary": "The MR changes authentication and deployment files without test coverage.",
  "severity": "critical",
  "confidence": 0.86,
  "evidence": [],
  "next_actions": [],
  "can_execute": true,
  "requires_approval": true,
  "action_type": "gitlab_comment",
  "status": "pending_approval"
}
```

### Backend Work

Add:

- structured recommendation builder
- severity ranking
- confidence scoring
- action type classification
- approval requirement detection
- duplicate suppression

Recommendation types:

- GitLab comment
- Slack alert
- reviewer request
- issue creation
- pipeline retry
- fix plan
- runbook update
- incident follow-up

### Frontend Work

Update Action Queue:

- priority sorting
- severity filters
- action type filters
- approve button
- dismiss button
- mark false positive
- show generated payload preview

### Acceptance Criteria

- No raw recommendation blobs.
- Every recommendation has evidence and next actions.
- Duplicate recommendations collapse cleanly.
- Users can see which recommendations are executable.

## Phase 4: Approval And Action System

### Goal

Separate recommendation generation from action execution.

### Backend Work

Add tables:

- agent actions
- action approvals

Add endpoints:

```text
POST /api/actions/{action_id}/approve
POST /api/actions/{action_id}/reject
POST /api/actions/{action_id}/execute
GET /api/actions
GET /api/actions/{action_id}
```

Action states:

```text
proposed
pending_approval
approved
rejected
executing
sent
failed
cancelled
```

### Frontend Work

Add an Actions page:

```text
/actions
```

Show:

- proposed actions
- approval status
- execution status
- payload preview
- audit trail

### Acceptance Criteria

- Live external actions require approval unless explicitly configured otherwise.
- Every action has an audit trail.
- Users can preview Slack messages and GitLab comments before execution.

## Phase 5: Chat Interface

### Goal

Add a developer-facing chat assistant that can answer questions using Panopticon data.

### Example Questions

```text
Why did checkout-service fail?
Which MR is riskiest today?
What changed before the rollback?
Summarize this MR for reviewers.
What should I fix first?
Which project has the worst deployment risk this week?
Prepare a GitLab comment for MR !7.
```

### Backend Work

Add:

```text
POST /api/chat
GET /api/chat/threads
GET /api/chat/threads/{thread_id}
```

Agent tools:

- search projects
- fetch project summary
- fetch merge request details
- fetch pipeline failure
- fetch operational memory
- fetch recommendations
- prepare GitLab comment
- prepare Slack alert
- create fix plan

### Frontend Work

Add:

```text
/chat
```

The chat UI should include:

- project selector
- thread history
- cited evidence
- prepared action cards
- approval prompts

### Acceptance Criteria

- The assistant answers using stored app data, not generic guesses.
- Responses cite project records, MRs, pipeline IDs, or incidents.
- Action requests create proposed actions, not immediate live actions.
- Chat uses Vertex Gemini for final reasoning when `GEMINI_ENABLED=true`.
- If Gemini is disabled or unavailable, chat falls back to deterministic grounded answers.
- The app exposes Panopticon tools through REST and an MCP-compatible JSON-RPC endpoint.

## Phase 6: Slack App Upgrade

### Goal

Move beyond incoming webhooks into interactive Slack workflows.

### Slack Capabilities

Add:

- slash command
- interactive buttons
- approval modals
- event verification
- channel-specific configuration

Example commands:

```text
/panopticon risks
/panopticon project checkout-service
/panopticon ask why did the latest pipeline fail
```

Example buttons:

```text
Approve GitLab Comment
Open In Panopticon
Mark False Positive
Send To On-Call
Create Follow-Up Issue
```

### Backend Work

Add endpoints:

```text
POST /slack/commands
POST /slack/interactions
POST /slack/events
```

Add Slack signature verification.

### Frontend Work

Add Slack setup status:

- webhook configured
- bot token configured
- signing secret configured
- default channel configured
- dry-run/live mode

### Acceptance Criteria

- Slack commands can query Panopticon.
- Slack buttons can approve or reject proposed actions.
- Slack messages link back to dashboard records.

## Phase 7: Safe Code-Changing Agent

### Goal

Let Panopticon prepare code/config fixes safely through GitLab branches and merge requests.

Panopticon must never directly push to the default branch.

### Supported First Fix Types

- add missing CI retry or timeout configuration
- add a simple missing test scaffold
- add deployment health check
- add rollback note or runbook update
- fix obvious `.gitlab-ci.yml` issue

### Backend Work

Add endpoints:

```text
POST /api/fix-plans
GET /api/fix-plans
GET /api/fix-plans/{id}
POST /api/fix-plans/{id}/approve
POST /api/fix-plans/{id}/reject
POST /api/fix-plans/{id}/create-branch
POST /api/fix-plans/{id}/open-merge-request
```

Safety constraints:

- branch-only changes
- approval required
- file count limit
- diff preview
- no secret edits
- no destructive changes
- full audit log

### Frontend Work

Add fix plan preview:

- problem
- proposed files
- proposed diff
- risk
- rollback plan
- approve/reject buttons

### Acceptance Criteria

- Panopticon can propose a fix plan.
- User can preview the diff.
- User approval is required before branch/MR creation.
- The final output is a GitLab merge request.
- Local development uses dry-run branch, commit, and MR payloads by default.
- The MCP endpoint exposes fix-plan tools for external agent runtimes.

## Phase 8: Observability Integrations

### Goal

Correlate GitLab activity with production symptoms.

GitLab tells us what changed. Observability tells us what broke.

### Integrations

Start with generic ingestion patterns:

- OpenTelemetry-compatible events
- Prometheus-style alert webhooks
- Sentry-style issue webhooks
- Grafana alert webhooks

### Backend Work

Add generic observability event model:

- service
- environment
- severity
- signal type
- metric name
- trace id
- log excerpt
- alert URL
- timestamp

Correlate:

```text
deployment commit
+ failed pipeline
+ error spike
+ rollback
+ incident alert
= probable root cause
```

### Frontend Work

Add incident correlation view:

- timeline
- deployment marker
- pipeline failure marker
- alert marker
- suspected cause
- recommended rollback/fix

### Acceptance Criteria

- Panopticon can ingest at least one observability webhook shape.
- Incidents can show correlated GitLab and observability signals.
- Root cause explanations cite both code activity and production symptoms.
- Observability context is available through REST and MCP tools.
- Demo data includes correlated observability signals for local validation.

## Phase 9: Metrics And Engineering Health

### Goal

Make Panopticon useful over weeks and months, not only during a single incident.

### Metrics

Track:

- deployment frequency
- lead time for changes
- change failure rate
- recovery time
- risky MR rate
- failed pipeline rate
- flaky job signatures
- review bottleneck time
- recommendation acceptance rate
- false positive rate

### Frontend Work

Add:

```text
/metrics
```

Views:

- organization overview
- project comparison
- risk trend
- pipeline trend
- incident trend
- recommendation quality

### Acceptance Criteria

- Metrics are derived from stored records.
- Project trends are visible.
- The app can show whether Panopticon is reducing repeated failures.
- Metrics include GitLab delivery state, action throughput, incidents, fix plans, and observability correlations.
- Metrics are exposed through REST and MCP tools.

## Phase 10: Feedback And Learning Loop

### Goal

Make recommendations improve based on developer feedback.

### Feedback Types

- helpful
- not helpful
- false positive
- already known
- fixed
- ignored

### Backend Work

Add:

```text
POST /api/recommendations/{id}/feedback
GET /api/recommendations/feedback/summary
```

Use feedback to adjust:

- duplicate suppression
- risk scoring
- project-specific sensitive paths
- recommendation ranking
- prompt context

### Frontend Work

Add feedback controls to:

- recommendation cards
- action details
- chat answers
- Slack interactive messages

### Acceptance Criteria

- Users can mark recommendation quality.
- Feedback is stored.
- Project-specific rules can be derived from feedback.

## Recommended Build Order

We should build in this order:

1. GitLab Project Sync
2. Project Detail Workspace
3. Recommendation Engine V2
4. Approval And Action System
5. Chat Interface
6. Slack App Upgrade
7. Safe Code-Changing Agent
8. Observability Integrations
9. Metrics And Engineering Health
10. Feedback And Learning Loop

This order is deliberate.

GitLab project sync must come first because every later feature needs real project context. Chat, Slack commands, recommendations, and code-changing actions are weak if the system only knows about isolated webhook events.

## Implementation Status

- Phase 1: GitLab Project Sync is implemented.
- Phase 2: Project Detail Workspace is implemented.
- Phase 3: Recommendation Engine V2 is implemented.
- Phase 4: Approval And Action System is implemented.
- Phase 5: Chat Interface is implemented with intent-specific retrieval for pipeline, risk, merge request, incident, memory, and action questions. Chat now sends focused evidence to Vertex Gemini through the backend reasoner when Gemini is enabled, and uses deterministic answers only as fallback. Chat answers should stay focused on the user question and cite only the records used.
- Phase 5.5: Agent Tool Layer is implemented with REST tool invocation and an MCP-compatible JSON-RPC endpoint for tool discovery and calls.
- Phase 5.6: Chat Hardening is implemented with rich multi-project seed data, project inference from natural language, priority triage questions, broader MCP chat context tools, and incomplete Gemini answer repair.
- Phase 6: Slack App Upgrade is implemented with signed slash commands, interactions for action approval/rejection, Events API URL verification, and dashboard setup status.
- Phase 7: Safe Code-Changing Agent is implemented with fix-plan records, approval/rejection, dry-run GitLab branch/commit/MR execution, safety validation, a `/fix-plans` UI, and MCP tools for creating/listing fix plans.
- Phase 8: Observability Integrations is implemented with generic observability event ingestion, Grafana/Prometheus/Sentry-style webhook normalization, stored incident correlations, correlated GitLab timelines, a `/observability` UI, demo observability seed data, and MCP tools for observability context.
- Phase 9: Metrics And Engineering Health is implemented with organization health, project rankings, daily metric snapshots, action throughput, observability-aware scoring, a `/metrics` UI, and MCP tools for metrics context.
- Phase 10: Feedback And Learning Loop is deferred.
- Next recommended phase: production hardening, Agent Builder packaging, or Phase 10 when feedback becomes the priority.

## Immediate Next Implementation Pipeline

The next concrete implementation sprint should either package Panopticon for Vertex AI Agent Builder / Agent Engine or begin production hardening. The Phase 10 feedback loop stays deferred for now.

### Optional Sprint 10A: Production Hardening

Make the product easier to operate outside local development.

Deliverables:

- production migration runbook
- environment validation endpoint
- deployment Docker/Compose cleanup
- safer secret redaction in logs and payload previews
- health checks for GitLab, Slack, Vertex Gemini, database, and MCP tools
- smoke test script that exercises the full local flow

### Optional Sprint 10B: Agent Builder Packaging

Prepare the existing agent/tool layer for managed Google Cloud agent runtime.

Deliverables:

- document Agent Builder / Agent Engine deployment shape
- define MCP tool registration requirements
- isolate the agent orchestration entrypoint from FastAPI routes
- add a cloud deployment checklist
- add a managed-runtime smoke test plan

### Deferred Phase 10

The feedback and learning loop remains important, but it is intentionally paused until after metrics are stable in real usage.

Deferred work:

- recommendation feedback buttons
- false-positive labels
- recommendation acceptance metrics
- project-specific learned rules from user feedback
- Slack feedback actions

The reason is sequencing: feedback should be added only after we can measure it against delivery health and recommendation quality.
- backend tests pass
- frontend build passes

## Run And Verification Commands

When running locally, always clear ports first.

Backend:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
$ports = @(8000); foreach ($port in $ports) { Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon
$ports = @(3000, 3001); foreach ($port in $ports) { Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }
cd frontend
npm.cmd run dev -- --port 3000
```

Tests:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m pytest -q
```

Frontend build:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run build
npm.cmd audit --omit=dev
```

## Safety Defaults

Keep these defaults unless explicitly changing modes:

```env
DRY_RUN_ACTIONS=true
DISPATCH_ACTIONS=true
```

Only set `DRY_RUN_ACTIONS=false` when intentionally testing live GitLab or Slack behavior.

## Final Product Standard

Panopticon should feel useful to a developer within five minutes:

1. Connect GitLab.
2. Sync projects.
3. See current risks and failures.
4. Ask a question.
5. Get an evidence-backed answer.
6. Approve a useful action.
7. See the action reflected in GitLab or Slack.

Every future change should be judged against that standard.
