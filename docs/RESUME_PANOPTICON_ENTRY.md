# Panopticon Resume Entry

Use this as a drop-in project entry. It matches the current resume style: compact stack line, two bullets, with performance claims only where they are meaningful and defensible.

## Recommended Version

**Panopticon [GitHub/GitLab]** May 2026 - Jun 2026  
FastAPI, Next.js, PostgreSQL, GitLab API/OAuth, Slack OAuth, Vertex AI Gemini, Google Agent Builder, MCP, Docker

- Built an agentic DevOps copilot that connects GitLab, Slack, Vertex Gemini, and an MCP tool server to inspect CI/CD failures, classify job traces, ground recommendations in repository context, and generate approval-gated Slack alerts, GitLab comments, and remediation merge requests.
- Engineered a low-latency agent context layer over PostgreSQL-backed operational memory, with MCP chat-context retrieval measured at ~30 ms p95 locally; added OAuth-scoped workspaces, audit logging, dry-run/live action controls, and a production-grade Next.js operations console.

## Shorter Version

**Panopticon [GitHub/GitLab]** May 2026 - Jun 2026  
FastAPI, Next.js, PostgreSQL, GitLab API/OAuth, Slack OAuth, Vertex AI Gemini, Google Agent Builder, MCP

- Built an agentic DevOps copilot that syncs GitLab CI/CD failures and repository context into a grounded operations dashboard and chat interface.
- Implemented an MCP-backed agent context layer with ~30 ms p95 local retrieval, enabling approval-gated recommendations for Slack alerts, GitLab comments, and remediation MRs.

## Metrics Considered

- Local MCP context retrieval benchmark: `get_chat_context` around `30 ms p95`
- Backend tests: `70 passed`, useful for validation but not worth putting in the bullet unless the resume has space.
- Frontend production build: passed, useful for validation but not a resume metric.
- Real GitLab data was used to validate the workflow, but repository/pipeline counts are intentionally omitted from the resume entry because they are not strong performance metrics.

## Placement Suggestion

This is stronger than the current `Txcat` entry for AI-agent/platform roles because it demonstrates production-style integrations, OAuth, real GitLab CI data, MCP tooling, agentic workflows, and LLM-grounded remediation.
