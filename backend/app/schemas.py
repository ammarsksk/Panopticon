from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkspaceOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthRequestIn(BaseModel):
    email: str
    password: str
    name: str = ""
    workspace_name: str = ""


class AuthSessionOut(BaseModel):
    user: UserOut
    workspace: WorkspaceOut
    role: str
    auth_required: bool = False


class OAuthIntegrationStatusOut(BaseModel):
    provider: str
    configured: bool
    connected: bool
    account_label: str = ""
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    base_url: str = ""


class OperationalEventOut(BaseModel):
    id: int
    provider: str
    event_type: str
    project_path: str
    title: str
    severity: str
    payload: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RiskAssessmentOut(BaseModel):
    id: int
    project_path: str
    merge_request_iid: str
    deployment_ref: str
    score: float
    level: str
    summary: str
    reasons: list[str]
    recommendations: list[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GitLabProjectOut(BaseModel):
    id: int
    gitlab_project_id: str
    project_path: str
    name: str
    namespace: str
    web_url: str
    default_branch: str
    visibility: str
    description: str
    last_activity_at: datetime | None
    open_merge_requests_count: int
    failed_pipelines_count: int
    latest_pipeline_id: str
    latest_pipeline_status: str
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectSyncRunOut(BaseModel):
    id: int
    provider: str
    status: str
    projects_seen: int
    projects_updated: int
    merge_requests_seen: int
    pipelines_seen: int
    jobs_seen: int
    error: str
    started_at: datetime
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RepoIndexRunOut(BaseModel):
    id: int
    project_id: int | None
    project_path: str
    ref: str
    status: str
    files_seen: int
    files_indexed: int
    files_skipped: int
    error: str
    started_at: datetime
    finished_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class RepoFileIndexOut(BaseModel):
    id: int
    project_id: int | None
    project_path: str
    file_path: str
    ref: str
    file_type: str
    language: str
    size_bytes: int
    content_sha: str
    last_commit_id: str
    content_excerpt: str
    signals: dict[str, Any]
    indexed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RepoContextSummaryOut(BaseModel):
    indexed_files: int
    by_type: dict[str, int]
    by_language: dict[str, int]
    latest_run: RepoIndexRunOut | None
    priority_files: list[RepoFileIndexOut]


class MergeRequestSnapshotOut(BaseModel):
    id: int
    gitlab_project_id: str
    project_path: str
    merge_request_iid: str
    title: str
    state: str
    web_url: str
    author_username: str
    source_branch: str
    target_branch: str
    draft: bool
    created_at_gitlab: datetime | None
    updated_at_gitlab: datetime | None
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineSnapshotOut(BaseModel):
    id: int
    gitlab_project_id: str
    project_path: str
    pipeline_id: str
    status: str
    ref: str
    sha: str
    web_url: str
    created_at_gitlab: datetime | None
    updated_at_gitlab: datetime | None
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobSnapshotOut(BaseModel):
    id: int
    gitlab_project_id: str
    project_path: str
    pipeline_id: str
    job_id: str
    name: str
    stage: str
    status: str
    failure_reason: str
    failure_signature: str = ""
    trace_summary: str = ""
    trace_excerpt: str = ""
    web_url: str
    duration: float | None
    created_at_gitlab: datetime | None
    trace_fetched_at: datetime | None = None
    synced_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PipelineInsightOut(BaseModel):
    id: int
    project_path: str
    pipeline_id: str
    status: str
    likely_cause: str
    evidence: list[str]
    recommendations: list[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MergeRequestSignalOut(BaseModel):
    id: int
    project_path: str
    merge_request_iid: str
    title: str
    state: str
    age_hours: float
    unresolved_threads: int
    reviewer_count: int
    bottleneck_level: str
    summary: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentRecordOut(BaseModel):
    id: int
    project_path: str
    title: str
    severity: str
    probable_root_cause: str
    timeline: list[dict[str, Any]]
    recommendations: list[str]
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ObservabilityEventIn(BaseModel):
    provider: str = "generic"
    event_uid: str = ""
    project_path: str = ""
    service_name: str = ""
    environment: str = ""
    severity: str = "info"
    signal_type: str = "alert"
    title: str = ""
    message: str = ""
    metric_name: str = ""
    trace_id: str = ""
    alert_url: str = ""
    observed_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ObservabilityEventOut(BaseModel):
    id: int
    provider: str
    event_uid: str
    project_path: str
    service_name: str
    environment: str
    severity: str
    signal_type: str
    title: str
    message: str
    metric_name: str
    trace_id: str
    alert_url: str
    payload: dict[str, Any]
    observed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IncidentCorrelationOut(BaseModel):
    id: int
    project_path: str
    title: str
    severity: str
    status: str
    summary: str
    suspected_cause: str
    confidence: float
    timeline: list[dict[str, Any]]
    related_observability_event_ids: list[int]
    related_pipeline_ids: list[str]
    related_risk_ids: list[int]
    related_incident_ids: list[int]
    recommendations: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ObservabilityIngestOut(BaseModel):
    event: ObservabilityEventOut
    correlation: IncidentCorrelationOut | None
    deduplicated: bool = False


class ProjectHealthOut(BaseModel):
    project_id: int
    project_path: str
    name: str
    namespace: str
    health_score: float
    health_level: str
    failed_pipeline_rate: float
    pipeline_count: int
    failed_pipeline_count: int
    open_merge_requests: int
    active_risks: int
    max_risk_score: float
    open_incidents: int
    observability_alerts: int
    pending_actions: int
    completed_actions: int
    fix_plans: int
    recommendation_count: int
    last_activity_at: datetime | None
    top_reasons: list[str]


class MetricsSummaryOut(BaseModel):
    generated_at: datetime
    project_count: int
    average_health_score: float
    health_level: str
    failed_pipeline_rate: float
    total_pipelines: int
    failed_pipelines: int
    active_risks: int
    open_incidents: int
    observability_alerts: int
    pending_actions: int
    completed_actions: int
    fix_plans: int
    projects_at_risk: int
    healthiest_projects: list[ProjectHealthOut]
    riskiest_projects: list[ProjectHealthOut]


class EngineeringMetricSnapshotOut(BaseModel):
    id: int
    scope_type: str
    project_path: str
    snapshot_date: date
    health_score: float
    metrics: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RecommendationOut(BaseModel):
    id: int
    project_path: str
    source_type: str
    source_id: str
    channel: str
    message: str
    title: str = ""
    summary: str = ""
    gemini_analysis: str = ""
    evidence: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    origin: str = "gitlab"
    severity: str = "info"
    confidence: float = 0.0
    action_type: str = "dashboard_note"
    can_execute: bool = False
    requires_approval: bool = False
    approval_state: str = "not_required"
    rank_score: float = 0.0
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GroundedRecommendationCreateIn(BaseModel):
    question: str = ""
    intent: str = "summary"
    persist: bool = False
    channel: str = "dashboard"


class GroundedRecommendationOut(BaseModel):
    project_path: str
    issue_type: str
    severity: str
    confidence: float
    grounded: bool
    validation_errors: list[str]
    summary: str
    recommendation: str
    evidence: list[dict[str, Any]]
    next_actions: list[str]
    proposed_action: dict[str, Any]
    saved_recommendation: RecommendationOut | None = None


class ActionDispatchOut(BaseModel):
    id: int
    recommendation_id: int | None
    channel: str
    status: str
    target: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    error: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentActionOut(BaseModel):
    id: int
    recommendation_id: int | None
    project_path: str
    action_type: str
    channel: str
    title: str
    summary: str
    status: str
    requires_approval: bool
    payload_preview: dict[str, Any]
    execution_context: dict[str, Any]
    last_result: dict[str, Any]
    error: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionApprovalOut(BaseModel):
    id: int
    agent_action_id: int
    decision: str
    actor: str
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionDecisionIn(BaseModel):
    actor: str = "local_user"
    reason: str = ""


class AgentActionDetailOut(BaseModel):
    action: AgentActionOut
    approvals: list[ActionApprovalOut]
    dispatches: list[ActionDispatchOut]


class FixPlanCreateIn(BaseModel):
    project_id: int | None = None
    project_path: str = ""
    source_type: str = ""
    source_id: str = ""
    problem_statement: str = ""
    fix_type: str = ""


class FixPlanOut(BaseModel):
    id: int
    project_id: int | None
    project_path: str
    source_type: str
    source_id: str
    title: str
    summary: str
    status: str
    requires_approval: bool
    fix_type: str
    base_branch: str
    branch_name: str
    merge_request_iid: str
    merge_request_url: str
    plan_payload: dict[str, Any]
    last_result: dict[str, Any]
    error: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FixPlanApprovalOut(BaseModel):
    id: int
    fix_plan_id: int
    decision: str
    actor: str
    reason: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FixPlanDecisionIn(BaseModel):
    actor: str = "local_user"
    reason: str = ""


class FixPlanDetailOut(BaseModel):
    plan: FixPlanOut
    approvals: list[FixPlanApprovalOut]


class ChatThreadOut(BaseModel):
    id: int
    project_id: int | None
    project_path: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageOut(BaseModel):
    id: int
    thread_id: int
    role: str
    content: str
    citations: list[dict[str, Any]]
    prepared_action_ids: list[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequestIn(BaseModel):
    message: str
    project_id: int | None = None
    thread_id: int | None = None


class ChatResponseOut(BaseModel):
    thread: ChatThreadOut
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut
    prepared_actions: list[AgentActionOut]
    prepared_fix_plans: list[FixPlanOut] = Field(default_factory=list)


class MemoryRecordOut(BaseModel):
    id: int
    project_path: str
    memory_type: str
    signature: str
    summary: str
    evidence: list[str]
    remediation: list[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectSummaryOut(BaseModel):
    project: GitLabProjectOut
    open_merge_requests: list[MergeRequestSnapshotOut]
    latest_pipelines: list[PipelineSnapshotOut]
    failed_jobs: list[JobSnapshotOut]
    active_risks: list[RiskAssessmentOut]
    recent_incidents: list[IncidentRecordOut]
    latest_recommendations: list[RecommendationOut]
    recent_actions: list[ActionDispatchOut]
    memory_records: list[MemoryRecordOut]
    repo_files: list[RepoFileIndexOut] = Field(default_factory=list)
    latest_repo_index_run: RepoIndexRunOut | None = None
    repo_context_summary: RepoContextSummaryOut | None = None


class DashboardSummary(BaseModel):
    active_risks: int
    failed_pipelines: int
    blocked_merge_requests: int
    open_incidents: int
    synced_projects: int = 0
    latest_project_sync: ProjectSyncRunOut | None = None
    latest_recommendations: list[RecommendationOut]
    slack_status: dict[str, Any]
    gitlab_status: OAuthIntegrationStatusOut
