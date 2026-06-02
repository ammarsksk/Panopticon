from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.config import get_settings
from app.integrations.gitlab import GitLabClient
from app.memory.repository import OperationalMemory
from app.services.repo_context import RepoContextService


class GitLabProjectSyncService:
    def __init__(self, db: Session, client: GitLabClient | None = None, workspace_id: int | None = None) -> None:
        self.db = db
        self.client = client or GitLabClient()
        self.workspace_id = workspace_id
        self.settings = get_settings()

    def sync(self, *, limit: int = 50, merge_request_limit: int = 20, pipeline_limit: int = 10, job_limit: int = 20) -> models.ProjectSyncRun:
        run = models.ProjectSyncRun(status="running", workspace_id=self.workspace_id)
        self.db.add(run)
        self.db.flush()

        try:
            if not self.client.configured:
                raise RuntimeError("GitLab is not connected. Configure GitLab OAuth or GITLAB_TOKEN.")

            projects = self.client.list_projects(limit=limit)
            run.projects_seen = len(projects)

            errors: list[str] = []
            for item in projects:
                project = self._upsert_project(item)
                project_path = project.project_path
                run.projects_updated += 1

                try:
                    merge_requests = self.client.list_open_merge_requests(project_path, limit=merge_request_limit)
                    pipelines = self.client.list_pipelines(project_path, limit=pipeline_limit)
                    failed_jobs = 0

                    run.merge_requests_seen += len(merge_requests)
                    run.pipelines_seen += len(pipelines)

                    for merge_request in merge_requests:
                        self._upsert_merge_request(project, merge_request)

                    for pipeline in pipelines:
                        snapshot = self._upsert_pipeline(project, pipeline)
                        if snapshot.status == "failed":
                            jobs = self.client.get_pipeline_jobs(project_path, snapshot.pipeline_id)
                            failed = [job for job in jobs if job.get("status") == "failed"][:job_limit]
                            failed_jobs += len(failed)
                            run.jobs_seen += len(failed)
                            for job in failed:
                                self._upsert_job(project, snapshot, job)

                    project.open_merge_requests_count = len(merge_requests)
                    project.failed_pipelines_count = len([pipeline for pipeline in pipelines if pipeline.get("status") == "failed"])
                    latest_pipeline = pipelines[0] if pipelines else {}
                    project.latest_pipeline_id = str(latest_pipeline.get("id") or "")
                    project.latest_pipeline_status = str(latest_pipeline.get("status") or "")
                    self._refresh_dashboard_intelligence(project=project, merge_requests=merge_requests, pipelines=pipelines)
                    if self.settings.repo_index_on_sync:
                        RepoContextService(self.db, client=self.client, workspace_id=self.workspace_id).index_project(
                            project,
                            limit=self.settings.repo_index_file_limit,
                        )
                except Exception as exc:
                    errors.append(f"{project_path}: {exc}")
                finally:
                    project.synced_at = _now()

            run.status = "completed_with_errors" if errors else "completed"
            run.error = "\n".join(errors)[:4000]
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
        finally:
            run.finished_at = _now()
            self.db.commit()

        return run

    def _upsert_project(self, item: dict) -> models.GitLabProject:
        gitlab_project_id = str(item.get("id") or "")
        project_path = str(item.get("path_with_namespace") or "")
        stmt = select(models.GitLabProject).where(models.GitLabProject.gitlab_project_id == gitlab_project_id)
        if self.workspace_id is not None:
            stmt = stmt.where(models.GitLabProject.workspace_id == self.workspace_id)
        project = self.db.scalar(stmt)
        if not project:
            stmt = select(models.GitLabProject).where(models.GitLabProject.project_path == project_path)
            if self.workspace_id is not None:
                stmt = stmt.where(models.GitLabProject.workspace_id == self.workspace_id)
            project = self.db.scalar(stmt)
        if not project:
            project = models.GitLabProject(gitlab_project_id=gitlab_project_id, project_path=project_path, workspace_id=self.workspace_id)
            self.db.add(project)

        project.workspace_id = self.workspace_id
        namespace = item.get("namespace") or {}
        project.gitlab_project_id = gitlab_project_id
        project.project_path = project_path
        project.name = str(item.get("name") or item.get("path") or project_path)
        project.namespace = str(namespace.get("full_path") or namespace.get("name") or "")
        project.web_url = str(item.get("web_url") or "")
        project.default_branch = str(item.get("default_branch") or "")
        project.visibility = str(item.get("visibility") or "")
        project.description = str(item.get("description") or "")
        project.last_activity_at = _parse_gitlab_datetime(item.get("last_activity_at"))
        self.db.flush()
        return project

    def _upsert_merge_request(self, project: models.GitLabProject, item: dict) -> models.MergeRequestSnapshot:
        merge_request_iid = str(item.get("iid") or item.get("id") or "")
        snapshot = self.db.scalar(
            select(models.MergeRequestSnapshot)
            .where(models.MergeRequestSnapshot.gitlab_project_id == project.gitlab_project_id)
            .where(models.MergeRequestSnapshot.merge_request_iid == merge_request_iid)
            .where(models.MergeRequestSnapshot.workspace_id == project.workspace_id)
        )
        if not snapshot:
            snapshot = models.MergeRequestSnapshot(
                gitlab_project_id=project.gitlab_project_id,
                project_path=project.project_path,
                merge_request_iid=merge_request_iid,
                workspace_id=project.workspace_id,
            )
            self.db.add(snapshot)

        snapshot.workspace_id = project.workspace_id
        author = item.get("author") or {}
        snapshot.project_path = project.project_path
        snapshot.title = str(item.get("title") or "")
        snapshot.state = str(item.get("state") or "")
        snapshot.web_url = str(item.get("web_url") or "")
        snapshot.author_username = str(author.get("username") or "")
        snapshot.source_branch = str(item.get("source_branch") or "")
        snapshot.target_branch = str(item.get("target_branch") or "")
        snapshot.draft = bool(item.get("draft") or item.get("work_in_progress"))
        snapshot.created_at_gitlab = _parse_gitlab_datetime(item.get("created_at"))
        snapshot.updated_at_gitlab = _parse_gitlab_datetime(item.get("updated_at"))
        snapshot.synced_at = _now()
        self.db.flush()
        return snapshot

    def _refresh_dashboard_intelligence(self, *, project: models.GitLabProject, merge_requests: list[dict], pipelines: list[dict]) -> None:
        memory = OperationalMemory(self.db, workspace_id=self.workspace_id)
        failed_pipelines = [pipeline for pipeline in pipelines if pipeline.get("status") == "failed"]

        for pipeline in failed_pipelines[:5]:
            pipeline_id = str(pipeline.get("id") or "")
            if not pipeline_id or self._pipeline_insight_exists(project.project_path, pipeline_id):
                continue
            insight = memory.add_pipeline_insight(
                event_id=None,
                project_path=project.project_path,
                pipeline_id=pipeline_id,
                status="failed",
                likely_cause=_pipeline_likely_cause(pipeline),
                evidence=_pipeline_evidence(pipeline),
                recommendations=[
                    "Open the failed pipeline and inspect failed jobs or logs.",
                    "Check recent merge request changes on the same branch.",
                    "Retry only after confirming the failure is not deterministic.",
                ],
            )
            memory.add_recommendation(
                project_path=project.project_path,
                source_type="pipeline",
                source_id=str(insight.id),
                channel="slack",
                status="pending",
                message=(
                    f"Pipeline failure detected for {project.project_path}: {insight.likely_cause}\n\n"
                    "Next action: inspect failed jobs, compare the latest merge request changes, and confirm whether a retry is safe."
                ),
            )

        for merge_request in merge_requests[:10]:
            merge_request_iid = str(merge_request.get("iid") or merge_request.get("id") or "")
            if not merge_request_iid:
                continue
            if not self._mr_signal_exists(project.project_path, merge_request_iid):
                signal = memory.add_mr_signal(
                    project_path=project.project_path,
                    merge_request_iid=merge_request_iid,
                    title=str(merge_request.get("title") or "Open merge request"),
                    state=str(merge_request.get("state") or "opened"),
                    age_hours=_hours_since(merge_request.get("created_at")),
                    unresolved_threads=int(merge_request.get("unresolved_discussions_count") or 0),
                    reviewer_count=len(merge_request.get("reviewers") or []),
                    bottleneck_level="blocked" if failed_pipelines else "review",
                    summary=_mr_summary(project, merge_request, failed_pipelines),
                )
                if signal.bottleneck_level == "blocked":
                    memory.add_recommendation(
                        project_path=project.project_path,
                        source_type="merge_request",
                        source_id=str(signal.id),
                        channel="dashboard",
                        status="pending",
                        message=f"Merge request !{merge_request_iid} is blocked by failed pipeline activity. Review pipeline evidence before merging.",
                    )

            if not self._risk_exists(project.project_path, merge_request_iid):
                score = 78 if failed_pipelines else 55
                level = "high" if score >= 70 else "medium"
                risk = memory.add_risk(
                    event_id=None,
                    project_path=project.project_path,
                    merge_request_iid=merge_request_iid,
                    deployment_ref=str(merge_request.get("source_branch") or ""),
                    score=score,
                    level=level,
                    summary=_risk_summary(project, merge_request, failed_pipelines),
                    reasons=_risk_reasons(project, merge_request, failed_pipelines),
                    recommendations=[
                        "Review the merge request alongside the latest pipeline result.",
                        "Require owner review before merging if the failed pipeline is related to this branch.",
                        "Add or confirm automated coverage for the touched service path.",
                    ],
                )
                if score >= 70:
                    memory.add_recommendation(
                        project_path=project.project_path,
                        source_type="risk",
                        source_id=str(risk.id),
                        channel="gitlab_comment",
                        status="pending",
                        message=f"{risk.summary} {' '.join(risk.recommendations)}",
                    )

    def _pipeline_insight_exists(self, project_path: str, pipeline_id: str) -> bool:
        stmt = select(models.PipelineInsight).where(models.PipelineInsight.project_path == project_path).where(models.PipelineInsight.pipeline_id == pipeline_id)
        if self.workspace_id is not None:
            stmt = stmt.where(models.PipelineInsight.workspace_id == self.workspace_id)
        return self.db.scalar(stmt) is not None

    def _mr_signal_exists(self, project_path: str, merge_request_iid: str) -> bool:
        stmt = select(models.MergeRequestSignal).where(models.MergeRequestSignal.project_path == project_path).where(models.MergeRequestSignal.merge_request_iid == merge_request_iid)
        if self.workspace_id is not None:
            stmt = stmt.where(models.MergeRequestSignal.workspace_id == self.workspace_id)
        return self.db.scalar(stmt.order_by(desc(models.MergeRequestSignal.created_at)).limit(1)) is not None

    def _risk_exists(self, project_path: str, merge_request_iid: str) -> bool:
        stmt = select(models.RiskAssessment).where(models.RiskAssessment.project_path == project_path).where(models.RiskAssessment.merge_request_iid == merge_request_iid)
        if self.workspace_id is not None:
            stmt = stmt.where(models.RiskAssessment.workspace_id == self.workspace_id)
        return self.db.scalar(stmt.order_by(desc(models.RiskAssessment.created_at)).limit(1)) is not None

    def _upsert_pipeline(self, project: models.GitLabProject, item: dict) -> models.PipelineSnapshot:
        pipeline_id = str(item.get("id") or "")
        snapshot = self.db.scalar(
            select(models.PipelineSnapshot)
            .where(models.PipelineSnapshot.gitlab_project_id == project.gitlab_project_id)
            .where(models.PipelineSnapshot.pipeline_id == pipeline_id)
            .where(models.PipelineSnapshot.workspace_id == project.workspace_id)
        )
        if not snapshot:
            snapshot = models.PipelineSnapshot(
                gitlab_project_id=project.gitlab_project_id,
                project_path=project.project_path,
                pipeline_id=pipeline_id,
                workspace_id=project.workspace_id,
            )
            self.db.add(snapshot)

        snapshot.workspace_id = project.workspace_id
        snapshot.project_path = project.project_path
        snapshot.status = str(item.get("status") or "")
        snapshot.ref = str(item.get("ref") or "")
        snapshot.sha = str(item.get("sha") or "")
        snapshot.web_url = str(item.get("web_url") or "")
        snapshot.created_at_gitlab = _parse_gitlab_datetime(item.get("created_at"))
        snapshot.updated_at_gitlab = _parse_gitlab_datetime(item.get("updated_at"))
        snapshot.synced_at = _now()
        self.db.flush()
        return snapshot

    def _upsert_job(self, project: models.GitLabProject, pipeline: models.PipelineSnapshot, item: dict) -> models.JobSnapshot:
        job_id = str(item.get("id") or "")
        snapshot = self.db.scalar(
            select(models.JobSnapshot)
            .where(models.JobSnapshot.gitlab_project_id == project.gitlab_project_id)
            .where(models.JobSnapshot.job_id == job_id)
            .where(models.JobSnapshot.workspace_id == project.workspace_id)
        )
        if not snapshot:
            snapshot = models.JobSnapshot(
                gitlab_project_id=project.gitlab_project_id,
                project_path=project.project_path,
                pipeline_id=pipeline.pipeline_id,
                job_id=job_id,
                workspace_id=project.workspace_id,
            )
            self.db.add(snapshot)

        snapshot.workspace_id = project.workspace_id
        snapshot.project_path = project.project_path
        snapshot.pipeline_id = pipeline.pipeline_id
        snapshot.name = str(item.get("name") or "")
        snapshot.stage = str(item.get("stage") or "")
        snapshot.status = str(item.get("status") or "")
        snapshot.failure_reason = str(item.get("failure_reason") or "")
        snapshot.web_url = str(item.get("web_url") or "")
        snapshot.duration = item.get("duration")
        snapshot.created_at_gitlab = _parse_gitlab_datetime(item.get("created_at"))
        snapshot.synced_at = _now()
        self.db.flush()
        return snapshot


