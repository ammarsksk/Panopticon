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


class DashboardSummary(BaseModel):
    active_risks: int
    failed_pipelines: int
    blocked_merge_requests: int
    open_incidents: int
    latest_recommendations: list[RecommendationOut]
    slack_status: dict[str, Any]
