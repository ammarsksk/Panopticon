# Panopticon Submission Answers

Use this file as paste-ready copy for the project submission form.

## Elevator Pitch

Panopticon is an agentic GitLab operations copilot that explains CI/CD failures, learns repository context, and drafts approval-gated fixes across GitLab and Slack.

## Built With

Python, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Cloud SQL, pgvector, Next.js, React, TypeScript, Tailwind CSS, Google Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Vertex AI Gemini 2.5 Pro, Gemini embeddings, Vertex AI Agent Builder / Agent Engine compatible runtime, GitLab API, GitLab OAuth, GitLab CI/CD, Slack OAuth, Slack webhooks, MCP-style JSON-RPC tools, Docker, pytest.

## Try It Out Links

```text
Live demo:
https://panopticon-frontend-226094931757.us-central1.run.app

Backend API:
https://panopticon-backend-226094931757.us-central1.run.app

Source code:
https://gitlab.com/ammarsaifeek/panopticon
```

If the GitLab repository is private at submission time, make it public or replace the source link with the public repository URL before submitting.

## What Google Cloud Products Did You Use?

We used Google Cloud as the production backbone for Panopticon:

- **Cloud Run** for the production backend and frontend services. The FastAPI backend and Next.js frontend are deployed as separate Cloud Run services.
- **Cloud SQL for PostgreSQL** as the production relational database for workspaces, users, GitLab projects, pipeline records, operational memory, repository indexes, fix plans, audit records, and action state.
- **Cloud SQL pgvector / vector search support** for production-grade repository memory and semantic code retrieval.
- **Vertex AI Gemini 2.5 Pro** for live agent reasoning over GitLab, Slack, repository, memory, and incident context.
- **Gemini embeddings** through Vertex AI for repository code chunk embeddings and semantic retrieval.
- **Vertex AI Agent Builder / Agent Engine compatible runtime** for packaging Panopticon as a managed agent runtime that calls workspace-scoped MCP tools instead of directly accessing databases or third-party tokens.
- **Cloud Build** for building production Docker images.
- **Artifact Registry** for storing backend and frontend container images.
- **Secret Manager** for production secrets such as database URLs, OAuth credentials, webhook secrets, and runtime tokens.
- **IAM service accounts** for least-privilege runtime access to Cloud SQL, Secret Manager, and Vertex AI.
- **Cloud Logging and Cloud Run logs** for production debugging and deployment verification.

## Other Tools Or Products Used

- **GitLab** for source repositories, merge requests, pipeline data, failed jobs, OAuth integration, CI/CD configuration, and approval-gated remediation merge requests.
- **Slack** for operational alerts, action notifications, and team-facing incident communication.
- **Model Context Protocol style tools** for structured agent access to project summaries, pipeline context, repository files, code search, memory, recommendations, and fix plans.
- **Docker** for reproducible service packaging.
- **pytest** for backend, security, chat, MCP, OAuth, and fix-plan testing.
- **Next.js / React / TypeScript** for the product dashboard, chat interface, authenticated workspace shell, fix-plan diff viewer, and operations console.
- **FastAPI** for the backend API, webhook receivers, OAuth callbacks, MCP endpoint, and agent orchestration layer.
- **PostgreSQL / SQLAlchemy / Alembic** for durable state, migrations, workspace isolation, and production data modeling.
- **GitLab CI/CD showcase projects** for realistic failed pipeline and code-change scenarios.

## About The Project

### Inspiration

Panopticon came from a very common engineering pain: when a deployment or CI/CD pipeline fails, developers rarely have one clean place to understand what happened.

In a real team, the evidence is scattered. The merge request is in GitLab. The failed pipeline is somewhere else. The failed job trace may be missing, huge, or noisy. The related code lives across multiple files. Slack has the human conversation. Incident timelines are usually reconstructed manually after the fact. A developer has to jump between tabs, guess which files matter, ask teammates for context, and then decide whether it is safe to comment, alert, roll back, or prepare a fix.

We wanted to build an agent that behaves less like a generic chatbot and more like an operations teammate. The goal was not just "ask an LLM why CI failed." The goal was:

```text
Connect the real tools -> retrieve real evidence -> reason over code and operations -> propose a safe action -> require approval before anything writes externally.
```

That became Panopticon.

### What Panopticon Does

Panopticon is an agentic operations console for GitLab teams. It connects to GitLab and Slack, syncs repository and pipeline context, stores operational memory, and gives developers a single place to ask questions such as:

- "Why did this pipeline fail?"
- "Which risks should I inspect first?"
- "What changed before the incident?"
- "Which files are related to this failure?"
- "Draft a fix plan for this code issue."
- "Prepare the Slack alert, but do not send it yet."
- "Create an MR for the proposed fix after approval."

The product has four major layers:

1. **Operations intelligence**
   Panopticon syncs GitLab projects, merge requests, pipelines, jobs, failed traces, risk assessments, incidents, recommendations, and action history.

2. **Repository-aware agent memory**
   It indexes repository files, chunks code, extracts symbols, records file metadata, stores operational memory, and retrieves relevant context when the user asks a question.

