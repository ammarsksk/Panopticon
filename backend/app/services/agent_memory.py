from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.services.chat_validation import contains_failure_notice


MEMORY_TYPES = {
    "project_memory",
    "incident_memory",
    "failure_signature_memory",
    "approved_action_memory",
    "rejected_action_memory",
    "fix_plan_memory",
    "user_preference_memory",
    "workspace_policy_memory",
}


@dataclass(frozen=True)
class MemoryBundle:
    records: list[models.MemoryRecord]
    created: list[models.MemoryRecord]


class AgentMemoryService:
    """Workspace-scoped operational memory with evidence-linked records."""

    def __init__(self, db: Session, workspace_id: int | None = None) -> None:
        self.db = db
        self.workspace_id = workspace_id

    def capture_user_memory(self, *, message: str, project: models.GitLabProject | None = None) -> list[models.MemoryRecord]:
        text = message.strip()
        preference = _preference_from_message(text)
        if not preference:
            return []
        preference = _redact_secret_text(preference)
        project_path = project.project_path if project else ""
        record = self._upsert_memory(
            project_path=project_path,
            memory_type="user_preference_memory",
            signature=_signature("user_preference", project_path, preference),
            summary=f"User preference: {preference}",
            evidence=[f"user_message:{_truncate(text, 240)}", f"captured_at:{_now().isoformat()}"],
            remediation=["Respect this preference when formatting future answers, unless fresh evidence or safety rules require otherwise."],
        )
        return [record]

    def retrieve(self, *, project: models.GitLabProject | None, question: str, current_memory: list[models.MemoryRecord] | None = None, limit: int = 8) -> list[models.MemoryRecord]:
        project_path = project.project_path if project else ""
        records = list(current_memory or [])
        stmt = select(models.MemoryRecord)
        if self.workspace_id is not None:
            stmt = stmt.where(models.MemoryRecord.workspace_id == self.workspace_id)
        if project_path:
            stmt = stmt.where((models.MemoryRecord.project_path == project_path) | (models.MemoryRecord.project_path == ""))
        else:
            stmt = stmt.where(models.MemoryRecord.project_path == "")
        fetched = self.db.scalars(stmt.order_by(desc(models.MemoryRecord.created_at)).limit(50)).all()
        records.extend(fetched)
        return _rank_memory([record for record in _dedupe(records) if not is_stale_failure_memory(record)], question=question)[:limit]

    def remember_prepared_fix_plan(self, plan: models.FixPlan) -> models.MemoryRecord:
        return self._upsert_memory(
            project_path=plan.project_path,
            memory_type="fix_plan_memory",
            signature=_signature("fix_plan", plan.project_path, str(plan.id)),
            summary=f"Fix plan #{plan.id} is {plan.status}: {plan.title}",
            evidence=[f"fix_plan:{plan.id}", f"source:{plan.source_type}:{plan.source_id}", f"branch:{plan.branch_name}"],
            remediation=["Use this fix plan only as historical context; it still requires approval and validation before any GitLab write."],
        )

    def remember_action_decision(self, action: models.AgentAction, *, decision: str, actor: str, reason: str) -> models.MemoryRecord:
        memory_type = "approved_action_memory" if decision == "approved" else "rejected_action_memory"
        return self._upsert_memory(
            project_path=action.project_path,
            memory_type=memory_type,
            signature=_signature(memory_type, action.project_path, str(action.id)),
            summary=f"Action #{action.id} was {decision}: {action.title}",
            evidence=[f"action:{action.id}", f"actor:{actor or 'local_user'}", f"reason:{reason or 'not provided'}", f"status:{action.status}"],
            remediation=[
                "Treat prior approvals/rejections as preference evidence, not permission.",
                "Require a fresh approval before executing any new action.",
            ],
        )

    def remember_fix_plan_decision(self, plan: models.FixPlan, *, decision: str, actor: str, reason: str) -> models.MemoryRecord:
        return self._upsert_memory(
            project_path=plan.project_path,
            memory_type="fix_plan_memory",
            signature=_signature("fix_plan_decision", plan.project_path, str(plan.id), decision),
            summary=f"Fix plan #{plan.id} was {decision}: {plan.title}",
            evidence=[f"fix_plan:{plan.id}", f"actor:{actor or 'local_user'}", f"reason:{reason or 'not provided'}", f"status:{plan.status}"],
            remediation=["Use this decision as historical context only; do not bypass approval for future code changes."],
        )

    def remember_answer_pattern(self, *, project_path: str, intent: str, answer: str, evidence_labels: list[str]) -> models.MemoryRecord | None:
        if intent not in {"pipeline_failure", "incident", "risk"}:
            return None
        if not evidence_labels:
            return None
        if contains_failure_notice(answer):
            return None
        memory_type = {
            "pipeline_failure": "failure_signature_memory",
            "incident": "incident_memory",
            "risk": "project_memory",
        }[intent]
        return self._upsert_memory(
            project_path=project_path,
            memory_type=memory_type,
            signature=_signature(memory_type, project_path, _truncate("|".join(evidence_labels), 120)),
            summary=_truncate(answer.replace("\n", " "), 360),
            evidence=evidence_labels[:8],
            remediation=["Prefer fresh GitLab evidence over this memory when they disagree."],
        )

    def _upsert_memory(self, *, project_path: str, memory_type: str, signature: str, summary: str, evidence: list[str], remediation: list[str]) -> models.MemoryRecord:
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {memory_type}")
        stmt = select(models.MemoryRecord).where(models.MemoryRecord.memory_type == memory_type).where(models.MemoryRecord.signature == signature)
        if self.workspace_id is not None:
            stmt = stmt.where(models.MemoryRecord.workspace_id == self.workspace_id)
        existing = self.db.scalar(stmt)
        if existing:
            existing.summary = _redact_secret_text(summary)
            existing.evidence = _redact_list(evidence)
            existing.remediation = _redact_list(remediation)
            existing.created_at = _now()
            self.db.flush()
            return existing
        record = models.MemoryRecord(
            workspace_id=self.workspace_id,
            project_path=project_path,
            memory_type=memory_type,
            signature=signature,
            summary=_redact_secret_text(summary),
            evidence=_redact_list(evidence),
            remediation=_redact_list(remediation),
        )
        self.db.add(record)
        self.db.flush()
        return record