def _parse_gitlab_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hours_since(value: str | None) -> float:
    parsed = _parse_gitlab_datetime(value)
    if not parsed:
        return 0.0
    return max(0.0, (_now() - parsed).total_seconds() / 3600)


def _pipeline_likely_cause(pipeline: dict) -> str:
    pipeline_id = str(pipeline.get("id") or "")
    ref = str(pipeline.get("ref") or "unknown ref")
    return f"GitLab reported pipeline #{pipeline_id} failed on {ref}. No failed job trace has been classified yet."


def _pipeline_evidence(pipeline: dict) -> list[str]:
    evidence = [f"Pipeline status: {pipeline.get('status') or 'unknown'}"]
    if pipeline.get("ref"):
        evidence.append(f"Ref: {pipeline['ref']}")
    if pipeline.get("sha"):
        evidence.append(f"Commit SHA: {pipeline['sha']}")
    if pipeline.get("web_url"):
        evidence.append(f"Pipeline URL: {pipeline['web_url']}")
    return evidence


def _mr_summary(project: models.GitLabProject, merge_request: dict, failed_pipelines: list[dict]) -> str:
    title = str(merge_request.get("title") or "Open merge request")
    if failed_pipelines:
        return f"!{merge_request.get('iid') or merge_request.get('id')} {title} needs review because {project.project_path} has recent failed pipeline activity."
    return f"!{merge_request.get('iid') or merge_request.get('id')} {title} is open and awaiting review."


def _risk_summary(project: models.GitLabProject, merge_request: dict, failed_pipelines: list[dict]) -> str:
    title = str(merge_request.get("title") or "Open merge request")
    if failed_pipelines:
        return f"Delivery risk is high for {project.project_path}!{merge_request.get('iid') or merge_request.get('id')} because recent pipeline activity failed while the merge request is open."
    return f"Delivery risk is medium for {project.project_path}!{merge_request.get('iid') or merge_request.get('id')} because an open merge request may affect delivery flow."


def _risk_reasons(project: models.GitLabProject, merge_request: dict, failed_pipelines: list[dict]) -> list[str]:
    reasons = [
        f"Open merge request: !{merge_request.get('iid') or merge_request.get('id')} {merge_request.get('title') or ''}".strip(),
        f"Source branch: {merge_request.get('source_branch') or 'unknown'}",
    ]
    if failed_pipelines:
        reasons.append(f"{len(failed_pipelines)} recent failed pipeline(s) are present for {project.project_path}.")
    if project.default_branch:
        reasons.append(f"Default branch: {project.default_branch}")
    return reasons
