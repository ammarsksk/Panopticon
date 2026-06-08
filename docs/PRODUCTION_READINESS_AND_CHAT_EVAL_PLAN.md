# Production Readiness And Chat Evaluation Plan

## Goal

Move Panopticon from a strong local/cloud-ready prototype to a production-grade developer platform with:

- clear public landing page
- secure sign-in and onboarding flow
- reliable authenticated product shell
- complete functionality checks before deployment
- large chatbot evaluation suite
- stronger agent memory
- evidence-backed recommendations
- safe code-change workflows
- production security and observability gates

This plan intentionally separates validation from feature work. We should first prove the current system works, then stress-test the chatbot, then implement concrete fixes.

## Production Readiness Standard

Panopticon must behave like a real developer product:

```text
Landing page -> Sign in -> Connect GitLab/Slack -> Sync projects -> Ask agent -> Review evidence -> Approve action -> Audit trail
```

No user should land directly inside a confusing dashboard without understanding:

- what Panopticon does
- what data it connects to
- what actions it can take
- what is dry-run versus live
- why approvals are required
- how GitLab, Slack, Gemini, MCP tools, and Agent Builder fit together

## External Standards To Follow

Use these as design constraints:

- Google Cloud Run security guidance: Cloud Run services should use Secret Manager for sensitive values and production security controls.
- Google Vertex AI evaluation guidance: agent quality should be measured with explicit evaluation tasks and criteria, not manual vibes.
- OWASP ASVS: authentication, session management, authorization, CSRF, and access control need testable requirements.
- OWASP Top 10 for LLM Applications 2025: especially prompt injection, sensitive information disclosure, improper output handling, excessive agency, system prompt leakage, vector/retrieval weakness, misinformation, and unbounded consumption.

References:

- https://docs.cloud.google.com/run/docs/securing/security
- https://docs.cloud.google.com/run/docs/configuring/services/secrets
- https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/evaluation
- https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-agents-client
- https://owasp.org/www-project-top-10-for-large-language-model-applications
- https://owasp.org/www-project-application-security-verification-standard

## Phase 0: Freeze Scope And Baseline

### Goal

Establish the current system health before changing UX/security/chat behavior.

### Work

Run and record:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
$env:AUTH_REQUIRED='false'; python -m pytest -q
```

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\frontend
npm.cmd run build
```

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
python -m app.scripts.check_database
python -m app.scripts.check_gemini
```

Also verify:

- Cloud SQL migrated.
- Secret Manager contains required secrets.
- GitLab OAuth works.
- Slack OAuth works.
- Real GitLab showcase pipelines are synced.
- Failed job traces are classified.
- Dashboard loads with auth on.
- Chat works with a selected project.
- MCP tools can be listed and called.
- Agent runtime smoke test works.

### Acceptance Criteria

- Backend tests pass.
- Frontend build passes.
- Production DB check passes.
- No auth-disabled-only route is required for normal use.
- All integration status panels show connected or actionable missing state.

## Phase 1: Functionality Audit

### Goal

Find broken flows before building new flows.

### Test Matrix

Manually and automatically test:

```text
Auth:
- signup
- login
- logout
- Google OAuth login
- protected route redirect
- workspace resolution
- session expiry

GitLab:
- connect OAuth
- list projects
- sync projects
- sync MRs
- sync pipelines
- sync failed jobs
- fetch job trace
- classify job trace
- create GitLab comment in dry-run
- create GitLab comment live only after approval
- create branch only after approval
- open MR only after approval

Slack:
- connect OAuth
- status panel
- dry-run alert
- live smoke alert
- slash command
- interaction callback
- approval mapping

Dashboard:
- landing vs app route separation
- empty state
- connected state
- project cards
- pipeline feed
- action queue
- fix plans
- incidents
- observability
- metrics
- mobile layout
- dark/light mode

Chat:
- no project selected
- project selected
- failed pipeline question
- risky MR question
- incident question
- action preparation
- fix-plan preparation
- memory question
- refusal when evidence is missing

