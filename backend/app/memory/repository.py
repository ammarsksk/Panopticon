from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app import models


class OperationalMemory:
    def __init__(self, db: Session, workspace_id: int | None = None):
        self.db = db
        self.workspace_id = workspace_id

    def add_event(self, *, event_type: str, project_path: str, title: str, severity: str, payload: dict) -> models.OperationalEvent:
        event = models.OperationalEvent(
            event_type=event_type,
            workspace_id=self.workspace_id,
            project_path=project_path,
            title=title,
            severity=severity,
            payload=payload,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def get_webhook_receipt(self, event_uid: str) -> models.WebhookReceipt | None:
        stmt = select(models.WebhookReceipt).where(models.WebhookReceipt.event_uid == event_uid)
        if self.workspace_id is not None:
            stmt = stmt.where(models.WebhookReceipt.workspace_id == self.workspace_id)
        return self.db.scalar(stmt)

    def add_webhook_receipt(self, *, event_uid: str, event_type: str, project_path: str) -> models.WebhookReceipt:
        receipt = models.WebhookReceipt(event_uid=event_uid, event_type=event_type, project_path=project_path, workspace_id=self.workspace_id)
        self.db.add(receipt)
        self.db.flush()
        return receipt

    def mark_webhook_processed(self, receipt: models.WebhookReceipt, event_id: int) -> None:
        receipt.status = "processed"
        receipt.created_event_id = event_id
        self.db.flush()

    def add_risk(self, *, event_id: int | None, project_path: str, merge_request_iid: str, deployment_ref: str, score: float, level: str, summary: str, reasons: list[str], recommendations: list[str]) -> models.RiskAssessment:
        risk = models.RiskAssessment(
            event_id=event_id,
            workspace_id=self.workspace_id,
            project_path=project_path,
            merge_request_iid=merge_request_iid,
            deployment_ref=deployment_ref,
            score=score,
            level=level,
            summary=summary,
            reasons=reasons,
            recommendations=recommendations,
        )
        self.db.add(risk)
        self.db.flush()
        return risk

    def add_pipeline_insight(self, *, event_id: int | None, project_path: str, pipeline_id: str, status: str, likely_cause: str, evidence: list[str], recommendations: list[str]) -> models.PipelineInsight:
        insight = models.PipelineInsight(
            event_id=event_id,
            workspace_id=self.workspace_id,
            project_path=project_path,
            pipeline_id=pipeline_id,
            status=status,
            likely_cause=likely_cause,
            evidence=evidence,
            recommendations=recommendations,
        )
        self.db.add(insight)
        self.db.flush()
        return insight

    def add_mr_signal(self, *, project_path: str, merge_request_iid: str, title: str, state: str, age_hours: float, unresolved_threads: int, reviewer_count: int, bottleneck_level: str, summary: str) -> models.MergeRequestSignal:
        signal = models.MergeRequestSignal(
            project_path=project_path,
            workspace_id=self.workspace_id,
            merge_request_iid=merge_request_iid,
            title=title,
            state=state,
            age_hours=age_hours,
            unresolved_threads=unresolved_threads,
            reviewer_count=reviewer_count,
            bottleneck_level=bottleneck_level,
            summary=summary,
        )
        self.db.add(signal)
        self.db.flush()
        return signal

    def add_incident(self, *, event_id: int | None, project_path: str, title: str, severity: str, probable_root_cause: str, timeline: list[dict], recommendations: list[str]) -> models.IncidentRecord:
        incident = models.IncidentRecord(
            event_id=event_id,
            workspace_id=self.workspace_id,
            project_path=project_path,
            title=title,
            severity=severity,
            probable_root_cause=probable_root_cause,
            timeline=timeline,
            recommendations=recommendations,
        )
        self.db.add(incident)
        self.db.flush()
        return incident

    def add_recommendation(self, *, project_path: str, source_type: str, source_id: str, channel: str, message: str, status: str = "pending") -> models.Recommendation:
        recommendation = models.Recommendation(
            project_path=project_path,
            workspace_id=self.workspace_id,
            source_type=source_type,
            source_id=source_id,
            channel=channel,
            message=message,
            status=status,
        )
        self.db.add(recommendation)
        self.db.flush()
        return recommendation

    def add_action_dispatch(self, *, recommendation_id: int | None, channel: str, status: str, target: str = "", request_payload: dict | None = None, response_payload: dict | None = None, error: str = "") -> models.ActionDispatch:
        dispatch = models.ActionDispatch(
            recommendation_id=recommendation_id,
            workspace_id=self.workspace_id,
            channel=channel,
            status=status,
            target=target,
            request_payload=request_payload or {},
            response_payload=response_payload or {},
            error=error,
        )
        self.db.add(dispatch)
        self.db.flush()
        return dispatch

    def add_memory(self, *, project_path: str, memory_type: str, signature: str, summary: str, evidence: list[str], remediation: list[str]) -> models.MemoryRecord:
        record = models.MemoryRecord(
            project_path=project_path,
            workspace_id=self.workspace_id,
            memory_type=memory_type,
            signature=signature,
            summary=summary,
            evidence=evidence,
            remediation=remediation,
        )
        self.db.add(record)
        self.db.flush()
        return record

    def recent_failures(self, project_path: str, limit: int = 10) -> list[models.MemoryRecord]:
        stmt = (
            select(models.MemoryRecord)
            .where(models.MemoryRecord.project_path == project_path)
            .where(models.MemoryRecord.memory_type.in_(["pipeline_failure", "incident", "rollback"]))
            .order_by(desc(models.MemoryRecord.created_at))
            .limit(limit)
        )
        if self.workspace_id is not None:
            stmt = stmt.where(models.MemoryRecord.workspace_id == self.workspace_id)
        return list(self.db.scalars(stmt))

    def dashboard_counts(self) -> dict[str, int]:
        high_risks = self.db.scalar(select(func.count()).select_from(models.RiskAssessment).where(models.RiskAssessment.score >= 70)) or 0
        failed_pipelines = self.db.scalar(select(func.count()).select_from(models.PipelineInsight).where(models.PipelineInsight.status == "failed")) or 0
        blocked_mrs = self.db.scalar(select(func.count()).select_from(models.MergeRequestSignal).where(models.MergeRequestSignal.bottleneck_level.in_(["blocked", "stale"]))) or 0
        open_incidents = self.db.scalar(select(func.count()).select_from(models.IncidentRecord).where(models.IncidentRecord.status == "open")) or 0
        return {
            "active_risks": high_risks,
            "failed_pipelines": failed_pipelines,
            "blocked_merge_requests": blocked_mrs,
            "open_incidents": open_incidents,
        }