def is_stale_failure_memory(record: models.MemoryRecord) -> bool:
    values = [record.summary or ""]
    values.extend(record.evidence or [])
    values.extend(record.remediation or [])
    return any(contains_failure_notice(value) for value in values)


def _rank_memory(records: list[models.MemoryRecord], *, question: str) -> list[models.MemoryRecord]:
    keywords = {item for item in re.findall(r"[a-zA-Z0-9_.-]{4,}", question.lower())}
    type_weight = {
        "workspace_policy_memory": 100,
        "user_preference_memory": 92,
        "failure_signature_memory": 86,
        "incident_memory": 82,
        "approved_action_memory": 76,
        "rejected_action_memory": 76,
        "fix_plan_memory": 72,
        "project_memory": 68,
    }

    def score(record: models.MemoryRecord) -> int:
        text = " ".join([record.memory_type, record.signature, record.summary, " ".join(record.evidence or [])]).lower()
        return type_weight.get(record.memory_type, 20) + sum(3 for keyword in keywords if keyword in text)

    return sorted(records, key=score, reverse=True)


def _dedupe(records: list[models.MemoryRecord]) -> list[models.MemoryRecord]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[models.MemoryRecord] = []
    for record in records:
        key = (record.project_path, record.memory_type, record.signature)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def _preference_from_message(message: str) -> str:
    lowered = message.lower()
    if not any(term in lowered for term in ["remember that", "please remember", "prefer", "preference", "always answer", "use tables", "use checklist"]):
        return ""
    match = re.search(r"(?i)(?:please\s+)?remember\s+that\s+(.+)", message)
    if match:
        return _truncate(match.group(1).strip(" ."), 220)
    match = re.search(r"(?i)(prefer .+|always answer .+|use tables.+|use checklist.+)", message)
    return _truncate(match.group(1).strip(" ."), 220) if match else ""


def _signature(*parts: str) -> str:
    raw = ":".join(part.strip().lower() for part in parts if part.strip())
    return re.sub(r"[^a-z0-9_.:-]+", "-", raw).strip("-")[:240] or "memory"


def _redact_list(values: list[str]) -> list[str]:
    return [_redact_secret_text(value) for value in values]


def _redact_secret_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(client_secret|password|api_key|private_key)\s*=\s*[^\s,;]+", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?i)\b(xox[baprs]-|glpat-)[A-Za-z0-9_\-]+", "[REDACTED_SECRET]", text)
    return text


def _truncate(value: str, limit: int) -> str:
    return value[:limit].strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)
