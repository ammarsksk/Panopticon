from __future__ import annotations

import argparse
from dataclasses import replace

from app.config import get_settings
from app.database import SessionLocal
from app.scripts.create_gitlab_showcase_projects import _client_from_env_or_oauth, _slug, _wait_for_pipelines, ShowcaseResult
from app.scripts.seed_showcase import PROJECTS
from app.services.gitlab_sync import GitLabProjectSyncService
import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger real GitLab pipelines for existing Panopticon showcase projects.")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--fast-sync", action="store_true", help="Skip repository indexing during the immediate sync.")
    args = parser.parse_args()

    settings = get_settings()
    db = SessionLocal()
    try:
        client, workspace_id = _client_from_env_or_oauth(db)
        namespace_path = settings.gitlab_showcase_namespace_path.strip().strip("/") or str(client.current_user().get("username") or "").strip()
        if not namespace_path:
            raise RuntimeError("Could not resolve GitLab namespace path.")

        results = []
        prefix = _slug(settings.gitlab_showcase_project_prefix or "panopticon-showcase")
        for scenario in PROJECTS:
            project_slug = _slug(f"{prefix}-{scenario['name']}")
            project_path = f"{namespace_path}/{project_slug}"
            branch = f"panopticon/{_slug(str(scenario['branch']))}"
            try:
                pipeline = client.create_pipeline_live(project_path, branch)
                print(f"triggered: {project_path}:{branch} pipeline={pipeline.get('id')} status={pipeline.get('status')}", flush=True)
                project = client.get_project(project_path)
                results.append(
                    ShowcaseResult(
                        project_path=project_path,
                        web_url=str(project.get("web_url") or ""),
                        branch=branch,
                        merge_request_url="",
                        created=False,
                    )
                )
            except Exception as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    print(f"trigger failed: {project_path}:{branch}: {exc.response.status_code} {exc.response.text}", flush=True)
                else:
                    print(f"trigger failed: {project_path}:{branch}: {exc}", flush=True)

        if not args.no_wait and settings.gitlab_showcase_pipeline_wait_seconds > 0 and results:
            _wait_for_pipelines(client, results, timeout_seconds=settings.gitlab_showcase_pipeline_wait_seconds)

        if not args.no_sync:
            service = GitLabProjectSyncService(db, client=client, workspace_id=workspace_id)
            if args.fast_sync:
                service.settings = replace(service.settings, repo_index_on_sync=False)
            run = service.sync(limit=100, merge_request_limit=50, pipeline_limit=30, job_limit=50)
            print(
                "synced from GitLab: "
                f"status={run.status}, projects={run.projects_updated}, mrs={run.merge_requests_seen}, "
                f"pipelines={run.pipelines_seen}, failed_jobs={run.jobs_seen}",
                flush=True,
            )
            if run.error:
                print(f"sync errors: {run.error}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
