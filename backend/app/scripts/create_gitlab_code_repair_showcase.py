from __future__ import annotations

import argparse
import time
from typing import Any

import httpx
from sqlalchemy import desc, select

from app import models
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.integrations.gitlab import GitLabClient
from app.scripts.create_gitlab_showcase_projects import _client_from_env_or_oauth, _decoded_content
from app.services.fix_plans import FixPlanService
from app.services.gitlab_sync import GitLabProjectSyncService
from app.services.repo_context import RepoContextService


PROJECT_NAME = "panopticon-showcase-code-repair"
BRANCH_NAME = "main"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a real GitLab code-repair showcase project for Panopticon.")
    parser.add_argument("--no-sync", action="store_true", help="Create/update GitLab only; skip Panopticon sync and indexing.")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait briefly for the failed pipeline to appear.")
    parser.add_argument("--sync-only", action="store_true", help="Skip GitLab writes and only sync/index the existing showcase project.")
    parser.add_argument("--create-fix-plan", action="store_true", help="Create a draft source-code bug-fix plan after indexing.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        client, workspace_id = _client_from_env_or_oauth(db)
        namespace_path = _namespace_path(client)
        project_path = f"{namespace_path}/{PROJECT_NAME}"
        if not args.sync_only:
            project = _ensure_project(client, project_path)
            _commit_files(client, project_path)
            pipeline = _trigger_pipeline(client, project_path)
            print(f"project: {project_path}")
            print(f"url: {project.get('web_url') or f'https://gitlab.com/{project_path}'}")
            if pipeline:
                print(f"pipeline: {pipeline.get('web_url') or pipeline.get('id')} status={pipeline.get('status')}")
            if not args.no_wait:
                _wait_for_pipeline(client, project_path)
        if not args.no_sync:
            _sync_and_index(db, client, project_path, workspace_id, create_fix_plan=args.create_fix_plan)
    finally:
        db.close()


def _namespace_path(client: GitLabClient) -> str:
    settings = get_settings()
    configured = settings.gitlab_showcase_namespace_path.strip().strip("/")
    if configured:
        return configured
    user = client.current_user()
    username = str(user.get("username") or "").strip()
    if not username:
        raise RuntimeError("Could not resolve GitLab username. Set GITLAB_SHOWCASE_NAMESPACE_PATH in backend/.env.")
    return username


def _ensure_project(client: GitLabClient, project_path: str) -> dict[str, Any]:
    try:
        project = client.get_project(project_path)
        _enable_shared_runners(client, project_path)
        return project
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise

    settings = get_settings()
    project = client.create_project(
        name=PROJECT_NAME,
        path=PROJECT_NAME,
        description="Panopticon showcase project with a real source-code bug and failing CI test.",
        visibility=settings.gitlab_showcase_visibility,
        namespace_id=settings.gitlab_showcase_namespace_id,
    )
    _enable_shared_runners(client, str(project.get("path_with_namespace") or project_path))
    return project


def _enable_shared_runners(client: GitLabClient, project_path: str) -> None:
    try:
        client.update_project(project_path, {"shared_runners_enabled": True})
    except httpx.HTTPStatusError:
        return


def _commit_files(client: GitLabClient, project_path: str) -> None:
    actions = []
    for path, content in _files().items():
        current = _file(client, project_path, path)
        action = "update" if current else "create"
        if current and _decoded_content(current) == content:
            continue
        actions.append({"action": action, "file_path": path, "content": content})
    if not actions:
        print("files already up to date")
        return
    client.create_commit_live(project_path, BRANCH_NAME, "Seed real Panopticon code repair scenario", actions)
    print(f"committed {len(actions)} file(s)")


def _file(client: GitLabClient, project_path: str, path: str) -> dict[str, Any]:
    try:
        return client.get_repository_file(project_path, path, BRANCH_NAME)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {}
        raise


def _trigger_pipeline(client: GitLabClient, project_path: str) -> dict[str, Any]:
    try:
        return client.create_pipeline_live(project_path, BRANCH_NAME)
    except httpx.HTTPStatusError as exc:
        print(f"could not trigger pipeline: {exc.response.status_code} {exc.response.text[:300]}")
    return {}


def _wait_for_pipeline(client: GitLabClient, project_path: str) -> None:
    deadline = time.monotonic() + 90
    terminal = {"success", "failed", "canceled", "skipped", "manual"}
    while time.monotonic() < deadline:
        pipelines = client.list_pipelines(project_path, limit=5)
        if pipelines:
            status = str(pipelines[0].get("status") or "")
            print(f"latest pipeline status: {status}")
            if status in terminal:
                return
        time.sleep(8)
    print("pipeline wait timed out; syncing current GitLab state")


def _sync_and_index(db, client: GitLabClient, project_path: str, workspace_id: int | None, *, create_fix_plan: bool = False) -> None:
    run = GitLabProjectSyncService(db, client=client, workspace_id=workspace_id).sync(limit=100, merge_request_limit=20, pipeline_limit=20, job_limit=50)
    print(
        "synced from GitLab: "
        f"status={run.status}, projects={run.projects_updated}, mrs={run.merge_requests_seen}, "
        f"pipelines={run.pipelines_seen}, failed_jobs={run.jobs_seen}"
    )
    if run.error:
        print(f"sync errors: {run.error}")

    stmt = select(models.GitLabProject).where(models.GitLabProject.project_path == project_path).order_by(desc(models.GitLabProject.synced_at))
    project = db.scalar(stmt)
    if not project:
        print("index skipped: project was not returned by GitLab sync yet")
        return
    index_run = RepoContextService(db, client=client, workspace_id=workspace_id).index_project(project, limit=30)
    print(f"indexed repo context: status={index_run.status}, files={index_run.files_indexed}, skipped={index_run.files_skipped}")
    if create_fix_plan:
        _create_demo_fix_plan(db, project, workspace_id)
    _create_demo_fix_plan_hint(project.project_path)


def _create_demo_fix_plan(db, project: models.GitLabProject, workspace_id: int | None) -> None:
    problem = "Fix the failing discount coupon bug. SAVE10 should apply a 10 percent discount."
    existing = db.scalar(
        select(models.FixPlan)
        .where(models.FixPlan.project_id == project.id)
        .where(models.FixPlan.fix_type == "source_bug_fix")
        .where(models.FixPlan.summary == problem)
        .order_by(desc(models.FixPlan.created_at))
    )
    if existing:
        print(f"fix plan already exists: id={existing.id} status={existing.status}")
        return
    plan = FixPlanService(db, workspace_id=workspace_id).create(
        project_id=project.id,
        problem_statement=problem,
        fix_type="source_bug_fix",
    )
    print(f"created draft source bug-fix plan: id={plan.id}")


def _create_demo_fix_plan_hint(project_path: str) -> None:
    print("demo prompt:")
    print(f"  Create a source bug fix plan for {project_path}: SAVE10 should apply a 10 percent discount.")


def _files() -> dict[str, str]:
    return {
        ".gitlab-ci.yml": """stages:
  - test

workflow:
  rules:
    - when: always

unit-tests:
  image: python:3.12-slim
  stage: test
  script:
    - pip install -r requirements.txt
    - python -m pytest -q
""",
        "README.md": """# Panopticon Code Repair Showcase

This is a real GitLab project for testing Panopticon as a repository-aware coding assistant.

The project intentionally contains a source-code bug:

- `SAVE10` should apply a 10 percent discount.
- The current implementation subtracts a flat 10 currency units.
- CI runs `python -m pytest -q` and should fail until the source file is fixed.

Expected Panopticon behavior:

1. Sync this project from GitLab.
2. Index the repository files into Cloud SQL / pgvector-backed memory.
3. Let chat explain the failing behavior using repository context.
4. Generate a source bug fix plan that edits `services/discounts/discounts.py`.
5. Show a red/green diff before any GitLab write.
""",
        "requirements.txt": "pytest==8.4.1\n",
        "services/__init__.py": "",
        "services/discounts/__init__.py": "",
        "services/discounts/discounts.py": '''def apply_coupon(total, coupon):
    """Apply a coupon code to an order total."""
    if total < 0:
        raise ValueError("total cannot be negative")
    if coupon == "SAVE10":
        return total - 10
    if coupon in (None, "", "NONE"):
        return total
    raise ValueError(f"unsupported coupon: {coupon}")
''',
        "tests/test_discounts.py": '''import pytest

from services.discounts.discounts import apply_coupon


def test_save10_applies_ten_percent_discount():
    assert apply_coupon(100.0, "SAVE10") == 90.0
    assert apply_coupon(50.0, "SAVE10") == 45.0


def test_unknown_coupon_is_rejected():
    with pytest.raises(ValueError):
        apply_coupon(100.0, "BOGUS")


def test_negative_total_is_rejected():
    with pytest.raises(ValueError):
        apply_coupon(-1.0, "SAVE10")
''',
    }


if __name__ == "__main__":
    main()
