# Production Functionality Audit

This checklist maps the phase 1 readiness matrix to current automated coverage and manual smoke checks.

## Automated Backend Coverage

Run:

```powershell
cd C:\Users\LENOVO\Downloads\Panopticon\backend
$env:AUTH_REQUIRED='false'; python -m pytest -q
```

Covered by tests:

- Auth signup, login, logout session storage, protected unauthenticated API rejection, secure production cookie flags.
- Workspace isolation for project lists, project detail access, chat project access, and chat thread reads.
- Google, GitLab, and Slack OAuth URL/status/token handling.
- GitLab project sync shaping, pipeline/job sync, failed trace classification, and showcase project provisioning logic.
- Slack slash command, interaction callback, and approval mapping.
- Action approval before execution and dry-run dispatch safety.
- Fix-plan creation, approval, branch/MR safety, and approval-gated execution.
- Agent/MCP tool listing and runtime bearer-token workspace resolution.
- Production configuration validation, Cloud Run Cloud SQL wiring, Secret Manager references, and ignored local secret files.
- Chat evaluation runner, report generation, and deterministic evaluation checks.

## Manual Smoke Checks

Run these against the local app before deployment:

1. Sign in with Google OAuth and confirm the dashboard loads.
2. Connect GitLab OAuth and confirm the connected state remains visible after refresh.
3. Confirm projects auto-sync or run sync from the project area, then open a project detail page.
4. Refresh repo context for one project and confirm indexed files appear.
5. Open Chat, ask a project-specific pipeline question, and confirm the answer names stored evidence without exposing citations in the UI.
6. Ask Chat to prepare an action and confirm it appears as pending approval.
7. Ask Chat to prepare a fix plan and confirm no GitLab branch/MR is created before approval.
8. Connect Slack OAuth and confirm Slack status shows connected.
9. Run a Slack dry-run alert and confirm the payload preview is visible without live dispatch.
10. Toggle dark/light mode on dashboard, projects, actions, fix plans, metrics, observability, and chat.
11. Check mobile viewport for dashboard, project detail, and chat.

## E2E Status

The frontend currently has no Playwright/Cypress stack in `frontend/package.json`. Do not add browser e2e dependencies silently. When approved, add:

```text
frontend/e2e/production-flows.spec.ts
```

Initial e2e coverage should verify:

- public landing/sign-in route separation
- authenticated dashboard redirect behavior
- onboarding integration status states
- project list and project detail navigation
- chat send/loading/response states
- action approval UI feedback
- dark/light mode persistence
