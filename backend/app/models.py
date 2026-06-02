from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OperationalEvent(Base):
    __tablename__ = "operational_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="gitlab", index=True)
    event_uid: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    project_path: Mapped[str] = mapped_column(String(255), default="", index=True)
    status: Mapped[str] = mapped_column(String(40), default="processing", index=True)
    created_event_id: Mapped[int | None] = mapped_column(ForeignKey("operational_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str] = mapped_column(String(500), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="owner", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    state_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    redirect_after: Mapped[str] = mapped_column(String(500), default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    provider_user_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    account_label: Mapped[str] = mapped_column(String(255), default="")
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(120), default="")
    target_id: Mapped[str] = mapped_column(String(120), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class GitLabProject(Base):
    __tablename__ = "gitlab_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    gitlab_project_id: Mapped[str] = mapped_column(String(80), index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    namespace: Mapped[str] = mapped_column(String(255), default="")
    web_url: Mapped[str] = mapped_column(String(500), default="")
    default_branch: Mapped[str] = mapped_column(String(160), default="")
    visibility: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    open_merge_requests_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_pipelines_count: Mapped[int] = mapped_column(Integer, default=0)
    latest_pipeline_id: Mapped[str] = mapped_column(String(80), default="")
    latest_pipeline_status: Mapped[str] = mapped_column(String(40), default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ProjectSyncRun(Base):
    __tablename__ = "project_sync_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), default="gitlab", index=True)
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    projects_seen: Mapped[int] = mapped_column(Integer, default=0)
    projects_updated: Mapped[int] = mapped_column(Integer, default=0)
    merge_requests_seen: Mapped[int] = mapped_column(Integer, default=0)
    pipelines_seen: Mapped[int] = mapped_column(Integer, default=0)
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RepoIndexRun(Base):
    __tablename__ = "repo_index_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("gitlab_projects.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    ref: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(40), default="running", index=True)
    files_seen: Mapped[int] = mapped_column(Integer, default=0)
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RepoFileIndex(Base):
    __tablename__ = "repo_file_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("gitlab_projects.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    file_path: Mapped[str] = mapped_column(String(600), index=True)
    ref: Mapped[str] = mapped_column(String(255), default="", index=True)
    file_type: Mapped[str] = mapped_column(String(80), default="source", index=True)
    language: Mapped[str] = mapped_column(String(80), default="", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_sha: Mapped[str] = mapped_column(String(160), default="", index=True)
    last_commit_id: Mapped[str] = mapped_column(String(160), default="")
    content_excerpt: Mapped[str] = mapped_column(Text, default="")
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class MergeRequestSnapshot(Base):
    __tablename__ = "merge_request_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    gitlab_project_id: Mapped[str] = mapped_column(String(80), index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    merge_request_iid: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[str] = mapped_column(String(60), default="")
    web_url: Mapped[str] = mapped_column(String(500), default="")
    author_username: Mapped[str] = mapped_column(String(120), default="")
    source_branch: Mapped[str] = mapped_column(String(255), default="")
    target_branch: Mapped[str] = mapped_column(String(255), default="")
    draft: Mapped[bool] = mapped_column(default=False)
    created_at_gitlab: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_gitlab: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class PipelineSnapshot(Base):
    __tablename__ = "pipeline_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    gitlab_project_id: Mapped[str] = mapped_column(String(80), index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    pipeline_id: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="", index=True)
    ref: Mapped[str] = mapped_column(String(255), default="")
    sha: Mapped[str] = mapped_column(String(80), default="")
    web_url: Mapped[str] = mapped_column(String(500), default="")
    created_at_gitlab: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at_gitlab: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class JobSnapshot(Base):
    __tablename__ = "job_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    gitlab_project_id: Mapped[str] = mapped_column(String(80), index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    pipeline_id: Mapped[str] = mapped_column(String(80), index=True)
    job_id: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    stage: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="", index=True)
    failure_reason: Mapped[str] = mapped_column(String(255), default="")
    web_url: Mapped[str] = mapped_column(String(500), default="")
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at_gitlab: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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


class ObservabilityEvent(Base):
    __tablename__ = "observability_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(80), default="generic", index=True)
    event_uid: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), default="", index=True)
    service_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    environment: Mapped[str] = mapped_column(String(120), default="", index=True)
    severity: Mapped[str] = mapped_column(String(40), default="info", index=True)
    signal_type: Mapped[str] = mapped_column(String(80), default="alert", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    metric_name: Mapped[str] = mapped_column(String(255), default="")
    trace_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    alert_url: Mapped[str] = mapped_column(String(500), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class IncidentCorrelation(Base):
    __tablename__ = "incident_correlations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    severity: Mapped[str] = mapped_column(String(40), default="info", index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    suspected_cause: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    timeline: Mapped[list[dict]] = mapped_column(JSON, default=list)
    related_observability_event_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    related_pipeline_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    related_risk_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    related_incident_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    recommendations: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class EngineeringMetricSnapshot(Base):
    __tablename__ = "engineering_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    scope_type: Mapped[str] = mapped_column(String(40), default="project", index=True)
    project_path: Mapped[str] = mapped_column(String(255), default="", index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    health_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
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
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class AgentAction(Base):
    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="pending_approval", index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    payload_preview: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_context: Mapped[dict] = mapped_column(JSON, default=dict)
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ActionApproval(Base):
    __tablename__ = "action_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    agent_action_id: Mapped[int] = mapped_column(ForeignKey("agent_actions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="local_user")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class FixPlan(Base):
    __tablename__ = "fix_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("gitlab_projects.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    source_id: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(60), default="draft", index=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    fix_type: Mapped[str] = mapped_column(String(80), default="", index=True)
    base_branch: Mapped[str] = mapped_column(String(255), default="")
    branch_name: Mapped[str] = mapped_column(String(255), default="")
    merge_request_iid: Mapped[str] = mapped_column(String(80), default="")
    merge_request_url: Mapped[str] = mapped_column(String(500), default="")
    plan_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    last_result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class FixPlanApproval(Base):
    __tablename__ = "fix_plan_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    fix_plan_id: Mapped[int] = mapped_column(ForeignKey("fix_plans.id"), index=True)
    decision: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="local_user")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ChatThread(Base):
    __tablename__ = "chat_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("gitlab_projects.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), default="", index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("chat_threads.id"), index=True)
    role: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    prepared_action_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    project_path: Mapped[str] = mapped_column(String(255), index=True)
    memory_type: Mapped[str] = mapped_column(String(80), index=True)
    signature: Mapped[str] = mapped_column(String(255), index=True)
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[str]] = mapped_column(JSON)
    remediation: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
