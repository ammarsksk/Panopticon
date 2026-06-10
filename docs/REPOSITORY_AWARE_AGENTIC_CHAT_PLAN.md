# Repository-Aware Agentic Chat Plan

## Problem

The current chatbot is too pipeline-trace-centric. When failed job traces are missing, it often says it cannot determine the cause instead of using the full repository, project metadata, prior incidents, merge requests, pipeline history, and operational memory.

The target behavior is different:

- The chat should treat job traces as one evidence source, not the only source.
- The database should remember each synced repository's file tree, file metadata, content chunks, symbols, and embeddings.
- The agent should retrieve code context before answering engineering questions.
- The agent should make explicit tool calls for code search, file reads, patch drafting, branch creation, MR creation, and approval-gated execution.
- The answer should be useful even when logs are missing: explain likely causes, cite files inspected, propose next checks, and generate safe code changes when requested.

## Current Implementation Status

- Repository file inventory, safe content storage, chunking, symbol extraction, and redaction are implemented.
- Agent tools can list trees, read files/ranges, search/grep code, retrieve symbols, build context packs, and draft approval-gated patches.
- Repository chunks now support production embedding metadata: provider, model, status, and error.
- Production mode requires Vertex embeddings with `gemini-embedding-001` and Cloud SQL PostgreSQL pgvector enabled.
- Local development still works with deterministic local embeddings, but production startup validation rejects that mode.
- `python -m app.scripts.check_repo_embeddings` reports embedding health.
- `python -m app.scripts.check_repo_embeddings --repair-pgvector` creates/verifies the Cloud SQL `vector` extension, vector column, and HNSW cosine index.

## Research Basis

- GitLab exposes repository tree listing through `GET /projects/:id/repository/tree`, including recursive traversal of files and directories. This is the right source for building the project file map.
  Source: https://docs.gitlab.com/api/repositories/
- GitLab exposes file metadata/content through `GET /projects/:id/repository/files/:file_path`, raw file contents through `/raw`, blame history, create file, update file, and delete file endpoints. These are enough for read and write tools.
  Source: https://docs.gitlab.com/api/repository_files/
- Google Agent Platform is designed for enterprise-grade agents grounded in enterprise data and supports building, governing, and optimizing production agents.
  Source: https://cloud.google.com/products/gemini-enterprise-agent-platform
- Gemini embeddings support semantic retrieval over text/code. `gemini-embedding-001` supports English, multilingual, and code tasks; Google recommends adding embeddings to a vector database for low-latency retrieval at scale.
  Source: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/embeddings/get-text-embeddings
- Google Cloud SQL for PostgreSQL documentation now explicitly includes vector search, using Cloud SQL with agents, Cloud SQL remote MCP servers, and securing agent interactions with MCP.
  Source: https://docs.cloud.google.com/sql/docs/postgres/extensions
- MCP tool guidance requires visible tool exposure, visible tool invocation indicators, and human confirmation for tool invocations. This matches our approval-gated action model.
  Source: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

## Target Architecture

Panopticon should become a repository-aware operations agent with four context layers:

1. **Operational context**
   - Pipelines
   - Failed jobs and traces
   - Merge requests
   - Incidents
   - Recommendations
   - Actions

2. **Repository context**
   - Full file tree
   - File metadata
   - File excerpts
   - Full content for safe text/code files
   - Code chunks
   - Symbols and imports
   - Config/deployment/test/security file classifications

3. **Long-term memory**
   - User preferences
   - Approved/rejected fixes
   - Prior root causes
   - Previously useful files
   - Repeated failure signatures
   - Project-specific architectural notes

4. **Agent tools**
   - Search code
   - Read file
   - List tree
   - Retrieve related files
   - Inspect MR/pipeline/job
   - Draft patch
   - Validate patch
   - Create branch
   - Commit changes
   - Open merge request

## Phase 1: Repository Database Memory

Add or extend tables:

### `repo_file_index`

Already exists, but it should become the canonical file inventory.

Required fields:

- `workspace_id`
- `project_id`
- `project_path`
- `ref`
- `file_path`
- `file_type`
- `language`
- `size_bytes`
- `content_sha`
- `last_commit_id`
- `content_excerpt`
- `signals`
- `indexed_at`

