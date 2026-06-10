import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.agents.gemini import GeminiReasoner
from app.services.agent_memory import AgentMemoryService
from app.services.agent_tools import AgentToolService
from app.services.chat_validation import ChatValidationService
from app.services.fix_plans import FixPlanService
from app.services.grounded_recommendations import GroundedRecommendationEngine
from app.services.repo_context import RepoContextService


class ChatService:
    def __init__(self, db: Session, workspace_id: int | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.reasoner = GeminiReasoner()
        self.tools = AgentToolService(db, workspace_id=workspace_id)

    def answer(self, *, message: str, project_id: int | None = None, thread_id: int | None = None) -> dict:
        project = self._project(project_id) or self.tools.infer_project(message)
        thread = self._thread(message=message, project=project, thread_id=thread_id)
        user_message = self._add_message(thread, role="user", content=message)

        intent = _classify_intent(message)
        memory_service = AgentMemoryService(self.db, workspace_id=self.workspace_id)
        captured_memory = memory_service.capture_user_memory(message=message, project=project)
        context = self._context(project, message)
        context["memory"] = memory_service.retrieve(project=project, question=message, current_memory=context.get("memory", []))
        context["grounded_recommendation"] = GroundedRecommendationEngine(self.db, workspace_id=self.workspace_id).recommend(
            project=project,
            question=message,
            intent=intent,
            context=context,
            use_live_reasoner=False,
        )
        prepared_actions = self._prepare_actions_if_requested(message, project)
        prepared_fix_plans = self._prepare_fix_plans_if_requested(message, project, context)
        for plan in prepared_fix_plans:
            memory_service.remember_prepared_fix_plan(plan)
        if prepared_fix_plans:
            context["memory"] = memory_service.retrieve(project=project, question=message, current_memory=context.get("memory", []))
        citations = self._citations(intent, context, prepared_actions)
        deterministic_answer = self._compose_answer(intent, message, project, context, prepared_actions)
        deterministic_answer = self._append_prepared_fix_plan_text(deterministic_answer, prepared_fix_plans)
        answer = self._llm_answer(
            question=message,
            intent=intent,
            project=project,
            context=context,
            citations=citations,
            prepared_actions=prepared_actions,
            deterministic_answer=deterministic_answer,
        )
        validation = ChatValidationService().validate(
            answer=answer,
            deterministic_answer=deterministic_answer,
            intent=intent,
            context=context,
            citations=citations,
            prepared_actions=prepared_actions,
            prepared_fix_plans=prepared_fix_plans,
        )
        answer = _redact_secret_text(validation.answer)
        if captured_memory:
            answer = f"{answer}\n\nSaved memory: {captured_memory[0].summary}"
        memory_service.remember_answer_pattern(
            project_path=project.project_path if project else "",
            intent=intent,
            answer=answer,
            evidence_labels=[f"{citation.get('type')}:{citation.get('label')}" for citation in citations],
        )
        assistant_message = self._add_message(
            thread,
            role="assistant",
            content=answer,
            citations=citations,
            prepared_action_ids=[action.id for action in prepared_actions],
        )
        thread.updated_at = _now()
        self.db.commit()

        return {
            "thread": thread,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "prepared_actions": prepared_actions,
            "prepared_fix_plans": prepared_fix_plans,
        }

    def _project(self, project_id: int | None) -> models.GitLabProject | None:
        if project_id is None:
            return None
        project = self.db.get(models.GitLabProject, project_id)
        if project and self.workspace_id is not None and project.workspace_id != self.workspace_id:
            return None
        return project

    def _thread(self, *, message: str, project: models.GitLabProject | None, thread_id: int | None) -> models.ChatThread:
        if thread_id:
            existing = self.db.get(models.ChatThread, thread_id)
            if existing:
                if self.workspace_id is not None and existing.workspace_id != self.workspace_id:
                    existing = None
                elif project and existing.project_id != project.id:
                    existing = None
                elif project is None and existing.project_id is not None:
                    existing = None
            if existing:
                return existing
        title = message.strip().replace("\n", " ")[:80] or "Panopticon chat"
        thread = models.ChatThread(
            project_id=project.id if project else None,
            workspace_id=self.workspace_id,
            project_path=project.project_path if project else "",
            title=title,
        )
        self.db.add(thread)
        self.db.flush()
        return thread

    def _add_message(
        self,
        thread: models.ChatThread,
        *,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        prepared_action_ids: list[int] | None = None,
    ) -> models.ChatMessage:
        message = models.ChatMessage(
            thread_id=thread.id,
            workspace_id=thread.workspace_id or self.workspace_id,
            role=role,
            content=content,
            citations=citations or [],
            prepared_action_ids=prepared_action_ids or [],
        )
        self.db.add(message)
        self.db.flush()
        return message

    def _context(self, project: models.GitLabProject | None, question: str) -> dict:
        context = self.tools.chat_context(project)
        repo_pack = RepoContextService(self.db, workspace_id=self.workspace_id).context_pack(project, query=question, limit=8)
        if repo_pack["files"]:
            context["repo_files"] = repo_pack["files"]
        if repo_pack["chunks"]:
            context["repo_chunks"] = repo_pack["chunks"]
        if repo_pack["symbols"]:
            context["repo_symbols"] = repo_pack["symbols"]
        context["repo_context_notes"] = repo_pack["notes"]
        return context

    def _prepare_actions_if_requested(self, message: str, project: models.GitLabProject | None) -> list[models.AgentAction]:
        lowered = message.lower()
        action_requested = any(
            phrase in lowered
            for phrase in [
                "prepare",
                "propose",
                "create action",
                "draft action",
                "make action",
                "approve",
                "execute",
                "send",
                "make the action",
                "action live",
                "live without approval",
                "without approval",
                "slack alert",
                "gitlab comment",
            ]
        )
        if not action_requested:
            return []

        return self.tools.prepare_action_records(project=project, limit=10)

    def _prepare_fix_plans_if_requested(self, message: str, project: models.GitLabProject | None, context: dict) -> list[models.FixPlan]:
        lowered = message.lower()
        wants_fix = any(
            phrase in lowered
            for phrase in [
                "fix plan",
                "safe fix",
                "prepare fix",
                "create fix",
                "code change",
                "make change",
                "generate patch",
                "patch",
                "create branch",
                "open mr",
                "mr plan",
                "branch plan",
                "merge request fix",
            ]
        )
        wants_fix = wants_fix or ("fix" in lowered and any(term in lowered for term in ["plan", "patch", "branch", "mr", "merge request", "code"]))
        if not wants_fix or not project:
            return []

        source_type, source_id = _best_fix_source(context)
        plan = FixPlanService(self.db, workspace_id=self.workspace_id).create(
            project_id=project.id,
            source_type=source_type,
            source_id=source_id,
            problem_statement=message,
            fix_type=_requested_fix_type(message),
        )
        return [plan]

    def _append_prepared_fix_plan_text(self, answer: str, prepared_fix_plans: list[models.FixPlan]) -> str:
        if not prepared_fix_plans:
            return answer
        lines = [answer, ""]
        for plan in prepared_fix_plans:
            diff_count = len((plan.plan_payload or {}).get("diff_preview") or [])
            commands = (plan.plan_payload or {}).get("test_plan", {}).get("commands", [])
            lines.append(
                f"Prepared safe fix plan #{plan.id}: {plan.title}. It targets branch {plan.branch_name}, includes {diff_count} diff preview(s), and requires approval before any GitLab write."
            )
            if commands:
                lines.append(f"Validation to run before merge: {commands[0]}.")
        return "\n".join(lines)

    def _compose_answer(self, intent: str, question: str, project: models.GitLabProject | None, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        subject = project.project_path if project else "all synced projects"
        response_format = _response_format(question)
        if _is_product_usage_question(question):
            return _product_usage_answer()
        if _asks_for_secret(question):
            return (
                f"For {subject}, I cannot reveal secrets, credentials, tokens, or raw secret-like job log values. "
                "I can still summarize the failure using redacted evidence and approval-gated next steps."
            )
        if response_format == "table":
            return _table_answer(subject=subject, intent=intent, context=context, prepared_actions=prepared_actions)
        if response_format == "checklist":
            return _checklist_answer(subject=subject, intent=intent, context=context, prepared_actions=prepared_actions)
        if response_format == "concise":
            return _concise_answer(subject=subject, intent=intent, context=context, prepared_actions=prepared_actions)
        if intent == "pipeline_failure":
            return self._pipeline_answer(subject, context, prepared_actions)
        if intent == "priority":
            return self._priority_answer(subject, context, prepared_actions)
        if intent == "risk":
            return self._risk_answer(subject, context, prepared_actions)
        if intent == "merge_request":
            return self._merge_request_answer(subject, context, prepared_actions)
        if intent == "incident":
            return self._incident_answer(subject, context, prepared_actions)
        if intent == "actions":
            return self._actions_answer(subject, context, prepared_actions)
        if intent == "memory":
            return self._memory_answer(subject, context, prepared_actions)

        parts = [f"For {subject}, here is the current operational summary from Panopticon records:"]

        risks = context["risks"]
        pipelines = context["pipelines"]
        failed_jobs = context["failed_jobs"]
        merge_requests = context["merge_requests"]
        incidents = context["incidents"]
        recommendations = context["recommendations"]
        actions = context["actions"]
        memory = context["memory"]

        if risks:
            top = risks[0]
            parts.append(f"- Highest recent risk: {top.summary} Score {top.score}/100, level {top.level}.")
        else:
            parts.append("- No risk assessments are currently stored for this scope.")

        if pipelines:
            failed_count = len([pipeline for pipeline in pipelines if pipeline.status == "failed"])
            latest = pipelines[0]
            parts.append(f"- Pipeline state: latest synced pipeline #{latest.pipeline_id} is {latest.status}; {failed_count} of the recent synced pipelines are failed.")
        else:
            parts.append("- No pipeline snapshots are currently stored for this scope.")

        if failed_jobs:
            job = failed_jobs[0]
            parts.append(f"- Most recent failed job: {job.name} in stage {job.stage}, reason {job.failure_reason or job.status}.")
            if job.trace_summary:
                parts.append(f"- Job trace classification: {job.trace_summary}")

        if merge_requests:
            mr = merge_requests[0]
            parts.append(f"- Open MR context: !{mr.merge_request_iid} {mr.title} from {mr.source_branch} to {mr.target_branch}.")

        if incidents:
            incident = incidents[0]
            parts.append(f"- Incident context: {incident.title}; likely cause: {incident.probable_root_cause}")

        if recommendations:
            rec = recommendations[0]
            parts.append(f"- Latest recommendation: {rec.source_type} via {rec.channel}, currently {rec.status}.")

        if actions:
            pending = len([action for action in actions if action.status == "pending_approval"])
            parts.append(f"- Action status: {pending} recent action(s) are pending approval.")

        if memory:
            record = memory[0]
            parts.append(f"- Operational memory: {record.summary}")

        if prepared_actions:
            ids = ", ".join(str(action.id) for action in prepared_actions)
            parts.append(f"- I prepared action proposal(s) {ids}. They still require approval in the Actions page before execution.")

        self._append_grounded(parts, context)

        if "why" in question.lower() or "what should" in question.lower():
            parts.append("Recommended next step: inspect the cited risk, pipeline, and recommendation records first; then approve only the proposed action whose payload matches what you want sent.")

        return "\n".join(parts)

    def _pipeline_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        pipelines = context["pipelines"]
        insights = [item for item in context["pipeline_insights"] if item.status == "failed"]
        failed_jobs = context["failed_jobs"]
        repo_files = context.get("repo_files", [])
        repo_chunks = context.get("repo_chunks", [])
        repo_symbols = context.get("repo_symbols", [])
        parts = [f"Pipeline analysis for {subject}:"]
        if not insights and not failed_jobs and not any(pipeline.status == "failed" for pipeline in pipelines):
            if pipelines:
                latest = pipelines[0]
                parts.append(f"- Latest synced pipeline #{latest.pipeline_id} is {latest.status} on ref {latest.ref or 'unknown'}.")
            if repo_files or repo_chunks or repo_symbols:
                self._append_repo_context(parts, context)
                parts.append("- I do not need to stop at job traces here: the next answerable step is to inspect the indexed CI/deploy/source files above and compare them with the failed branch or MR.")
                parts.append("- Next action: refresh pipeline jobs if you need exact log proof, but use repository context now to identify likely affected files and prepare an approval-gated fix plan.")
            else:
                parts.append("- Cannot determine a failed job or root cause because no failed pipeline, failed job trace, pipeline insight, or repository context is stored for this scope.")
                parts.append("- Next action: sync GitLab and refresh repository context before naming a root cause or preparing a live action.")
            self._append_prepared(parts, prepared_actions)
            return "\n".join(parts)
        if insights:
            insight = insights[0]
            parts.append(f"- Likely cause: {_redact_secret_text(insight.likely_cause)}")
            if failed_jobs:
                job = failed_jobs[0]
                parts.append(f"- Failed job: {job.name} in stage {job.stage}, pipeline #{job.pipeline_id}.")
            if insight.evidence:
                parts.append(f"- Evidence: {'; '.join(_redact_secret_text(item) for item in insight.evidence[:3])}")
            if insight.recommendations:
                parts.append(f"- Next action: {_redact_secret_text(insight.recommendations[0])}")
        elif failed_jobs:
            job = failed_jobs[0]
            parts.append(f"- The most recent failed job is {job.name} in stage {job.stage}. GitLab reported {job.failure_reason or job.status}.")
            if job.trace_summary:
                parts.append(f"- Classified job trace: {job.trace_summary}")
                parts.append(f"- Failure signature: {job.failure_signature or 'unknown_failure'}.")
            else:
                parts.append("- Next action: open the failed job log and inspect the first failing command or timeout boundary.")
        elif pipelines:
            latest = pipelines[0]
            failed_count = len([pipeline for pipeline in pipelines if pipeline.status == "failed"])
            parts.append(f"- Latest synced pipeline #{latest.pipeline_id} is {latest.status} on ref {latest.ref or 'unknown'}.")
            parts.append(f"- Recent failed pipeline count in the synced window: {failed_count}.")
            if repo_files or repo_chunks or repo_symbols:
                self._append_repo_context(parts, context)
                parts.append("- No parsed failed job trace is stored yet, so this is repository-grounded triage rather than a final log-proven root cause.")
            else:
                parts.append("- No parsed failed job or pipeline insight is stored yet, so Panopticon cannot name an exact root cause from logs.")
        else:
            parts.append("- No pipeline snapshots, failed jobs, or pipeline insights are stored for this scope.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _append_repo_context(self, parts: list[str], context: dict) -> None:
        files = context.get("repo_files", [])[:4]
        chunks = context.get("repo_chunks", [])[:3]
        symbols = context.get("repo_symbols", [])[:4]
        if files:
            file_list = ", ".join(item.file_path for item in files)
            parts.append(f"- Repository context to inspect: {file_list}.")
        if chunks:
            chunk = chunks[0]
            excerpt = " ".join(chunk.content.split())[:220]
            parts.append(f"- Matching code memory: {chunk.file_path}:{chunk.start_line}-{chunk.end_line} contains `{excerpt}`.")
        if symbols:
            symbol_list = ", ".join(f"{item.symbol_name} ({item.file_path}:{item.start_line})" for item in symbols)
            parts.append(f"- Relevant symbols/config keys: {symbol_list}.")
        notes = context.get("repo_context_notes") or []
        if notes:
            parts.append(f"- Repository memory note: {notes[0]}")

    def _priority_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        risks = sorted(context["risks"], key=lambda risk: risk.score, reverse=True)
        failures = [item for item in context["pipeline_insights"] if item.status == "failed"]
        incidents = [item for item in context["incidents"] if item.status == "open"]
        actions = [item for item in context["actions"] if item.status == "pending_approval"]
        parts = [f"Priority triage for {subject}:"]
        if risks:
            top = risks[0]
            parts.append(f"- First risk: {top.project_path} at {top.score}/100 {top.level}. {top.summary}")
        if failures:
            failure = failures[0]
            parts.append(f"- First pipeline failure: {failure.project_path} pipeline #{failure.pipeline_id}. Likely cause: {failure.likely_cause}")
        if incidents:
            incident = incidents[0]
            parts.append(f"- Open incident: {incident.project_path} {incident.title}. Root cause: {incident.probable_root_cause}")
        if actions:
            action = actions[0]
            parts.append(f"- Pending approval: action #{action.id} {action.title} for {action.project_path}.")
        if not any([risks, failures, incidents, actions]):
            parts.append("- No active risks, failures, incidents, or pending approvals are stored for this scope.")
        else:
            parts.append("- Recommended order: handle critical risks and failed production-facing pipelines first, then approve or reject prepared actions.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _risk_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        risks = context["risks"]
        recommendations = context["recommendations"]
        parts = [f"Risk analysis for {subject}:"]
        if risks:
            risk = risks[0]
            parts.append(f"- Current top risk: {risk.summary} Score {risk.score}/100, level {risk.level}.")
            if risk.reasons:
                parts.append(f"- Evidence: {'; '.join(risk.reasons[:3])}")
            if risk.recommendations:
                parts.append(f"- Next action: {risk.recommendations[0]}")
        else:
            parts.append("- No risk assessments are stored for this scope.")
        if recommendations:
            rec = recommendations[0]
            parts.append(f"- Related recommendation: {rec.source_type} through {rec.channel}, status {rec.status}.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _merge_request_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        merge_requests = context["merge_requests"]
        parts = [f"Merge request context for {subject}:"]
        if not merge_requests:
            parts.append("- No synced merge requests are stored for this scope.")
        for mr in merge_requests[:3]:
            draft = "draft" if mr.draft else mr.state
            parts.append(f"- !{mr.merge_request_iid} {mr.title}: {draft}, {mr.source_branch} -> {mr.target_branch}, author {mr.author_username or 'unknown'}.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _incident_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        incidents = context["incidents"]
        memory = context["memory"]
        parts = [f"Incident context for {subject}:"]
        if incidents:
            incident = incidents[0]
            parts.append(f"- Latest incident: {incident.title}, severity {incident.severity}.")
            parts.append(f"- Probable root cause: {incident.probable_root_cause}")
            if incident.recommendations:
                parts.append(f"- Next action: {incident.recommendations[0]}")
        else:
            parts.append("- No incidents are stored for this scope.")
        if memory:
            parts.append(f"- Related memory: {memory[0].summary}")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _actions_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        actions = context["actions"]
        parts = [f"Action status for {subject}:"]
        if actions:
            counts = {status: len([action for action in actions if action.status == status]) for status in sorted({action.status for action in actions})}
            parts.append(f"- Recent action statuses: {counts}")
            first = actions[0]
            parts.append(f"- Latest action: #{first.id} {first.title}, {first.status}, channel {first.channel}.")
        else:
            parts.append("- No proposed or executed actions are stored for this scope.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _memory_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        memory = context["memory"]
        parts = [f"Operational memory for {subject}:"]
        if not memory:
            parts.append("- No memory records are stored for this scope.")
        for record in memory[:3]:
            parts.append(f"- {record.memory_type}: {record.summary}")
            if record.remediation:
                parts.append(f"  Next remediation: {record.remediation[0]}")
        if memory:
            parts.append("- Owner review is still required before approving Slack, GitLab, or code-change actions based on this memory.")
        self._append_grounded(parts, context)
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _append_prepared(self, parts: list[str], prepared_actions: list[models.AgentAction]) -> None:
        if prepared_actions:
            ids = ", ".join(str(action.id) for action in prepared_actions)
            parts.append(f"- Prepared action proposal(s): {ids}. They require approval in the Actions page before execution.")

    def _append_grounded(self, parts: list[str], context: dict) -> None:
        bundle = context.get("grounded_recommendation") or {}
        if not bundle:
            return
        confidence = int(float(bundle.get("confidence") or 0) * 100)
        recommendation = str(bundle.get("recommendation") or "").strip()
        next_actions = bundle.get("next_actions") or []
        parts.append(f"- Grounded recommendation ({confidence}% confidence): {_redact_secret_text(recommendation)}")
        if next_actions:
            parts.append(f"- Grounded next step: {_redact_secret_text(next_actions[0])}")

    def _citations(self, intent: str, context: dict, prepared_actions: list[models.AgentAction]) -> list[dict]:
        intent_sources = {
            "pipeline_failure": ["pipeline_insights", "failed_jobs", "pipelines", "repo_files", "repo_chunks", "repo_symbols"],
            "priority": ["risks", "pipeline_insights", "failed_jobs", "incidents", "actions", "repo_files", "repo_chunks", "repo_symbols"],
            "risk": ["risks", "recommendations", "repo_files", "repo_chunks", "repo_symbols"],
            "merge_request": ["merge_requests", "risks", "repo_files", "repo_chunks", "repo_symbols"],
            "incident": ["incidents", "memory", "recommendations"],
            "actions": ["actions", "recommendations"],
            "memory": ["memory", "incidents", "repo_files", "repo_chunks"],
            "summary": ["risks", "pipeline_insights", "pipelines", "merge_requests", "incidents", "recommendations", "actions", "memory", "repo_files", "repo_chunks", "repo_symbols"],
        }
        citations: list[dict] = []
        for key in intent_sources.get(intent, intent_sources["summary"]):
            records = context.get(key, [])
            if not records:
                continue
            for record in records[:3]:
                citations.append(_citation(key, record))
        for action in prepared_actions:
            citations.append({"type": "prepared_action", "id": action.id, "label": action.title, "summary": action.summary})
        return citations[:12]

    def _llm_answer(
        self,
        *,
        question: str,
        intent: str,
        project: models.GitLabProject | None,
        context: dict,
        citations: list[dict],
        prepared_actions: list[models.AgentAction],
        deterministic_answer: str,
    ) -> str:
        subject = project.project_path if project else "all synced projects"
        return self.reasoner.chat_answer(
            question=question,
            intent=intent,
            subject=subject,
            evidence=_llm_evidence(intent, context, citations, prepared_actions),
            deterministic_draft=deterministic_answer,
        )


def _citation(kind: str, record) -> dict:
    if isinstance(record, models.PipelineSnapshot):
        label = f"Pipeline #{record.pipeline_id}"
        summary = f"{record.status} on {record.ref or 'unknown ref'}"
    elif isinstance(record, models.PipelineInsight):
        label = f"Pipeline insight #{record.pipeline_id}"
        summary = record.likely_cause
    elif isinstance(record, models.JobSnapshot):
        label = f"Job {record.name}"
        summary = record.trace_summary or f"{record.status}; {record.failure_reason or 'no failure reason'}"
    elif isinstance(record, models.MergeRequestSnapshot):
        label = f"MR !{record.merge_request_iid}: {record.title}"
        summary = f"{record.source_branch} -> {record.target_branch}; {record.state}"
    elif isinstance(record, models.RiskAssessment):
        label = f"Risk {record.score}/100 {record.level}"
        summary = record.summary
    elif isinstance(record, models.Recommendation):
        label = f"{record.source_type} recommendation via {record.channel}"
        summary = record.status
    elif isinstance(record, models.AgentAction):
        label = f"Action #{record.id}: {record.title}"
        summary = record.status
    elif isinstance(record, models.RepoFileIndex):
        label = f"{record.file_type} file: {record.file_path}"
        flags = ", ".join((record.signals or {}).get("risk_flags") or [])
        summary = flags or record.language or record.ref
    elif isinstance(record, models.RepoCodeChunk):
        label = f"Code chunk: {record.file_path}:{record.start_line}-{record.end_line}"
        summary = ", ".join((record.keywords or [])[:8]) or record.content[:160]
    elif isinstance(record, models.RepoSymbolIndex):
        label = f"{record.symbol_type}: {record.symbol_name}"
        summary = f"{record.file_path}:{record.start_line} {record.signature}"
    else:
        label = getattr(record, "title", "") or getattr(record, "name", "") or getattr(record, "summary", "") or kind
        summary = getattr(record, "summary", "") or getattr(record, "likely_cause", "") or getattr(record, "probable_root_cause", "") or getattr(record, "status", "")
    return {
        "type": kind,
        "id": record.id,
        "label": _redact_secret_text(str(label))[:160],
        "summary": _redact_secret_text(str(summary))[:240],
    }


def _llm_evidence(intent: str, context: dict, citations: list[dict], prepared_actions: list[models.AgentAction]) -> list[dict]:
    selected_ids = {(citation["type"], citation["id"]) for citation in citations}
    evidence: list[dict] = []
    for kind, records in context.items():
        if kind in {"project", "repo_context_notes"}:
            continue
        if kind == "grounded_recommendation" and isinstance(records, dict):
            evidence.append(
                {
                    "type": "grounded_recommendation",
                    "issue_type": records.get("issue_type"),
                    "severity": records.get("severity"),
                    "confidence": records.get("confidence"),
                    "grounded": records.get("grounded"),
                    "recommendation": records.get("recommendation"),
                    "next_actions": records.get("next_actions", []),
                    "evidence": records.get("evidence", [])[:8],
                }
            )
            continue
        if not isinstance(records, list):
            continue
        for record in records[:3]:
            if not hasattr(record, "id"):
                continue
            if (kind, record.id) in selected_ids:
                evidence.append(_record_evidence(kind, record))
    for action in prepared_actions:
        evidence.append(_record_evidence("prepared_action", action))
    if evidence:
        return evidence[:12]
    return citations[:12]


def _record_evidence(kind: str, record) -> dict:
    base = _citation(kind, record)
    if isinstance(record, models.PipelineInsight):
        base.update(
            {
                "pipeline_id": record.pipeline_id,
                "status": record.status,
                "likely_cause": _redact_secret_text(record.likely_cause),
                "evidence": [_redact_secret_text(item) for item in record.evidence],
                "recommendations": [_redact_secret_text(item) for item in record.recommendations],
            }
        )
    elif isinstance(record, models.PipelineSnapshot):
        base.update(
            {
                "pipeline_id": record.pipeline_id,
                "status": record.status,
                "ref": record.ref,
                "sha": record.sha,
                "web_url": record.web_url,
            }
        )
    elif isinstance(record, models.JobSnapshot):
        base.update(
            {
                "pipeline_id": record.pipeline_id,
                "job_id": record.job_id,
                "name": record.name,
                "stage": record.stage,
                "status": record.status,
                "failure_reason": record.failure_reason,
                "failure_signature": record.failure_signature,
                "trace_summary": _redact_secret_text(record.trace_summary),
                "trace_excerpt": _redact_secret_text(record.trace_excerpt[:1200]) if record.trace_excerpt else "",
                "duration": record.duration,
                "web_url": record.web_url,
            }
        )
    elif isinstance(record, models.RiskAssessment):
        base.update(
            {
                "project_path": record.project_path,
                "merge_request_iid": record.merge_request_iid,
                "deployment_ref": record.deployment_ref,
                "score": record.score,
                "level": record.level,
                "reasons": record.reasons,
                "recommendations": record.recommendations,
            }
        )
    elif isinstance(record, models.MergeRequestSnapshot):
        base.update(
            {
                "merge_request_iid": record.merge_request_iid,
                "title": record.title,
                "state": record.state,
                "source_branch": record.source_branch,
                "target_branch": record.target_branch,
                "author_username": record.author_username,
                "draft": record.draft,
                "web_url": record.web_url,
            }
        )
    elif isinstance(record, models.IncidentRecord):
        base.update(
            {
                "project_path": record.project_path,
                "title": record.title,
                "severity": record.severity,
                "probable_root_cause": record.probable_root_cause,
                "timeline": record.timeline,
                "recommendations": record.recommendations,
                "status": record.status,
            }
        )
    elif isinstance(record, models.MemoryRecord):
        base.update(
            {
                "project_path": record.project_path,
                "memory_type": record.memory_type,
                "signature": record.signature,
                "summary": record.summary,
                "evidence": record.evidence,
                "remediation": record.remediation,
            }
        )
    elif isinstance(record, models.Recommendation):
        base.update(
            {
                "project_path": record.project_path,
                "source_type": record.source_type,
                "source_id": record.source_id,
                "channel": record.channel,
                "message": record.message,
                "status": record.status,
            }
        )
    elif isinstance(record, models.AgentAction):
        base.update(
            {
                "project_path": record.project_path,
                "action_type": record.action_type,
                "channel": record.channel,
                "title": record.title,
                "summary": record.summary,
                "status": record.status,
                "requires_approval": record.requires_approval,
                "payload_preview": record.payload_preview,
            }
        )
    elif isinstance(record, models.RepoFileIndex):
        base.update(
            {
                "project_path": record.project_path,
                "file_path": record.file_path,
                "ref": record.ref,
                "file_type": record.file_type,
                "language": record.language,
                "signals": record.signals,
                "content_excerpt": record.content_excerpt[:2500],
            }
        )
    elif isinstance(record, models.RepoCodeChunk):
        base.update(
            {
                "project_path": record.project_path,
                "file_path": record.file_path,
                "ref": record.ref,
                "chunk_index": record.chunk_index,
                "start_line": record.start_line,
                "end_line": record.end_line,
                "language": record.language,
                "keywords": record.keywords,
                "content": _redact_secret_text(record.content[:2500]),
                "embedding_model": record.embedding_model,
                "embedding_provider": record.embedding_provider,
                "embedding_status": record.embedding_status,
            }
        )
    elif isinstance(record, models.RepoSymbolIndex):
        base.update(
            {
                "project_path": record.project_path,
                "file_path": record.file_path,
                "ref": record.ref,
                "symbol_name": record.symbol_name,
                "symbol_type": record.symbol_type,
                "signature": _redact_secret_text(record.signature),
                "start_line": record.start_line,
                "end_line": record.end_line,
            }
        )
    return base


def _now():
    return datetime.now(timezone.utc)


def _classify_intent(message: str) -> str:
    text = message.lower()
    if _is_product_usage_question(message):
        return "summary"
    if _asks_for_secret(message):
        return "summary"

    has_action_word = _has_phrase(text, ["action", "actions", "approve", "approval", "execute", "prepare", "propose", "send", "slack alert", "gitlab comment"])
    has_memory_word = _has_phrase(text, ["memory", "remember", "history", "recurring", "previous", "happened before", "before"])
    has_incident_word = _has_phrase(text, ["incident", "incidents", "outage", "rollback"])
    has_fix_plan_word = _has_phrase(text, ["fix plan", "safe fix", "prepare fix", "create fix", "patch", "generate patch", "code change", "create branch", "mr plan", "branch plan"])
    has_merge_request_word = _has_phrase(text, ["merge request", "mr ", "review", "branch"])
    has_failure_word = _has_phrase(text, ["pipeline", "pipelines", "ci", "job", "jobs", "build", "test failed", "timeout", "fail", "failed", "failure", "failures", "broke", "broken", "went wrong", "what to do next"])
    has_risk_word = _has_phrase(text, ["risk", "risks", "risky", "danger", "safe", "unsafe", "deployment", "deploy", "release"])
    has_priority_word = _has_phrase(text, ["first", "worst", "highest", "top", "prioritize", "priority", "look at first", "start debugging"])

    if has_memory_word:
        return "memory"
    if has_fix_plan_word:
        return "pipeline_failure"
    if has_action_word:
        return "actions"
    if has_incident_word:
        return "incident"
    if has_priority_word and (has_risk_word or has_failure_word or "issue" in text or "problem" in text or "debugging" in text):
        return "priority"
    if has_failure_word:
        return "pipeline_failure"
    if has_risk_word:
        return "risk"
    if has_merge_request_word:
        return "merge_request"
    return "summary"


def _has_phrase(text: str, phrases: list[str]) -> bool:
    for phrase in phrases:
        if " " in phrase:
            if phrase in text:
                return True
            continue
        if re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", text):
            return True
    return False


def _asks_for_secret(message: str) -> bool:
    text = message.lower()
    return _has_phrase(
        text,
        [
            "secret",
            "secrets",
            "credential",
            "credentials",
            "token",
            "tokens",
            "api key",
            "api keys",
            "client_secret",
            "password",
            "private key",
        ],
    ) and any(term in text for term in ["print", "reveal", "show", "extract", "tell me", "raw"])


def _is_product_usage_question(message: str) -> bool:
    text = message.lower().strip()
    return any(
        phrase in text
        for phrase in [
            "how should i use panopticon",
            "what can i ask",
            "what does panopticon know",
            "how do i review actions safely",
            "how does this app help",
            "how do i use",
        ]
    )


def _product_usage_answer() -> str:
    return (
        "Panopticon helps you connect GitLab projects, sync pipelines and merge requests, inspect risks, ask the agent grounded questions, "
        "prepare approval-gated Slack or GitLab actions, and review safe fix plans before anything writes back. "
        "Start by checking synced projects, then ask about a specific failed pipeline, risky merge request, incident, or action you want to review."
    )


def _response_format(message: str) -> str:
    text = message.lower()
    if any(term in text for term in ["table", "tabular", "matrix", "columns", "compare in columns", "make a table"]):
        return "table"
    if any(term in text for term in ["checklist", "todo", "to-do", "step by step", "steps", "what should i do next"]):
        return "checklist"
    if any(term in text for term in ["tl;dr", "tldr", "brief", "short answer", "summarize briefly", "concise"]):
        return "concise"
    return "default"


def _table_answer(*, subject: str, intent: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
    rows: list[list[str]] = []
    for insight in context.get("pipeline_insights", [])[:3]:
        if insight.status != "failed" and intent == "pipeline_failure":
            continue
        rows.append(
            [
                "Pipeline",
                f"#{insight.pipeline_id} {insight.status}",
                _redact_secret_text(insight.likely_cause),
                _safe_join(insight.evidence[:2]),
                _safe_join(insight.recommendations[:1]) or "Inspect the failed job log.",
                "Approval required before Slack/GitLab action.",
            ]
        )
    for job in context.get("failed_jobs", [])[:3]:
        rows.append(
            [
                "Failed job",
                f"{job.name} / {job.stage}",
                _redact_secret_text(job.trace_summary or job.failure_signature or job.failure_reason or job.status),
                f"Pipeline #{job.pipeline_id}; job #{job.job_id}",
                "Open the job trace and verify the first failing command.",
                "No live write from chat.",
            ]
        )
    for risk in context.get("risks", [])[:3]:
        rows.append(
            [
                "Risk",
                f"{risk.score}/100 {risk.level}",
                _redact_secret_text(risk.summary),
                _safe_join(risk.reasons[:2]),
                _safe_join(risk.recommendations[:1]) or "Require owner review.",
                "Approval required before GitLab comment.",
            ]
        )
    for incident in context.get("incidents", [])[:2]:
        rows.append(
            [
                "Incident",
                incident.severity,
                _redact_secret_text(incident.probable_root_cause),
                incident.title,
                _safe_join(incident.recommendations[:1]) or "Review incident timeline.",
                "Approval required before external action.",
            ]
        )
    for action in (prepared_actions or context.get("actions", []))[:3]:
        rows.append(
            [
                "Action",
                action.status,
                _redact_secret_text(action.summary),
                f"{action.channel} / {action.action_type}",
                "Review payload, then approve or reject.",
                "Requires approval." if action.requires_approval else "No approval required.",
            ]
        )
    if not rows:
        rows.append(["Evidence", "missing", "No matching records are stored.", "No pipeline/job/risk evidence found.", "Sync GitLab and refresh repo context.", "Do not execute actions."])

    lines = [
        f"Table view for {subject}:",
        "",
        "| Area | Status | What went wrong | Evidence | Next step | Safety |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend("| " + " | ".join(_md_cell(cell) for cell in row) + " |" for row in rows[:10])
    lines.append("")
    lines.append("Review the evidence and approve only actions whose payload matches this table.")
    return "\n".join(lines)


def _checklist_answer(*, subject: str, intent: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
    items: list[str] = [f"Checklist for {subject}:"]
    failed_jobs = context.get("failed_jobs", [])
    insights = [item for item in context.get("pipeline_insights", []) if item.status == "failed"]
    risks = context.get("risks", [])
    incidents = context.get("incidents", [])
    actions = prepared_actions or context.get("actions", [])
    if insights:
        items.append(f"- [ ] Verify pipeline #{insights[0].pipeline_id}: {_redact_secret_text(insights[0].likely_cause)}")
    if failed_jobs:
        job = failed_jobs[0]
        items.append(f"- [ ] Open failed job `{job.name}` in stage `{job.stage}` and inspect the first failing command.")
    if risks:
        items.append(f"- [ ] Review deployment risk {risks[0].score}/100 {risks[0].level}: {_redact_secret_text(risks[0].summary)}")
    if incidents:
        items.append(f"- [ ] Check incident `{incidents[0].title}` and confirm whether the probable root cause still matches fresh evidence.")
    if actions:
        items.append("- [ ] Review prepared action payloads; approve only the action that matches the evidence.")
    items.append("- [ ] Keep Slack/GitLab writes approval-gated; do not execute live actions from chat alone.")
    if len(items) == 2:
        items.insert(1, "- [ ] Sync GitLab projects, pipelines, failed jobs, and repository context before making a diagnosis.")
    return "\n".join(items)


def _concise_answer(*, subject: str, intent: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
    insight = next((item for item in context.get("pipeline_insights", []) if item.status == "failed"), None)
    risk = context.get("risks", [None])[0]
    incident = context.get("incidents", [None])[0]
    if intent == "risk" and risk:
        return f"Short answer for {subject}: the top delivery risk is {risk.score}/100 {risk.level}. {_redact_secret_text(risk.summary)} Next step: {_safe_join(risk.recommendations[:1]) or 'require owner review.'}"
    if insight:
        return f"Short answer for {subject}: pipeline #{insight.pipeline_id} failed because {_redact_secret_text(insight.likely_cause)} Next step: {_safe_join(insight.recommendations[:1]) or 'inspect the failed job log.'}"
    if risk:
        return f"Short answer for {subject}: the top delivery risk is {risk.score}/100 {risk.level}. {_redact_secret_text(risk.summary)} Next step: {_safe_join(risk.recommendations[:1]) or 'require owner review.'}"
    if incident:
        return f"Short answer for {subject}: the active incident is `{incident.title}`. Probable root cause: {_redact_secret_text(incident.probable_root_cause)}."
    return f"Short answer for {subject}: I do not have enough stored evidence to diagnose this yet. Sync GitLab pipelines, failed jobs, and repository context first."


def _md_cell(value: object) -> str:
    text = _redact_secret_text(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("|", "\\|")
    return text[:220] or "-"


def _safe_join(values: list[object]) -> str:
    return "; ".join(_redact_secret_text(str(value)) for value in values if str(value or "").strip())


def _best_fix_source(context: dict) -> tuple[str, str]:
    risks = sorted(context.get("risks", []), key=lambda risk: getattr(risk, "score", 0), reverse=True)
    if risks:
        return "risk", str(risks[0].id)
    pipeline_insights = context.get("pipeline_insights", [])
    if pipeline_insights:
        return "pipeline", str(pipeline_insights[0].id)
    incidents = context.get("incidents", [])
    if incidents:
        return "incident", str(incidents[0].id)
    recommendations = context.get("recommendations", [])
    if recommendations:
        return "recommendation", str(recommendations[0].id)
    return "manual", ""


def _requested_fix_type(message: str) -> str:
    text = message.lower()
    if "timeout" in text or "retry" in text or "ci" in text or "pipeline" in text:
        return "pipeline_timeout"
    if "test" in text or "coverage" in text:
        return "test_scaffold"
    if "deployment" in text or "health" in text or "readiness" in text:
        return "deployment_healthcheck"
    if "rollback" in text or "incident" in text or "runbook" in text:
        return "rollback_runbook"
    return ""


def _redact_secret_text(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(client_secret|password|api_key|private_key)\s*=\s*[^\s,;]+", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?i)\b(authorization:\s*bearer)\s+[^\s,;]+", r"\1 [REDACTED_SECRET]", text)
    text = re.sub(r"(?i)\b(xox[baprs]-|glpat-)[A-Za-z0-9_\-]+", "[REDACTED_SECRET]", text)
    text = re.sub(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", "[REDACTED_SECRET]", text, flags=re.DOTALL)
    return text
