# Panopticon

Autonomous GitLab operations intelligence agent for monitoring merge requests, CI/CD pipelines, deployments, incidents, and delivery bottlenecks.

Panopticon is intentionally not a coding copilot. It is an operations coordination layer that ingests GitLab activity, detects delivery risk, investigates failures, stores operational memory, and surfaces recommendations through a dashboard, GitLab comments, and Slack alerts.

## MVP Scope

- GitLab webhook ingestion
- Operational memory storage
- Deployment risk scoring
- CI/CD failure intelligence
- Merge request bottleneck detection
- Incident timeline generation
- Local deterministic reasoning with Gemini-ready prompt boundaries
- Next.js operational dashboard
- Demo payload replay for hackathon walkthroughs

## Repository Layout

```text
backend/          FastAPI API, intelligence modules, integrations, persistence
frontend/         Next.js + Tailwind dashboard
prompts/          Gemini prompt templates
workflows/        Demo event payloads and replay scripts
infrastructure/   Docker and Cloud Run deployment assets
docs/             Product and implementation notes
```

## Quick Start

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.scripts.seed_demo --reset
uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:3000`.

## Local Defaults

The backend defaults to SQLite for local development at `backend/panopticon.db`. Production should use PostgreSQL through `DATABASE_URL`.

## Environment

Copy `backend/.env.example` to `backend/.env` and configure real integrations when ready.

See `docs/INTEGRATIONS.md` for GitLab, Slack, and Gemini configuration.
See `docs/PRODUCTION_SETUP.md` for the production deployment path.
See `docs/USER_SETUP_CHECKLIST.md` for the concrete values you must create in GitLab and Slack.

Gemini smoke test:

```powershell
cd backend
python -m app.scripts.check_gemini
```

Slack smoke test:

```powershell
cd backend
python -m app.scripts.check_slack
```

## Demo Reset

Replay a clean local story:

```powershell
cd backend
python -m app.scripts.seed_demo --reset
```

This creates one risky merge request, one failed pipeline, one rollback incident, and dispatched dry-run recommendations.