### `repo_file_content`

Stores full text content only for safe eligible files.

Fields:

- `workspace_id`
- `project_id`
- `project_path`
- `ref`
- `file_path`
- `content_sha`
- `content`
- `content_redacted`
- `redaction_flags`
- `line_count`
- `indexed_at`

Rules:

- Store source/config/test files under a size threshold.
- Skip binaries, media, vendored folders, node_modules, build outputs, lockfiles above threshold.
- Redact secrets before storage.
- Store only metadata for very large files.

### `repo_code_chunks`

Stores retrieval units.

Fields:

- `workspace_id`
- `project_id`
- `file_path`
- `chunk_id`
- `start_line`
- `end_line`
- `chunk_type`
- `symbol_name`
- `language`
- `content`
- `content_sha`
- `embedding`
- `indexed_at`

Chunking strategy:

- Python/JS/TS: function/class chunks where possible.
- YAML/JSON/TOML: logical object sections.
- Docker/Kubernetes/Terraform: resource-level chunks.
- Markdown: heading sections.
- Fallback: sliding line windows.

### `repo_symbol_index`

Stores structure for targeted code reasoning.

Fields:

- `workspace_id`
- `project_id`
- `file_path`
- `symbol_name`
- `symbol_type`
- `start_line`
- `end_line`
- `imports`
- `exports`
- `calls`
- `defined_by_chunk_id`

### `agent_memory_records`

Upgrade current memory into typed memory.

Memory types:

- `project_architecture`
- `root_cause_pattern`
- `approved_fix`
- `rejected_fix`
- `user_preference`
- `important_file`
- `test_strategy`
- `deployment_pattern`

## Phase 2: Repository Indexing Pipeline

Create a proper indexer:

1. Pull project tree from GitLab.
2. Filter eligible files.
3. Fetch metadata and raw content.
4. Redact secrets.
5. Classify file purpose.
6. Chunk content.
7. Extract symbols/imports.
8. Generate embeddings.
9. Store/update only changed files by content SHA.
10. Delete stale index rows for removed files.

Indexing triggers:

- After GitLab project sync.
- On manual `Refresh repo context`.
- On webhook push event.
- Before chat answer if project context is stale.

Freshness contract:

- If code index is stale, the chat says it is refreshing or asks to refresh.
- It should not answer from old repository context without saying so.

## Phase 3: MCP Tool Layer

Add MCP-compatible tools:

### Read/retrieval tools

- `list_project_tree(project_id, ref, path?)`
- `search_code(project_id, query, filters?)`
- `grep_code(project_id, pattern, filters?)`
- `read_file(project_id, file_path, ref?)`
- `read_file_range(project_id, file_path, start_line, end_line)`
- `get_symbols(project_id, file_path?)`
- `find_related_files(project_id, file_path | symbol | issue)`
- `get_pipeline_context(project_id, pipeline_id?)`
- `get_mr_context(project_id, mr_iid?)`

### Reasoning tools

- `rank_suspect_files(question, evidence)`
- `build_context_pack(question, project_id)`
- `explain_code_path(project_id, entrypoint_or_file)`
- `summarize_repository(project_id)`

### Write tools

All write tools must be approval-gated:

- `draft_patch(project_id, problem, target_files?)`
- `validate_patch(project_id, patch)`
- `create_fix_plan(project_id, problem)`
- `create_branch(project_id, branch_name)`
- `commit_file_changes(project_id, branch, changes)`
- `open_merge_request(project_id, branch, title, description)`

No direct default-branch writes.

## Phase 4: Chat Reasoning Pipeline

Replace deterministic chat handling with an agent loop:

1. Classify intent:
   - explain
   - debug
   - compare
   - summarize
   - code search
   - patch request
   - action approval
   - setup/help

2. Choose context sources:
   - repo index
   - file contents
   - pipeline/job traces
   - MR diffs
   - incidents
   - memory

3. Make tool calls.

4. Build an evidence pack.

5. Answer with the format the user asked for:
   - paragraph
   - table
   - checklist
   - diff
   - step-by-step
   - short answer

6. If traces are missing:
   - do not stop
   - inspect repository and metadata
   - state that traces are unavailable only as a limitation
   - provide likely cause and next verification steps

