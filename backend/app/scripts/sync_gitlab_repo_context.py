from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app import models
from app.config import get_settings
from app.database import SessionLocal
from app.integrations.gitlab import GitLabClient
from app.services.auth import AuthService
from app.services.gitlab_sync import GitLabProjectSyncService


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync GitLab projects, pipelines, and repository context into the active database.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--merge-request-limit", type=int, default=20)
    parser.add_argument("--pipeline-limit", type=int, default=10)
    parser.add_argument("--job-limit", type=int, default=20)
    args = parser.parse_args()

    settings = get_settings()
    with SessionLocal() as db:
        context = AuthService(db).agent_runtime_context()
        client = GitLabClient()
        if not client.configured:
            raise SystemExit("GitLab is not connected. Set GITLAB_TOKEN or connect GitLab OAuth first.")

        run = GitLabProjectSyncService(db, client=client, workspace_id=context.workspace.id).sync(
            limit=max(1, args.limit),
            merge_request_limit=max(1, args.merge_request_limit),
            pipeline_limit=max(1, args.pipeline_limit),
            job_limit=max(1, args.job_limit),
        )

        projects = db.scalar(select(func.count(models.GitLabProject.id)).where(models.GitLabProject.workspace_id == context.workspace.id)) or 0
        files = db.scalar(select(func.count(models.RepoFileIndex.id)).where(models.RepoFileIndex.workspace_id == context.workspace.id)) or 0
        chunks = db.scalar(select(func.count(models.RepoCodeChunk.id)).where(models.RepoCodeChunk.workspace_id == context.workspace.id)) or 0
        symbols = db.scalar(select(func.count(models.RepoSymbolIndex.id)).where(models.RepoSymbolIndex.workspace_id == context.workspace.id)) or 0
        pipelines = db.scalar(select(func.count(models.PipelineSnapshot.id)).where(models.PipelineSnapshot.workspace_id == context.workspace.id)) or 0
        jobs = db.scalar(select(func.count(models.JobSnapshot.id)).where(models.JobSnapshot.workspace_id == context.workspace.id)) or 0

        embedding_rows = db.execute(
            select(models.RepoCodeChunk.embedding_provider, models.RepoCodeChunk.embedding_status, func.count(models.RepoCodeChunk.id))
            .where(models.RepoCodeChunk.workspace_id == context.workspace.id)
            .group_by(models.RepoCodeChunk.embedding_provider, models.RepoCodeChunk.embedding_status)
            .order_by(models.RepoCodeChunk.embedding_provider, models.RepoCodeChunk.embedding_status)
        ).all()

        print("GitLab production sync")
        print("======================")
        print(f"workspace={context.workspace.slug} ({context.workspace.id})")
        print(f"repo_index_on_sync={settings.repo_index_on_sync}")
        print(f"embedding_provider={settings.repo_embedding_provider}")
        print(f"embedding_model={settings.repo_embedding_model}")
        print(f"pgvector_enabled={settings.repo_pgvector_enabled}")
        print(f"sync_status={run.status}")
        print(f"projects_seen={run.projects_seen}")
        print(f"projects_updated={run.projects_updated}")
        print(f"merge_requests_seen={run.merge_requests_seen}")
        print(f"pipelines_seen={run.pipelines_seen}")
        print(f"jobs_seen={run.jobs_seen}")
        if run.error:
            print("sync_errors:")
            print(run.error)
        print()
        print("Cloud SQL workspace totals")
        print("--------------------------")
        print(f"projects={projects}")
        print(f"repo_files={files}")
        print(f"repo_chunks={chunks}")
        print(f"repo_symbols={symbols}")
        print(f"pipelines={pipelines}")
        print(f"failed_jobs={jobs}")
        if embedding_rows:
            print()
            print("Embedding status")
            print("----------------")
            for provider, status, count in embedding_rows:
                print(f"{count:6} {provider or 'unknown':18} {status or 'unknown'}")


if __name__ == "__main__":
    main()
