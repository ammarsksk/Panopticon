import re
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.agents.gemini import GeminiReasoner
from app.services.agent_memory import is_stale_failure_memory


class GroundedRecommendationEngine:
    """Evidence-backed recommendation pipeline used by chat, API, and tools."""

    def __init__(self, db: Session, workspace_id: int | None = None, reasoner: GeminiReasoner | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.reasoner = reasoner or GeminiReasoner()

    def recommend(
        self,
        *,
        project: models.GitLabProject | None,
        question: str = "",
        intent: str = "summary",
        context: dict[str, Any] | None = None,
        use_live_reasoner: bool = True,
    ) -> dict[str, Any]:
        project_path = project.project_path if project else ""
        issue_type = _classify_issue(intent=intent, question=question, context=context or {})
        evidence = self._retrieve(project_path=project_path, issue_type=issue_type, question=question, context=context)
        deterministic = _deterministic_recommendation(project_path=project_path, issue_type=issue_type, evidence=evidence)
        generated = deterministic
        if use_live_reasoner:
            generated = self.reasoner.grounded_recommendation(
                issue_type=issue_type,
                project_path=project_path or "all synced projects",
                question=question,
                evidence=evidence,
                deterministic_draft=deterministic,
            )
        validation = validate_recommendation(generated, evidence)
        if not validation["grounded"]:
            generated = deterministic
            validation = validate_recommendation(generated, evidence)

        confidence = score_confidence(evidence=evidence, validation=validation, issue_type=issue_type)
        severity = _severity(issue_type=issue_type, evidence=evidence)
        return {
            "project_path": project_path,
            "issue_type": issue_type,
            "severity": severity,
            "confidence": confidence,
            "grounded": validation["grounded"],
            "validation_errors": validation["errors"],
            "summary": _first_sentence(generated),
            "recommendation": generated,
            "evidence": evidence,
            "next_actions": _next_actions(issue_type, evidence, confidence),
            "proposed_action": _proposed_action(issue_type, severity, confidence),
        }

    def create_recommendation(
        self,
        *,
        project: models.GitLabProject,
        question: str = "",
        intent: str = "summary",
        context: dict[str, Any] | None = None,
        channel: str = "dashboard",
    ) -> models.Recommendation:
        bundle = self.recommend(project=project, question=question, intent=intent, context=context)
        source = _primary_source(bundle["evidence"])
        message = _message(bundle)
        recommendation = models.Recommendation(
            workspace_id=project.workspace_id or self.workspace_id,
            project_path=project.project_path,
            source_type=source["type"],
            source_id=str(source["id"]),
            channel=channel,
            message=message,
            status="pending",
        )
        self.db.add(recommendation)
        self.db.commit()
        self.db.refresh(recommendation)
        return recommendation

    def _retrieve(
        self,
        *,
        project_path: str,
        issue_type: str,
        question: str,
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        if context:
            return _rank_evidence(_context_evidence(context, issue_type=issue_type, question=question))[:12]

        evidence: list[dict[str, Any]] = []
        evidence.extend(_records_to_evidence("risks", self._records(models.RiskAssessment, project_path, desc(models.RiskAssessment.score), 8)))
        evidence.extend(_records_to_evidence("pipeline_insights", self._records(models.PipelineInsight, project_path, desc(models.PipelineInsight.created_at), 8)))
        evidence.extend(_records_to_evidence("failed_jobs", self._records(models.JobSnapshot, project_path, desc(models.JobSnapshot.synced_at), 8, models.JobSnapshot.status == "failed")))
        evidence.extend(_records_to_evidence("merge_requests", self._records(models.MergeRequestSnapshot, project_path, desc(models.MergeRequestSnapshot.updated_at_gitlab), 8)))
        evidence.extend(_records_to_evidence("repo_files", self._records(models.RepoFileIndex, project_path, desc(models.RepoFileIndex.indexed_at), 12)))
        evidence.extend(_records_to_evidence("repo_chunks", self._records(models.RepoCodeChunk, project_path, desc(models.RepoCodeChunk.indexed_at), 12)))
        evidence.extend(_records_to_evidence("repo_symbols", self._records(models.RepoSymbolIndex, project_path, desc(models.RepoSymbolIndex.indexed_at), 12)))
        evidence.extend(_records_to_evidence("memory", self._records(models.MemoryRecord, project_path, desc(models.MemoryRecord.created_at), 5)))
        return _rank_evidence(evidence, issue_type=issue_type, question=question)[:12]

    def _records(self, model, project_path: str, order_by, limit: int, *filters) -> list[Any]:
        stmt = select(model)
        if self.workspace_id is not None and hasattr(model, "workspace_id"):
            stmt = stmt.where(model.workspace_id == self.workspace_id)
        if project_path and hasattr(model, "project_path"):
            stmt = stmt.where(model.project_path == project_path)
        for filter_expr in filters:
            stmt = stmt.where(filter_expr)
        records = self.db.scalars(stmt.order_by(order_by).limit(limit)).all()
        if model is models.MemoryRecord:
            records = [record for record in records if not is_stale_failure_memory(record)]
        return records


def validate_recommendation(text: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    supported_files = {str(item.get("file_path")) for item in evidence if item.get("file_path")}
    supported_jobs = {str(item.get("job_id")) for item in evidence if item.get("job_id")}
    supported_pipelines = {str(item.get("pipeline_id")) for item in evidence if item.get("pipeline_id")}
    supported_mrs = {str(item.get("merge_request_iid")) for item in evidence if item.get("merge_request_iid")}

    for file_path in _mentioned_paths(text):
        if supported_files and file_path not in supported_files:
            errors.append(f"Unsupported file claim: {file_path}")
    for label, supported in [("job", supported_jobs), ("pipeline", supported_pipelines), ("MR", supported_mrs)]:
        for identifier in _mentioned_identifiers(text, label):
            if supported and identifier not in supported:
                errors.append(f"Unsupported {label} claim: {identifier}")

    weak = evidence_strength(evidence) < 0.35
    if weak and _claims_root_cause(text):
        errors.append("Root cause is asserted even though evidence is weak")

    return {"grounded": not errors, "errors": errors}


def score_confidence(*, evidence: list[dict[str, Any]], validation: dict[str, Any], issue_type: str) -> float:
    score = evidence_strength(evidence)
    if issue_type in {"pipeline_failure", "deployment_risk"}:
        score += 0.08
    if validation.get("grounded"):
        score += 0.12
    else:
        score -= 0.25
    return round(max(0.05, min(score, 0.97)), 2)


def evidence_strength(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.05
    score = 0.12
    kinds = {item["type"] for item in evidence}
    score += min(len(evidence), 8) * 0.045
    score += len(kinds) * 0.035
    if any(item["type"] == "repo_files" for item in evidence):
        score += 0.12
    if any(item["type"] in {"repo_chunks", "repo_symbols"} for item in evidence):
        score += 0.14
    if any(item["type"] in {"failed_jobs", "pipeline_insights"} for item in evidence):
        score += 0.13
    if any(item["type"] == "risks" for item in evidence):
        score += 0.08
    if any(item["type"] == "memory" for item in evidence):
        score += 0.05
    return min(score, 0.85)


def _context_evidence(context: dict[str, Any], *, issue_type: str, question: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for kind in ["risks", "pipeline_insights", "failed_jobs", "pipelines", "merge_requests", "repo_files", "repo_chunks", "repo_symbols", "incidents", "memory", "recommendations"]:
        records = context.get(kind, []) or []
        evidence.extend(_records_to_evidence(kind, records[:8]))
    return _rank_evidence(evidence, issue_type=issue_type, question=question)


def _records_to_evidence(kind: str, records: list[Any]) -> list[dict[str, Any]]:
    return [_record_to_evidence(kind, record) for record in records]


def _record_to_evidence(kind: str, record: Any) -> dict[str, Any]:
    base = {"type": kind, "id": getattr(record, "id", 0), "project_path": getattr(record, "project_path", "")}
    if isinstance(record, models.RiskAssessment):
        base.update(
            {
                "label": f"Risk {record.score}/100 {record.level}",
                "summary": record.summary,
                "merge_request_iid": record.merge_request_iid,
                "score": record.score,
                "level": record.level,
                "details": record.reasons,
            }
        )
    elif isinstance(record, models.PipelineInsight):
        base.update(
            {
                "label": f"Pipeline insight #{record.pipeline_id}",
                "summary": record.likely_cause,
                "pipeline_id": record.pipeline_id,
                "status": record.status,
                "details": record.evidence,
            }
        )
    elif isinstance(record, models.JobSnapshot):
        base.update(
            {
                "label": f"Job {record.name}",
                "summary": record.trace_summary or f"{record.status}; {record.failure_reason or 'no failure reason'}",
                "pipeline_id": record.pipeline_id,
                "job_id": record.job_id,
                "stage": record.stage,
                "failure_signature": record.failure_signature,
                "trace_excerpt": record.trace_excerpt[:1200] if record.trace_excerpt else "",
                "details": [item for item in [record.web_url, record.trace_summary] if item],
            }
        )
    elif isinstance(record, models.PipelineSnapshot):
        base.update(
            {
                "label": f"Pipeline #{record.pipeline_id}",
                "summary": f"{record.status} on {record.ref or 'unknown ref'}",
                "pipeline_id": record.pipeline_id,
                "sha": record.sha,
                "ref": record.ref,
                "details": [record.web_url] if record.web_url else [],
            }
        )
    elif isinstance(record, models.MergeRequestSnapshot):
        base.update(
            {
                "label": f"MR !{record.merge_request_iid}",
                "summary": record.title,
                "merge_request_iid": record.merge_request_iid,
                "source_branch": record.source_branch,
                "target_branch": record.target_branch,
                "details": [record.web_url] if record.web_url else [],
            }
        )
    elif isinstance(record, models.RepoFileIndex):
        flags = (record.signals or {}).get("risk_flags") or []
        base.update(
            {
                "label": f"{record.file_type}: {record.file_path}",
                "summary": ", ".join(flags) or record.language or "indexed repository file",
                "file_path": record.file_path,
                "file_type": record.file_type,
                "language": record.language,
                "details": [record.content_excerpt[:1200]],
            }
        )
    elif isinstance(record, models.RepoCodeChunk):
        base.update(
            {
                "label": f"Code chunk {record.file_path}:{record.start_line}-{record.end_line}",
                "summary": ", ".join((record.keywords or [])[:8]) or record.language or "indexed code chunk",
                "file_path": record.file_path,
                "language": record.language,
                "start_line": record.start_line,
                "end_line": record.end_line,
                "embedding_provider": record.embedding_provider,
                "embedding_status": record.embedding_status,
                "details": [record.content[:1200]],
            }
        )
    elif isinstance(record, models.RepoSymbolIndex):
        base.update(
            {
                "label": f"{record.symbol_type}: {record.symbol_name}",
                "summary": record.signature or record.file_path,
                "file_path": record.file_path,
                "symbol_name": record.symbol_name,
                "symbol_type": record.symbol_type,
                "start_line": record.start_line,
                "details": [record.signature],
            }
        )
    elif isinstance(record, models.IncidentRecord):
        base.update({"label": record.title, "summary": record.probable_root_cause, "severity": record.severity, "details": record.recommendations})
    elif isinstance(record, models.MemoryRecord):
        base.update({"label": record.signature, "summary": record.summary, "memory_type": record.memory_type, "details": record.evidence})
    elif isinstance(record, models.Recommendation):
        base.update({"label": f"{record.source_type} recommendation", "summary": record.message[:240], "details": [record.status]})
    else:
        base.update({"label": getattr(record, "title", "") or kind, "summary": getattr(record, "summary", "") or getattr(record, "status", ""), "details": []})
    return base


def _rank_evidence(evidence: list[dict[str, Any]], *, issue_type: str = "summary", question: str = "") -> list[dict[str, Any]]:
    keywords = set(re.findall(r"[a-zA-Z0-9_.-]{4,}", question.lower()))

    def score(item: dict[str, Any]) -> float:
        kind_weight = {
            "pipeline_insights": 0.9,
            "failed_jobs": 0.85,
            "risks": 0.8,
            "repo_files": 0.7,
            "repo_chunks": 0.76,
            "repo_symbols": 0.68,
            "merge_requests": 0.55,
            "pipelines": 0.45,
            "incidents": 0.45,
            "memory": 0.35,
            "recommendations": 0.25,
        }.get(item["type"], 0.2)
        if issue_type == "pipeline_failure" and item["type"] in {"pipeline_insights", "failed_jobs", "repo_files", "repo_chunks", "repo_symbols", "pipelines"}:
            kind_weight += 0.2
        if issue_type == "deployment_risk" and item["type"] in {"risks", "repo_files", "repo_chunks", "repo_symbols", "merge_requests"}:
            kind_weight += 0.2
        text = " ".join([str(item.get("label", "")), str(item.get("summary", "")), str(item.get("file_path", ""))]).lower()
        keyword_weight = sum(0.04 for keyword in keywords if keyword in text)
        return kind_weight + keyword_weight

    seen: set[tuple[str, Any]] = set()
    unique: list[dict[str, Any]] = []
    for item in sorted(evidence, key=score, reverse=True):
        key = (item["type"], item.get("id") or item.get("file_path"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _classify_issue(*, intent: str, question: str, context: dict[str, Any]) -> str:
    text = question.lower()
    if intent == "pipeline_failure" or any(term in text for term in ["pipeline", "job", "ci", "timeout", "build"]):
        return "pipeline_failure"
    if intent == "risk" or any(term in text for term in ["risk", "deployment", "unsafe"]):
        return "deployment_risk"
    if any(term in text for term in ["incident", "rollback", "outage"]):
        return "incident"
    if context.get("pipeline_insights") or context.get("failed_jobs"):
        return "pipeline_failure"
    if context.get("risks"):
        return "deployment_risk"
    return "operational_summary"


def _deterministic_recommendation(*, project_path: str, issue_type: str, evidence: list[dict[str, Any]]) -> str:
    subject = project_path or "the selected workspace"
    if not evidence:
        return f"I cannot determine a root cause for {subject} because no pipeline, job, MR, or repository evidence is indexed yet. Sync GitLab and refresh repository context before approving any action."

    files = [item["file_path"] for item in evidence if item.get("file_path")][:3]
    jobs = [item for item in evidence if item["type"] == "failed_jobs"]
    pipelines = [item for item in evidence if item.get("pipeline_id")]
    risks = [item for item in evidence if item["type"] == "risks"]
    parts = [f"For {subject}, the recommendation is grounded in {len(evidence)} evidence item(s)."]
    if issue_type == "pipeline_failure" and jobs:
        job = jobs[0]
        parts.append(f"Start with job {job.get('job_id')} in stage {job.get('stage')}, then compare it with pipeline {job.get('pipeline_id')}.")
    elif issue_type == "pipeline_failure" and pipelines:
        parts.append(f"Start with pipeline {pipelines[0].get('pipeline_id')} because it is the strongest stored failure signal.")
    elif issue_type == "deployment_risk" and risks:
        risk = risks[0]
        parts.append(f"Treat {risk.get('label')} as the gate because the stored reasons support a deployment review.")
    else:
        parts.append("Use the highest-ranked evidence first and avoid asserting a root cause until job logs or repo context prove it.")
    if files:
        parts.append(f"Inspect repository file(s): {', '.join(files)}.")
    parts.append("Require approval before sending Slack/GitLab actions or creating code changes.")
    return " ".join(parts)


def _next_actions(issue_type: str, evidence: list[dict[str, Any]], confidence: float) -> list[str]:
    actions = []
    files = [item["file_path"] for item in evidence if item.get("file_path")]
    if files:
        actions.append(f"Inspect indexed file evidence: {', '.join(files[:3])}.")
    if issue_type == "pipeline_failure":
        actions.append("Open the failed GitLab job or pipeline log and verify the first failing command.")
    if issue_type == "deployment_risk":
        actions.append("Require service-owner review before merge or deployment.")
    if confidence < 0.55:
        actions.append("Refresh repository context and sync failed job logs before naming a root cause.")
    actions.append("Only approve generated actions after their payload matches the cited evidence.")
    return actions


def _proposed_action(issue_type: str, severity: str, confidence: float) -> dict[str, Any]:
    if confidence < 0.55:
        return {"type": "investigate", "channel": "dashboard", "requires_approval": False}
    if issue_type == "pipeline_failure":
        return {"type": "slack_alert", "channel": "slack", "requires_approval": True}
    if issue_type == "deployment_risk" and severity in {"critical", "high"}:
        return {"type": "gitlab_comment", "channel": "gitlab_comment", "requires_approval": True}
    return {"type": "dashboard_note", "channel": "dashboard", "requires_approval": False}


def _severity(*, issue_type: str, evidence: list[dict[str, Any]]) -> str:
    risk_scores = [float(item.get("score") or 0) for item in evidence if item["type"] == "risks"]
    if risk_scores:
        top = max(risk_scores)
        if top >= 85:
            return "critical"
        if top >= 70:
            return "high"
    if any(item["type"] in {"pipeline_insights", "failed_jobs"} for item in evidence):
        return "high"
    if issue_type == "incident":
        return "high"
    return "medium" if evidence else "info"


def _message(bundle: dict[str, Any]) -> str:
    evidence_lines = [f"- {item['label']}: {item['summary']}" for item in bundle["evidence"][:6]]
    action_lines = [f"- {item}" for item in bundle["next_actions"][:5]]
    return "\n".join(
        [
            bundle["recommendation"],
            "",
            "Grounded evidence:",
            *(evidence_lines or ["- No evidence available."]),
            "",
            f"Confidence: {int(bundle['confidence'] * 100)}%",
            f"Validation: {'grounded' if bundle['grounded'] else 'needs more evidence'}",
            "",
            "Next actions:",
            *action_lines,
        ]
    )


def _primary_source(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    if not evidence:
        return {"type": "manual", "id": ""}
    item = evidence[0]
    source_type = {
        "risks": "risk",
        "pipeline_insights": "pipeline",
        "failed_jobs": "pipeline",
        "incidents": "incident",
        "repo_files": "repository",
        "repo_chunks": "repository",
        "repo_symbols": "repository",
    }.get(item["type"], item["type"])
    return {"type": source_type, "id": item.get("id", "")}


def _first_sentence(text: str) -> str:
    stripped = " ".join((text or "").split())
    match = re.search(r"(.+?[.!?])(?:\s|$)", stripped)
    return match.group(1) if match else stripped[:220]


def _mentioned_paths(text: str) -> list[str]:
    return re.findall(r"(?<![\w/.-])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+", text)


def _mentioned_identifiers(text: str, label: str) -> list[str]:
    if label == "MR":
        return re.findall(r"!(\d+)", text)
    return re.findall(rf"{label}\s+#?(\d+)", text, flags=re.IGNORECASE)


def _claims_root_cause(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ["root cause is", "caused by", "failed because", "due to"])
