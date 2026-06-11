from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class LargeShowcase:
    slug: str
    description: str
    fix_type: str
    problem: str
    files: dict[str, str]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create large GitLab projects for Panopticon multi-file code-repair testing.")
    parser.add_argument("--no-sync", action="store_true", help="Create/update GitLab only; skip Panopticon sync and indexing.")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait briefly for failed pipelines.")
    parser.add_argument("--sync-only", action="store_true", help="Skip GitLab writes and only sync/index existing projects.")
    parser.add_argument("--create-fix-plans", action="store_true", help="Create draft fix plans for the showcase projects.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        client, workspace_id = _client_from_env_or_oauth(db)
        namespace_path = _namespace_path(client)
        for showcase in _showcases():
            project_path = f"{namespace_path}/{showcase.slug}"
            if not args.sync_only:
                project = _ensure_project(client, project_path, showcase)
                _commit_files(client, project_path, showcase.files)
                pipeline = _trigger_pipeline(client, project_path)
                print(f"project: {project_path}", flush=True)
                print(f"url: {project.get('web_url') or f'https://gitlab.com/{project_path}'}", flush=True)
                if pipeline:
                    print(f"pipeline: {pipeline.get('web_url') or pipeline.get('id')} status={pipeline.get('status')}", flush=True)
                if not args.no_wait:
                    _wait_for_pipeline(client, project_path)
        if not args.no_sync:
            _sync_index_and_plan(db, client, namespace_path, workspace_id, create_fix_plans=args.create_fix_plans)
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


def _ensure_project(client: GitLabClient, project_path: str, showcase: LargeShowcase) -> dict[str, Any]:
    try:
        project = client.get_project(project_path)
        _enable_shared_runners(client, project_path)
        return project
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            raise

    settings = get_settings()
    project = client.create_project(
        name=showcase.slug,
        path=showcase.slug,
        description=showcase.description,
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


def _commit_files(client: GitLabClient, project_path: str, files: dict[str, str]) -> None:
    actions = []
    for path, content in files.items():
        current = _file(client, project_path, path)
        if current and _decoded_content(current) == content:
            continue
        actions.append({"action": "update" if current else "create", "file_path": path, "content": content})
    if not actions:
        print(f"files already up to date: {project_path}", flush=True)
        return
    client.create_commit_live(project_path, "main", "Seed large Panopticon code repair showcase", actions)
    print(f"committed {len(actions)} file(s) to {project_path}", flush=True)


def _file(client: GitLabClient, project_path: str, path: str) -> dict[str, Any]:
    try:
        return client.get_repository_file(project_path, path, "main")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {}
        raise


def _trigger_pipeline(client: GitLabClient, project_path: str) -> dict[str, Any]:
    try:
        return client.create_pipeline_live(project_path, "main")
    except httpx.HTTPStatusError as exc:
        print(f"could not trigger pipeline for {project_path}: {exc.response.status_code} {exc.response.text[:300]}", flush=True)
    return {}


def _wait_for_pipeline(client: GitLabClient, project_path: str) -> None:
    deadline = time.monotonic() + 120
    terminal = {"success", "failed", "canceled", "skipped", "manual"}
    while time.monotonic() < deadline:
        pipelines = client.list_pipelines(project_path, limit=3)
        if pipelines:
            status = str(pipelines[0].get("status") or "")
            print(f"{project_path} latest pipeline status: {status}", flush=True)
            if status in terminal:
                return
        time.sleep(8)
    print(f"pipeline wait timed out for {project_path}; syncing current state", flush=True)


def _sync_index_and_plan(db, client: GitLabClient, namespace_path: str, workspace_id: int | None, *, create_fix_plans: bool) -> None:
    print("syncing GitLab project metadata...", flush=True)
    run = GitLabProjectSyncService(db, client=client, workspace_id=workspace_id).sync(limit=40, merge_request_limit=15, pipeline_limit=10, job_limit=20)
    print(
        "synced from GitLab: "
        f"status={run.status}, projects={run.projects_updated}, mrs={run.merge_requests_seen}, "
        f"pipelines={run.pipelines_seen}, failed_jobs={run.jobs_seen}"
    , flush=True)
    if run.error:
        print(f"sync errors: {run.error}", flush=True)

    for showcase in _showcases():
        project_path = f"{namespace_path}/{showcase.slug}"
        project = db.scalar(
            select(models.GitLabProject)
            .where(models.GitLabProject.project_path == project_path)
            .order_by(desc(models.GitLabProject.synced_at))
        )
        if not project:
            print(f"index skipped: {project_path} was not returned by GitLab sync", flush=True)
            continue
        index_run = RepoContextService(db, client=client, workspace_id=workspace_id).index_project(project, limit=80)
        print(f"indexed {project_path}: status={index_run.status}, files={index_run.files_indexed}, skipped={index_run.files_skipped}", flush=True)
        if create_fix_plans:
            _create_fix_plan(db, project, workspace_id, showcase)


def _create_fix_plan(db, project: models.GitLabProject, workspace_id: int | None, showcase: LargeShowcase) -> None:
    existing = db.scalar(
        select(models.FixPlan)
        .where(models.FixPlan.project_id == project.id)
        .where(models.FixPlan.fix_type == showcase.fix_type)
        .where(models.FixPlan.summary == showcase.problem)
        .order_by(desc(models.FixPlan.created_at))
    )
    if existing:
        print(f"fix plan already exists for {project.project_path}: id={existing.id} status={existing.status}", flush=True)
        return
    plan = FixPlanService(db, workspace_id=workspace_id).create(
        project_id=project.id,
        problem_statement=showcase.problem,
        fix_type=showcase.fix_type,
    )
    print(f"created draft fix plan for {project.project_path}: id={plan.id} type={plan.fix_type}", flush=True)


def _showcases() -> list[LargeShowcase]:
    return [
        LargeShowcase(
            slug="panopticon-showcase-multi-error-commerce",
            description="Large Panopticon showcase with several source-code bugs across pricing, inventory, and shipping.",
            fix_type="multi_file_bug_fix",
            problem="Fix all failing tests: discount coupon, inventory reservation, and shipping estimate bugs.",
            files=_commerce_files(),
        ),
        LargeShowcase(
            slug="panopticon-showcase-platform-hardening",
            description="Large Panopticon showcase for robustness recommendations and multi-file hardening changes.",
            fix_type="multi_file_bug_fix",
            problem="Make this project more robust: add HTTP timeout handling, required config validation, and transient retry handling.",
            files=_hardening_files(),
        ),
    ]


def _base_ci() -> str:
    return """stages:
  - lint
  - test
  - package

workflow:
  rules:
    - when: always

lint:
  image: python:3.12-slim
  stage: lint
  script:
    - python -m compileall services tests

unit-tests:
  image: python:3.12-slim
  stage: test
  script:
    - pip install -r requirements.txt
    - python -m pytest -q

package:
  image: python:3.12-slim
  stage: package
  script:
    - python -c "print('package metadata validated')"
"""


def _commerce_files() -> dict[str, str]:
    return {
        ".gitlab-ci.yml": _base_ci(),
        "README.md": """# Multi Error Commerce Showcase

This repository intentionally contains multiple real source-code bugs.

Panopticon should identify the failing areas, retrieve the relevant code, and draft a multi-file source fix plan.
""",
        "requirements.txt": "pytest==8.4.1\n",
        "services/__init__.py": "",
        "services/pricing/__init__.py": "",
        "services/pricing/discounts.py": '''def apply_coupon(total, coupon):
    if total < 0:
        raise ValueError("total cannot be negative")
    if coupon == "SAVE10":
        return total - 10
    return total
''',
        "services/inventory/__init__.py": "",
        "services/inventory/reservations.py": """def reserve_stock(available, requested):
    return available - requested
""",
        "services/shipping/__init__.py": "",
        "services/shipping/estimate.py": """def estimate_delivery_days(country, expedited=False):
    if expedited:
        return 2
    return 5
""",
        "services/orders/__init__.py": "",
        "services/orders/checkout.py": """from services.inventory.reservations import reserve_stock
from services.pricing.discounts import apply_coupon
from services.shipping.estimate import estimate_delivery_days


def checkout(total, coupon, available, requested, country):
    remaining = reserve_stock(available, requested)
    payable = apply_coupon(total, coupon)
    delivery_days = estimate_delivery_days(country)
    return {"remaining": remaining, "payable": payable, "delivery_days": delivery_days}
""",
        "tests/test_pricing.py": '''from services.pricing.discounts import apply_coupon


def test_save10_is_percent_discount():
    assert apply_coupon(100.0, "SAVE10") == 90.0
    assert apply_coupon(50.0, "SAVE10") == 45.0
''',
        "tests/test_inventory.py": '''import pytest

from services.inventory.reservations import reserve_stock


def test_reserve_stock_rejects_invalid_quantities():
    with pytest.raises(ValueError):
        reserve_stock(10, 0)
    with pytest.raises(ValueError):
        reserve_stock(10, 11)


def test_reserve_stock_returns_remaining_inventory():
    assert reserve_stock(10, 3) == 7
''',
        "tests/test_shipping.py": '''from services.shipping.estimate import estimate_delivery_days


def test_domestic_and_international_shipping_estimates():
    assert estimate_delivery_days("IN") == 3
    assert estimate_delivery_days("IN", expedited=True) == 1
    assert estimate_delivery_days("US") == 7
    assert estimate_delivery_days("US", expedited=True) == 3
''',
        "docs/architecture.md": "# Architecture\n\nPricing, inventory, shipping, and checkout are intentionally separate modules.\n",
        "deploy/kubernetes/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: commerce-showcase\n",
    }


def _hardening_files() -> dict[str, str]:
    return {
        ".gitlab-ci.yml": _base_ci(),
        "README.md": """# Platform Hardening Showcase

This repository intentionally contains robustness gaps across HTTP calls, environment configuration, and retry handling.

Panopticon should recommend concrete hardening changes and draft source-code diffs.
""",
        "requirements.txt": "pytest==8.4.1\n",
        "services/__init__.py": "",
        "services/platform/__init__.py": "",
        "services/platform/http_client.py": """def fetch_status(url, client):
    return client.get(url)
""",
        "services/platform/config.py": '''import os


def payment_url():
    return os.getenv("PAYMENT_URL")
''',
        "services/platform/retry.py": """def call_with_retry(fn, attempts=3):
    return fn()
""",
        "services/platform/worker.py": """from services.platform.config import payment_url
from services.platform.http_client import fetch_status
from services.platform.retry import call_with_retry


def healthcheck(client):
    url = payment_url()
    return call_with_retry(lambda: fetch_status(url, client))
""",
        "tests/test_http_client.py": '''from services.platform.http_client import fetch_status


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        return {"ok": True}


def test_fetch_status_uses_bounded_timeout():
    client = FakeClient()
    assert fetch_status("https://example.test/health", client) == {"ok": True}
    assert client.calls[0]["timeout"] == 5
''',
        "tests/test_config.py": '''import pytest

from services.platform.config import payment_url


def test_payment_url_is_required(monkeypatch):
    monkeypatch.delenv("PAYMENT_URL", raising=False)
    with pytest.raises(ValueError):
        payment_url()
''',
        "tests/test_retry.py": '''from services.platform.retry import call_with_retry


def test_call_with_retry_recovers_from_transient_failures():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert call_with_retry(flaky, attempts=3) == "ok"
    assert attempts["count"] == 3
''',
        "docs/operations.md": "# Operations\n\nHardening targets: timeouts, config validation, retries, and CI evidence.\n",
        "deploy/kubernetes/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: platform-hardening\n",
    }


if __name__ == "__main__":
    main()