Example expected response:

> I could not inspect failed job trace logs for this pipeline, but I inspected `deploy/kubernetes/deployment.yaml`, `.gitlab-ci.yml`, and `services/checkout/auth.py`. The most likely cause is a deployment/auth configuration mismatch because...

## Phase 5: Code Change Workflow

When user asks for a fix:

1. Retrieve likely files.
2. Read exact file ranges.
3. Draft patch.
4. Validate:
   - no secrets
   - no default branch write
   - no destructive changes without explicit approval
   - tests identified
   - rollback noted
5. Show:
   - changed files
   - diff preview
   - reasoning
   - tests to run
   - risk level
6. Ask for approval.
7. Create branch.
8. Commit changes.
9. Open MR.
10. Store memory about accepted/rejected fix.

## Phase 6: Database And Vector Storage

Use PostgreSQL as the source of truth.

Recommended local/prod storage:

- Cloud SQL PostgreSQL for relational state.
- Cloud SQL vector capabilities or Vertex AI Vector Search for semantic retrieval.
- Store file chunks and metadata in PostgreSQL even if embeddings are external.
- Use `content_sha` as the deduplication key.

For the first implementation:

- Add embedding fields as nullable.
- Support lexical search first.
- Add Gemini embeddings next.
- Add vector reranking after lexical retrieval works.

## Phase 7: Google Agent Platform Integration

Use Google Agent Platform for:

- Gemini model runtime.
- Embeddings generation.
- Optional Vector Search.
- Agent governance/deployment story.
- Future Agent Builder/ADK alignment.

Panopticon remains the source of operational truth, while Google Agent Platform provides the model, retrieval, and agent runtime capabilities.

## Phase 8: Testing And Evaluation

Create a large evaluation suite with categories:

### Repository explanation

- "Explain this project."
- "What does checkout service do?"
- "Where is payment auth handled?"
- "Make a table of important files."
- "Which files control deployment?"

### Debugging without traces

- Pipeline failed but no trace available.
- Job timed out.
- Deploy failed.
- Tests failed.
- No pipeline context, but repo context exists.

Expected behavior:

- Never stop at "no job trace".
- Use repo/MR/pipeline context.

### Code search

- "Find auth code."
- "Where is rollback configured?"
- "Show files related to payment gateway."
- "Which tests cover checkout?"

### Patch generation

- "Fix missing timeout."
- "Add a test."
- "Make deployment safer."
- "Create an MR for this fix."

### Safety

- Prompt injection in repo file.
- Secret-like content.
- Direct default-branch write request.
- Destructive delete request.
- Ambiguous project request.

Metrics:

- File recall@5.
- Answer groundedness.
- Tool-call validity.
- Patch safety pass rate.
- No-trace answer success rate.
- Human approval compliance.
- Latency p95.

## Phase 9: UI Changes

Chat should visibly show:

- Tool calls being made.
- Files retrieved.
- Code snippets used.
- Whether repository index is fresh.
- Suggested follow-up actions.
- Draft patch preview.
- Approval buttons.

Project pages should show:

- Repo context status.
- File count.
- Indexed chunks.
- Last indexed commit.
- Stale/fresh indicator.
- Manual refresh button.

## Phase 10: Implementation Order

1. Add repository content/chunk/schema migrations.
2. Extend GitLab client for tree/raw file/blame/write endpoints.
3. Build repo indexer.
4. Add code retrieval MCP tools.
5. Route chatbot through tool-based context builder.
6. Add no-trace fallback behavior.
7. Add patch drafting tools.
8. Add approval-gated write tools.
9. Add UI tool-call timeline.
10. Build large chat eval suite.
11. Add embeddings/vector retrieval.
12. Integrate with Google Agent Platform more formally.

## Acceptance Criteria

The phase is complete only when:

- A synced project has a stored file tree and indexed file chunks.
- Chat can answer project/file/code questions without job traces.
- Chat makes visible tool calls.
- Chat can retrieve and quote exact files/ranges.
- Chat can draft a patch from repository context.
- Write operations require approval.
- The chatbot eval suite includes no-trace cases and passes them.
- The answer quality is judged against groundedness, not just whether it mentions pipeline logs.
