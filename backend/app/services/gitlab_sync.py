from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.integrations.gitlab import GitLabClient


class GitLabProjectSyncService:
    def __init__(self, db: Session, client: GitLabClient | None = None, workspace_id: int | None = None) -> None:
        self.db = db
        self.client = client or GitLabClient()
        self.workspace_id = workspace_id

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
