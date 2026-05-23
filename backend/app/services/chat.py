from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import models
from app.agents.gemini import GeminiReasoner
from app.services.agent_tools import AgentToolService


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
        context = self._context(project)
        prepared_actions = self._prepare_actions_if_requested(message, project)
        citations = self._citations(intent, context, prepared_actions)
        deterministic_answer = self._compose_answer(intent, message, project, context, prepared_actions)
        answer = self._llm_answer(
            question=message,
            intent=intent,
            project=project,
            context=context,
            citations=citations,
            prepared_actions=prepared_actions,
            deterministic_answer=deterministic_answer,
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

    def _context(self, project: models.GitLabProject | None) -> dict:
        return self.tools.chat_context(project)

    def _prepare_actions_if_requested(self, message: str, project: models.GitLabProject | None) -> list[models.AgentAction]:
        lowered = message.lower()
        if not any(word in lowered for word in ["prepare", "propose", "create action", "draft action", "make action"]):
            return []

        return self.tools.prepare_action_records(project=project, limit=10)

    def _compose_answer(self, intent: str, question: str, project: models.GitLabProject | None, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        subject = project.project_path if project else "all synced projects"
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

        if "why" in question.lower() or "what should" in question.lower():
            parts.append("Recommended next step: inspect the cited risk, pipeline, and recommendation records first; then approve only the proposed action whose payload matches what you want sent.")

        return "\n".join(parts)

    def _pipeline_answer(self, subject: str, context: dict, prepared_actions: list[models.AgentAction]) -> str:
        pipelines = context["pipelines"]
        insights = context["pipeline_insights"]
        failed_jobs = context["failed_jobs"]
        parts = [f"Pipeline analysis for {subject}:"]
        if insights:
            insight = insights[0]
            parts.append(f"- Likely cause: {insight.likely_cause}")
            if insight.evidence:
                parts.append(f"- Evidence: {'; '.join(insight.evidence[:3])}")
            if insight.recommendations:
                parts.append(f"- Next action: {insight.recommendations[0]}")
        elif failed_jobs:
            job = failed_jobs[0]
            parts.append(f"- The most recent failed job is {job.name} in stage {job.stage}. GitLab reported {job.failure_reason or job.status}.")
            parts.append("- Next action: open the failed job log and inspect the first failing command or timeout boundary.")
        elif pipelines:
            latest = pipelines[0]
            failed_count = len([pipeline for pipeline in pipelines if pipeline.status == "failed"])
            parts.append(f"- Latest synced pipeline #{latest.pipeline_id} is {latest.status} on ref {latest.ref or 'unknown'}.")
            parts.append(f"- Recent failed pipeline count in the synced window: {failed_count}.")
            parts.append("- No parsed failed job or pipeline insight is stored yet, so Panopticon cannot name an exact root cause from logs.")
        else:
            parts.append("- No pipeline snapshots, failed jobs, or pipeline insights are stored for this scope.")
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

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
        self._append_prepared(parts, prepared_actions)
        return "\n".join(parts)

    def _append_prepared(self, parts: list[str], prepared_actions: list[models.AgentAction]) -> None:
        if prepared_actions:
            ids = ", ".join(str(action.id) for action in prepared_actions)
            parts.append(f"- Prepared action proposal(s): {ids}. They require approval in the Actions page before execution.")

    def _citations(self, intent: str, context: dict, prepared_actions: list[models.AgentAction]) -> list[dict]:
        intent_sources = {
            "pipeline_failure": ["pipeline_insights", "failed_jobs", "pipelines"],
            "priority": ["risks", "pipeline_insights", "failed_jobs", "incidents", "actions"],
            "risk": ["risks", "recommendations"],
            "merge_request": ["merge_requests", "risks"],
            "incident": ["incidents", "memory", "recommendations"],
            "actions": ["actions", "recommendations"],
            "memory": ["memory", "incidents"],
            "summary": ["risks", "pipeline_insights", "pipelines", "merge_requests", "incidents", "recommendations", "actions", "memory"],
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
        summary = f"{record.status}; {record.failure_reason or 'no failure reason'}"
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
    else:
        label = getattr(record, "title", "") or getattr(record, "name", "") or getattr(record, "summary", "") or kind
        summary = getattr(record, "summary", "") or getattr(record, "likely_cause", "") or getattr(record, "probable_root_cause", "") or getattr(record, "status", "")
    return {
        "type": kind,
        "id": record.id,
        "label": str(label)[:160],
        "summary": str(summary)[:240],
    }


def _llm_evidence(intent: str, context: dict, citations: list[dict], prepared_actions: list[models.AgentAction]) -> list[dict]:
    selected_ids = {(citation["type"], citation["id"]) for citation in citations}
    evidence: list[dict] = []
    for kind, records in context.items():
        if kind == "project":
            continue
        for record in records[:3]:
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
                "likely_cause": record.likely_cause,
                "evidence": record.evidence,
                "recommendations": record.recommendations,
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
    return base


def _now():
    return datetime.now(timezone.utc)


def _classify_intent(message: str) -> str:
    text = message.lower()
    has_priority_word = any(term in text for term in ["which", "first", "worst", "highest", "top", "prioritize", "priority", "look at"])
    has_risk_word = any(term in text for term in ["risk", "risky", "danger", "safe", "unsafe", "deployment"])
    has_failure_word = any(term in text for term in ["pipeline", "ci", "job", "build", "test failed", "timeout", "fail", "failure"])
    if has_priority_word and (has_risk_word or has_failure_word):
        return "priority"
    if has_risk_word and has_failure_word:
        return "priority"
    if has_failure_word:
        return "pipeline_failure"
    if has_risk_word:
        return "risk"
    if any(term in text for term in ["merge request", "mr ", "review", "branch"]):
        return "merge_request"
    if any(term in text for term in ["incident", "rollback", "outage", "root cause"]):
        return "incident"
    if any(term in text for term in ["action", "approve", "approval", "execute", "prepare", "propose"]):
        return "actions"
    if any(term in text for term in ["memory", "remember", "history", "recurring", "previous"]):
        return "memory"
    return "summary"