3. **Agentic chat and tools**
   The chat is backed by structured MCP-style tools. The agent can search code, read files, inspect project state, retrieve memory, build context packs, draft patches, and create safe fix plans.

4. **Approval-gated execution**
   Panopticon can prepare GitLab comments, Slack alerts, branches, fix plans, and merge requests, but live external writes remain gated behind explicit approval.

### How We Built It

The backend is a FastAPI service with SQLAlchemy models and Alembic migrations. It owns authentication, workspaces, GitLab sync, Slack integration, repository indexing, operational memory, action approvals, fix plans, and the MCP-compatible tool boundary.

The frontend is a Next.js and React application. It provides the landing page, sign-in flow, dashboard, GitLab project view, chat interface, action approvals, fix plans, observability correlation, metrics, and dark/light UI polish.

The agent stack is built around a tool-first architecture:

```text
User question
  -> classify intent
  -> resolve project/workspace
  -> call MCP-style tools
  -> retrieve GitLab, repo, memory, and incident context
  -> call Gemini 2.5 Pro
  -> validate output
  -> show answer, action, or fix plan
  -> require approval before external writes
```

For Google Cloud, Panopticon runs on Cloud Run with Cloud SQL PostgreSQL as the production database. Vertex AI Gemini 2.5 Pro powers live reasoning, and Gemini embeddings support repository-aware retrieval. The project also includes a Vertex AI Agent Builder / Agent Engine compatible runtime that exposes Panopticon's agent as a managed runtime while still routing every operation through the backend's workspace-scoped MCP tools.

### What Makes It Agentic

Panopticon is agentic because it does not only generate text. It can plan, retrieve evidence, call tools, maintain memory, and prepare real actions.

The important part is that agency is bounded. The agent can:

- search repositories
- read indexed files
- inspect pipeline and MR context
- retrieve operational memory
- draft code patches
- create fix plans
- prepare Slack or GitLab actions
- open safe approval flows

But it cannot silently:

- write to the default branch
- send Slack alerts without approval
- post GitLab comments without approval
- expose secrets
- bypass workspace isolation
- treat old memory as stronger than fresh evidence

That balance is the core design: useful automation without unsafe autonomy.

### Challenges We Faced

The biggest challenge was making the chatbot useful when pipeline traces are missing. A simple implementation would say, "I cannot determine the cause because the job trace is unavailable." That is not enough for developers. We rebuilt the agent around repository context, memory, project metadata, pipelines, merge requests, and code search so the assistant can still provide useful answers and next steps.

Another challenge was authentication in production. The backend and frontend are separate Cloud Run services, which means cookies and server-side rendering can behave differently from local development. We had to adjust protected pages so authenticated data loads through the browser session instead of relying on the frontend server to possess backend-domain cookies.

The third major challenge was safe code changes. It is easy to generate a patch-looking answer. It is much harder to make the workflow production-safe: evidence, changed files, diff preview, test plan, rollback plan, approval state, branch creation, MR creation, and audit history all need to be explicit.

### What We Are Proud Of

We are proud that Panopticon became a full product, not just a prompt demo. It has a real dashboard, OAuth login, workspace isolation, GitLab sync, Slack integration, repository indexing, MCP-style tools, operational memory, chat evaluation, code-patch evaluation, and production deployment.

The latest local validation artifacts show:

| Validation Area | Result |
| --- | ---: |
| Chat evaluation cases | 119/119 passing |
| Chat eval pass rate | 100.0% |
| Chat eval p95 latency | 130.1 ms |
| Code patch evaluation cases | 500/500 passing |
| Code patch eval p95 latency | 0.2 ms |
| Backend test suite | 127 tests passing |
| Live actions without approval | 0 by design |

These are not vanity metrics. They directly map to the product's reliability goals: grounded answers, safe patch generation, approval-gated actions, and fast enough interaction loops for developer workflows.

### What We Learned

The main lesson was that agents need product architecture, not just model calls. The LLM is only one part of the system. The real quality comes from:

- clean data models
- reliable sync pipelines
- scoped tools
- strong memory rules
- evidence retrieval
- validation checks
- user-visible approvals
- evaluation suites
- production auth and deployment hygiene

We also learned that operational agents should be honest about uncertainty. If job traces are missing, Panopticon should say that clearly, but still inspect repository context and propose useful next checks instead of stopping.

### What's Next

The next step is to deepen the production code-change workflow:

- stronger repository-scale retrieval with pgvector and Gemini embeddings
- larger chat evaluation suites
- richer tool-call timelines in the UI
- more robust patch validation
- automated MR descriptions with evidence and tests
- production observability for Gemini latency, GitLab rate limits, and action outcomes
- deeper Agent Builder deployment and evaluation integration

The long-term vision is that Panopticon becomes the operations copilot developers trust during delivery incidents: not a bot that guesses, but an agent that reads the repo, understands the pipeline, remembers prior decisions, proposes safe fixes, and keeps humans in control.
