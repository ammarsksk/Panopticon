from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationalEvent(Base):
    __tablename__ = "operational_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="gitlab", index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    severity: Mapped[str] = mapped_column(String(40), default="info", index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(back_populates="event")
    pipeline_insights: Mapped[list["PipelineInsight"]] = relationship(back_populates="event")
    incidents: Mapped[list["IncidentRecord"]] = relationship(back_populates="event")


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="gitlab", index=True)
    event_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    project_path: Mapped[str] = mapped_column(String(255), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="processing", index=True)
    created_event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    merge_request_iid: Mapped[str] = mapped_column(String(80), default="")
    deployment_ref: Mapped[str] = mapped_column(String(160), default="")
    score: Mapped[float] = mapped_column(Float, index=True)
    level: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(Text)
    reasons: Mapped[list[str]] = mapped_column(JSON)
    recommendations: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    event: Mapped[OperationalEvent | None] = relationship(back_populates="risk_assessments")


class PipelineInsight(Base):
    __tablename__ = "pipeline_insights"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    pipeline_id: Mapped[str] = mapped_column(String(80), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    likely_cause: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSON)
    recommendations: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    event: Mapped[OperationalEvent | None] = relationship(back_populates="pipeline_insights")


class MergeRequestSignal(Base):
    __tablename__ = "merge_request_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    merge_request_iid: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(60), default="")
    age_hours: Mapped[float] = mapped_column(Float, default=0)
    unresolved_threads: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_count: Mapped[int] = mapped_column(Integer, default=0)
    bottleneck_level: Mapped[str] = mapped_column(String(40), default="healthy", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class IncidentRecord(Base):
    __tablename__ = "incident_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(40), index=True)
    probable_root_cause: Mapped[str] = mapped_column(Text)
    timeline: Mapped[list[dict]] = mapped_column(JSON)
    recommendations: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    event: Mapped[OperationalEvent | None] = relationship(back_populates="incidents")


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(80), index=True)
    source_id: Mapped[str] = mapped_column(String(80), default="")
    channel: Mapped[str] = mapped_column(String(80), default="dashboard")
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ActionDispatch(Base):
    __tablename__ = "action_dispatches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    memory_type: Mapped[str] = mapped_column(String(80), index=True)
    signature: Mapped[str] = mapped_column(String(255), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSON)
    remediation: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
