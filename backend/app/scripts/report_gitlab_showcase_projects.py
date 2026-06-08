from __future__ import annotations

import argparse
import base64

from app.database import SessionLocal
from app.scripts.create_gitlab_showcase_projects import _client_from_env_or_oauth


def main() -> None:
    parser = argparse.ArgumentParser(description="Report real GitLab showcase project pipeline status.")
    parser.add_argument("--project", default="", help="Only report one project path.")
    parser.add_argument("--pipeline-limit", type=int, default=5)
    parser.add_argument("--show-ci", action="store_true", help="Print .gitlab-ci.yml from the default branch.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        client, _workspace_id = _client_from_env_or_oauth(db)
        projects = [
            project
            for project in client.list_projects(limit=100)
            if "panopticon-showcase" in str(project.get("path_with_namespace") or "")
        ]
        if args.project:
            projects = [project for project in projects if str(project.get("path_with_namespace") or "") == args.project]
        print(f"showcase_projects={len(projects)}")
        for project in projects:
            project_path = str(project.get("path_with_namespace") or "")
            print(f"\n{project_path}")
            if args.show_ci:
                ci_file = client.get_repository_file(project_path, ".gitlab-ci.yml", str(project.get("default_branch") or "main"))
                content = base64.b64decode(str(ci_file.get("content") or "").encode("ascii")).decode("utf-8")
                print("  .gitlab-ci.yml:")
                for line in content.splitlines():
                    print(f"    {line}")
            pipelines = client.list_pipelines(project_path, limit=args.pipeline_limit)
            for pipeline in pipelines:
                pipeline_id = str(pipeline.get("id") or "")
                detail = client.get_pipeline(project_path, pipeline_id)
                yaml_errors = detail.get("yaml_errors") or ""
                detailed_status = detail.get("detailed_status") or {}
                label = detailed_status.get("label") or detailed_status.get("text") or ""
                suffix = f" yaml_errors={yaml_errors}" if yaml_errors else ""
                status_label = f" label={label}" if label else ""
                print(f"  pipeline={pipeline_id} ref={pipeline.get('ref')} status={pipeline.get('status')}{status_label}{suffix}")
                jobs = client.get_pipeline_jobs(project_path, pipeline_id)
                for job in jobs:
                    print(f"    job={job.get('name')} status={job.get('status')} reason={job.get('failure_reason') or ''}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
