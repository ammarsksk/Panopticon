from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    web_url: str
    duration: float | None
    created_at_gitlab: datetime | None
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


class DashboardSummary(BaseModel):
    active_risks: int
    failed_pipelines: int
    blocked_merge_requests: int
    open_incidents: int
    latest_recommendations: list[RecommendationOut]
    slack_status: dict[str, Any]