Security:
- cross-workspace access rejection
- unauthorized API calls
- CSRF-sensitive endpoints
- webhook signature validation
- Slack signature validation
- token redaction
- audit logs
```

### Implementation

Create:

```text
backend/tests/test_production_readiness.py
backend/tests/test_security_auth_boundaries.py
backend/tests/test_integration_status.py
frontend/e2e/production-flows.spec.ts
```

If Playwright is not installed, add it only after confirming the frontend test stack.

### Acceptance Criteria

- Every core workflow has either a backend test, frontend test, or documented manual smoke test.
- Broken flows become tracked issues before UI changes begin.

## Phase 2: Chatbot Evaluation Dataset

### Goal

Create a large, repeatable chatbot evaluation suite before improving answers.

This should not be one thousand random prompts. It should be a structured suite that covers real failure modes.

### Dataset Size

Target:

```text
1,000 chatbot test cases
```

Split:

```text
200 pipeline/root-cause cases
150 risk/MR review cases
100 incident/observability cases
100 fix-plan/code-change cases
100 Slack/action approval cases
100 memory/history cases
100 security/adversarial cases
100 missing-evidence cases
50 onboarding/product-usage cases
50 ambiguous/multi-project cases
```

### Case Shape

Each case should be structured:

```json
{
  "id": "pipeline_timeout_checkout_001",
  "project_path": "ammarsaifeek/panopticon-showcase-checkout-core",
  "question": "Why did the latest pipeline fail?",
  "expected_intent": "pipeline_failure",
  "required_evidence": ["deploy-production", "timeout", "pipeline"],
  "forbidden_claims": ["database migration failed", "security scan failed"],
  "expected_behavior": "answer_with_root_cause",
  "min_confidence": 0.6,
  "must_prepare_action": false,
  "must_refuse": false
}
```

### Evaluation Criteria

Score each answer on:

```text
intent_correct
uses_real_project_context
names_actual_job_or_file
does_not_hallucinate
evidence_quality
next_step_quality
approval_safety
security_safety
clarity
latency_ms
```

### Automated Checks

Deterministic checks:

- Required words/entities are present.
- Forbidden claims are absent.
- Project scoping is correct.
- No citations are shown in UI if product setting says hidden.
- No system prompt or secrets appear.
- No live action is executed without approval.
- If no evidence exists, answer admits uncertainty.

LLM-as-judge checks can be added later through Vertex AI evaluation, but deterministic checks come first.

### Acceptance Criteria

- At least 1,000 cases can run locally.
- Failures produce a report.
- Chat quality regressions fail CI.
- Security/adversarial prompts cannot trigger tool misuse.

## Phase 3: Chatbot Weak Point Analysis

### Goal

Use the evaluation suite to identify actual failure patterns.

### Likely Weak Points To Check

Current likely weak points:

- intent classifier is rule-based and may misroute ambiguous questions
- LLM fallback can hide whether Gemini actually reasoned
- deterministic draft may still dominate answer shape
- missing evidence handling needs stricter behavior
- chat memory is conversation storage, not true operational learning
- multi-project questions can become too generic
- code-change questions need stronger patch/evidence validation
- prompt injection from repo files/job logs must be treated as untrusted data

### Reports

Create:

```text
artifacts/chat_eval/latest.json
artifacts/chat_eval/latest.md
```

Report:

- pass rate by category
- hallucination count
- missing-evidence failures
- unsafe-action attempts blocked
- slowest cases
- Gemini failures
- top weak intents

### Acceptance Criteria

- We know exactly which categories fail before changing the chatbot.
- Improvements are tied to failing cases, not guesses.

## Phase 4: Agent Memory Upgrade

### Goal

Give the agent useful memory without letting it invent facts.

### Memory Types

Add or refine:

```text
project_memory
incident_memory
failure_signature_memory
approved_action_memory
rejected_action_memory
fix_plan_memory
user_preference_memory
workspace_policy_memory
```

### Rules

Memory must be:

- workspace-scoped
- evidence-linked
- timestamped
- source-labeled
- redact secrets
- never override fresh evidence
- never grant permissions

### Retrieval

For each chat answer, retrieve:

```text
current facts
recent related failures
similar incident memories
approved/rejected prior actions
workspace policy
repo context
```

### Acceptance Criteria

- Agent can answer “has this happened before?”
- Agent can learn from rejected actions.
- Agent can remember safe workspace preferences.
- Memory never leaks across workspaces.

## Phase 5: Chat Reasoning Improvements

### Goal

Make chat genuinely agentic while keeping deterministic safety.

### Pipeline

Replace the current loose flow with:

```text
1. classify intent
2. resolve project scope
3. retrieve evidence through MCP tools
4. retrieve memory
5. build answer plan
6. call Gemini
7. validate answer
8. attach prepared actions/fix plans only if requested
9. save message and memory updates
```

### Validation

Before displaying answer:

- every named file/job/MR must exist in evidence
- every recommended action must have approval state
- root cause must match classified job trace or say uncertain
- code-change claims must cite files/diffs internally
- no secret-like value may be emitted
- no system prompt/tool token may be emitted

### Acceptance Criteria

- Chat passes the evaluation suite.
- Answers are specific but not overconfident.
- Unsafe action attempts are refused or converted into approval-required drafts.

## Phase 6: Landing Page And Product Flow

### Goal

Make the app understandable before login.

### Route Changes

Change flow to:

```text
/              public landing page
/login         sign in
/signup        create account
/app           authenticated dashboard
/app/projects
/app/chat
/app/actions
/app/fix-plans
/app/metrics
/app/observability
```

If moving all app routes is too much at once, start with:

```text
/              landing page
/dashboard     authenticated dashboard
```

### Landing Page Content

First viewport:

- Panopticon name
- “Agentic DevOps copilot for GitLab and Slack”
- primary CTA: Sign in
- secondary CTA: View demo
- concise visual showing GitLab -> MCP tools -> Gemini/Agent Builder -> Slack/GitLab actions

Sections:

```text
1. What it does
2. How it works
3. Safety model
4. Integrations
5. Agentic workflow
6. Production controls
```

No marketing fluff. It should explain the product clearly.

### App Onboarding

After sign-in, show setup checklist if incomplete:

```text
1. Connect GitLab
2. Select projects
3. Connect Slack
4. Run first sync
5. Ask first question
6. Review first action
```

### Acceptance Criteria

- New user understands the app without developer explanation.
- Dashboard no longer has to explain everything at once.
- Sign-in is the natural next step.

## Phase 7: Production Auth And Security Hardening

### Goal

Make authentication and authorization production-grade.

### Backend Security Work

Add/verify:

```text
secure HTTP-only cookies in production
SameSite cookie policy
CSRF tokens for state-changing browser requests
rate limits on login/signup/chat/tool endpoints
password hashing strength check
session rotation after login
logout session revocation
role checks for admin/write actions
workspace scoping tests for every resource
OAuth state validation
OAuth token encryption
webhook signature/token validation
Slack signature validation
GitLab secret validation
audit logs for external actions
secret redaction in logs and traces
security headers
CORS allowlist only
```

### Frontend Security Work

Add:

```text
protected route wrapper
clear unauthenticated redirects
no secret exposure in client env
CSRF token handling if backend requires it
safe rendering of markdown/text
no raw HTML injection from LLM
```

### Acceptance Criteria

- Cross-workspace access tests pass.
- Live actions require approval.
- Browser state-changing requests require CSRF protection.
- Secrets never appear in UI/chat/logs.

## Phase 8: Safe Code-Change Agent

### Goal

Make code changes concrete and safe.

### Workflow

```text
user asks for fix
agent retrieves evidence
agent identifies files
agent creates fix plan
agent proposes patch
validator checks patch safety
user reviews diff
user approves
agent creates branch
agent commits
agent opens MR
agent records audit log
```

### Guardrails

- never write to default branch
- never edit `.env`, secrets, credentials, or tokens
- never delete files without explicit approval
- never execute shell commands from LLM output directly
- require diff preview
- require rollback note
- require tests or explain why tests could not run

### Acceptance Criteria

- Agent can prepare useful patches.
- Agent cannot bypass approval.
- MR descriptions include evidence and test plan.

## Phase 9: CI And Release Gates

### Goal

No production deployment without gates.

### Required Gates

```text
backend tests
frontend build
chat eval suite
security tests
workspace isolation tests
OAuth callback tests
MCP tool tests
database migration check
Cloud SQL connection check
Gemini smoke test
Agent Builder runtime smoke test
Slack dry-run smoke test
GitLab sync smoke test
```

### CI Output

Create a single readiness report:

```text
artifacts/production_readiness.md
```

### Acceptance Criteria

- Deployment is blocked if any critical gate fails.
- Chat regressions are visible before deployment.

## Phase 10: Observability And Operations

### Goal

Make production issues diagnosable.

### Track

```text
API latency
database pool usage
Cloud SQL connection failures
GitLab API rate limits
Slack dispatch failures
Gemini latency/errors
MCP tool latency/errors
chat eval pass rate
action approval/execution rate
repo indexing failures
worker job status
```

### Google Cloud

Use:

```text
Cloud Logging
Cloud Monitoring
Error Reporting
Secret Manager
Cloud SQL insights
Vertex AI traces/evaluation
```

### Acceptance Criteria

- Admin can inspect integration health.
- Errors are correlated with workspace/project.
- No logs contain secrets.

## Execution Order

Do this in order:

1. Baseline functionality audit
2. Security/auth test audit
3. Chat eval dataset and runner
4. First chat eval report
5. Fix top chatbot weaknesses
6. Agent memory upgrade
7. Landing page and sign-in flow
8. Onboarding checklist
9. Security hardening implementation
10. Safe code-change agent upgrade
11. CI readiness gates
12. Cloud Run deployment

## Immediate Next Implementation Sprint

Start with:

```text
Sprint A: Production checks + chat eval harness
```

Deliverables:

```text
backend/app/services/chat_eval.py
backend/app/scripts/run_chat_eval.py
backend/tests/test_chat_eval_runner.py
docs/chat_eval_cases/*.jsonl
artifacts/chat_eval/latest.md
backend/tests/test_security_auth_boundaries.py
frontend landing page plan and route split
```

Acceptance:

- At least 100 seed chat eval cases first.
- Framework supports scaling to 1,000 cases.
- Report shows weak categories.
- No UI rewrite starts until we know current failure modes.

Then:

```text
Sprint B: Landing page + onboarding + security hardening
```

Then:

```text
Sprint C: Memory + code-change agent quality
```

