from __future__ import annotations

import argparse
import base64
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import desc, select

from app import models
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.integrations.gitlab import GitLabClient
from app.scripts.seed_showcase import PROJECTS
from app.services.gitlab_sync import GitLabProjectSyncService
from app.services.oauth import decrypt_token, gitlab_client_for_workspace


@dataclass(frozen=True)
class ShowcaseResult:
    project_path: str
    web_url: str
    branch: str
    merge_request_url: str
    created: bool


class GitLabShowcaseProvisioner:
    def __init__(self, client: GitLabClient, *, prefix: str, namespace_path: str = "", namespace_id: str = "", visibility: str = "private") -> None:
        self.client = client
        self.prefix = _slug(prefix or "panopticon-showcase")
        self.namespace_path = namespace_path.strip().strip("/")
        self.namespace_id = namespace_id.strip()
        self.visibility = visibility if visibility in {"private", "internal", "public"} else "private"

    def provision(self, scenarios: list[dict[str, Any]] | None = None) -> list[ShowcaseResult]:
        scenarios = scenarios or PROJECTS
        namespace_path = self.namespace_path or self._personal_namespace_path()
        results: list[ShowcaseResult] = []
        for scenario in scenarios:
            project_path = f"{namespace_path}/{self._project_slug(scenario)}"
            project, created = self._ensure_project(project_path, scenario)
            default_branch = str(project.get("default_branch") or "main")
            self._commit_main_files(project_path, default_branch, scenario)
            branch = self._demo_branch(scenario)
            self._commit_demo_branch(project_path, default_branch, branch, scenario)
            merge_request = self._ensure_merge_request(project_path, branch, default_branch, scenario)
            self._trigger_branch_pipeline(project_path, branch)
            results.append(
                ShowcaseResult(
                    project_path=project_path,
                    web_url=str(project.get("web_url") or ""),
                    branch=branch,
                    merge_request_url=str(merge_request.get("web_url") or ""),
                    created=created,
                )
            )
        return results

    def _personal_namespace_path(self) -> str:
        user = self.client.current_user()
        namespace = str(user.get("username") or "").strip()
        if not namespace:
            raise RuntimeError("Could not resolve GitLab username. Set GITLAB_SHOWCASE_NAMESPACE_PATH in backend/.env.")
        return namespace

    def _project_slug(self, scenario: dict[str, Any]) -> str:
        return _slug(f"{self.prefix}-{scenario['name']}")

    def _demo_branch(self, scenario: dict[str, Any]) -> str:
        return f"panopticon/{_slug(str(scenario['branch']))}"

    def _ensure_project(self, project_path: str, scenario: dict[str, Any]) -> tuple[dict, bool]:
        try:
            project = self.client.get_project(project_path)
            self._enable_shared_runners(project_path)
            return project, False
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise

        project = self.client.create_project(
            name=f"{self.prefix}-{scenario['name']}",
            path=project_path.rsplit("/", 1)[-1],
            description=f"Panopticon real GitLab showcase: {scenario['summary']}",
            visibility=self.visibility,
            namespace_id=self.namespace_id,
        )
        self._enable_shared_runners(str(project.get("path_with_namespace") or project_path))
        return project, True

    def _enable_shared_runners(self, project_path: str) -> None:
        try:
            self.client.update_project(project_path, {"shared_runners_enabled": True})
        except httpx.HTTPStatusError:
            return

    def _commit_main_files(self, project_path: str, default_branch: str, scenario: dict[str, Any]) -> None:
        actions = self._actions_for_files(project_path, default_branch, _main_files(scenario))
        if not actions:
            return
        self.client.create_commit_live(project_path, default_branch, f"Seed Panopticon showcase files for {scenario['name']}", actions)

    def _commit_demo_branch(self, project_path: str, default_branch: str, branch: str, scenario: dict[str, Any]) -> None:
        branch_exists = self._branch_exists(project_path, branch)
        ref = branch if branch_exists else default_branch
        actions = self._actions_for_files(project_path, ref, _branch_files(scenario))
        if not actions:
            return
        result = self.client.create_commit_live(
            project_path,
            branch,
            f"Create Panopticon risk scenario for {scenario['name']}",
            actions,
            start_branch="" if branch_exists else default_branch,
        )
        if not result:
            raise RuntimeError(f"GitLab did not return a commit payload for {project_path}:{branch}")

    def _actions_for_files(self, project_path: str, ref: str, files: dict[str, str]) -> list[dict[str, str]]:
        actions = []
        for path, content in files.items():
            current = self._file(project_path, path, ref)
            if current and _decoded_content(current) == content:
                continue
            actions.append({"action": "update" if current else "create", "file_path": path, "content": content})
        return actions

    def _file(self, project_path: str, file_path: str, ref: str) -> dict:
        try:
            return self.client.get_repository_file(project_path, file_path, ref)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return {}
            raise

    def _branch_exists(self, project_path: str, branch: str) -> bool:
        try:
            return bool(self.client.get_branch(project_path, branch))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return False
            raise

    def _ensure_merge_request(self, project_path: str, branch: str, default_branch: str, scenario: dict[str, Any]) -> dict:
        existing = self.client.list_open_merge_requests(project_path, limit=100)
        for merge_request in existing:
            if merge_request.get("source_branch") == branch:
                return merge_request
        description = (
            "Panopticon showcase merge request.\n\n"
            f"Scenario: {scenario['summary']}\n\n"
            "This MR is intentionally designed to exercise project sync, pipeline failure ingestion, "
            "job trace classification, risk scoring, repository context, chat grounding, Slack recommendations, and fix-plan generation."
        )
        return self.client.create_merge_request_live(project_path, branch, default_branch, str(scenario["mr"]), description)

    def _trigger_branch_pipeline(self, project_path: str, branch: str) -> None:
        try:
            self.client.create_pipeline_live(project_path, branch)
        except httpx.HTTPStatusError as exc:
            print(f"could not trigger pipeline for {project_path}:{branch}: {exc.response.status_code}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create real GitLab projects for Panopticon showcase testing.")
    parser.add_argument("--no-sync", action="store_true", help="Create GitLab projects only; skip Panopticon sync.")
    parser.add_argument("--no-wait", action="store_true", help="Do not wait for GitLab pipelines before sync.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        client, workspace_id = _client_from_env_or_oauth(db)
        settings = get_settings()
        provisioner = GitLabShowcaseProvisioner(
            client,
            prefix=settings.gitlab_showcase_project_prefix,
            namespace_path=settings.gitlab_showcase_namespace_path,
            namespace_id=settings.gitlab_showcase_namespace_id,
            visibility=settings.gitlab_showcase_visibility,
        )
        results = provisioner.provision()
        for result in results:
            status = "created" if result.created else "updated"
            print(f"{status}: {result.project_path} {result.web_url}")
            if result.merge_request_url:
                print(f"  mr: {result.merge_request_url}")
        if not args.no_wait and settings.gitlab_showcase_pipeline_wait_seconds > 0:
            _wait_for_pipelines(client, results, timeout_seconds=settings.gitlab_showcase_pipeline_wait_seconds)
        if not args.no_sync:
            run = GitLabProjectSyncService(db, client=client, workspace_id=workspace_id).sync(limit=100, merge_request_limit=50, pipeline_limit=20, job_limit=50)
            print(
                "synced from GitLab: "
                f"status={run.status}, projects={run.projects_updated}, mrs={run.merge_requests_seen}, "
                f"pipelines={run.pipelines_seen}, failed_jobs={run.jobs_seen}"
            )
            if run.error:
                print(f"sync errors: {run.error}")
    finally:
        db.close()


def _client_from_env_or_oauth(db) -> tuple[GitLabClient, int | None]:
    settings = get_settings()
    if settings.gitlab_token:
        return GitLabClient(), None

    connection = db.scalar(
        select(models.OAuthConnection)
        .where(models.OAuthConnection.provider == "gitlab")
        .order_by(desc(models.OAuthConnection.updated_at))
    )
    if not connection:
        raise RuntimeError("GitLab is not connected. Connect GitLab OAuth in the app or set GITLAB_TOKEN in backend/.env.")
    workspace_id = connection.workspace_id
    if workspace_id is None:
        token = decrypt_token(connection.access_token_encrypted)
        return GitLabClient(access_token=token, auth_mode="bearer"), None
    return gitlab_client_for_workspace(db, workspace_id), workspace_id


def _wait_for_pipelines(client: GitLabClient, results: list[ShowcaseResult], *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    active = {"created", "waiting_for_resource", "preparing", "pending", "running"}
    terminal = {"success", "failed", "canceled", "skipped", "manual"}
    while time.monotonic() < deadline:
        unfinished = []
        for result in results:
            pipelines = client.list_pipelines(result.project_path, limit=5)
            branch_pipelines = [item for item in pipelines if item.get("ref") == result.branch]
            if not branch_pipelines:
                unfinished.append(f"{result.project_path}:{result.branch}:missing")
                continue
            status = str(branch_pipelines[0].get("status") or "")
            if status in active or status not in terminal:
                unfinished.append(f"{result.project_path}:{status}")
        if not unfinished:
            print("GitLab showcase pipelines reached terminal states.")
            return
        print(f"waiting for GitLab pipelines: {len(unfinished)} unfinished")
        time.sleep(10)
    print("GitLab pipeline wait timed out; syncing current GitLab state.")


def _main_files(scenario: dict[str, Any]) -> dict[str, str]:
    files = dict(scenario["files"])
    files[".gitlab-ci.yml"] = _ci_config(scenario)
    files["README.md"] = _readme(scenario)
    files["docs/panopticon_scenario.md"] = _scenario_doc(scenario)
    files["scripts/panopticon_failure.py"] = _failure_script(scenario)
    return files


def _branch_files(scenario: dict[str, Any]) -> dict[str, str]:
    files = {
        "docs/change_request.md": (
            f"# {scenario['mr']}\n\n"
            f"Risk level: {scenario['level']}\n\n"
            f"Expected Panopticon signal: {scenario['summary']}\n"
        )
    }
    primary = _primary_file(scenario)
    files[primary] = scenario["files"][primary] + "\n\n# Panopticon scenario change: review this path before merge.\n"
    return files


def _ci_config(scenario: dict[str, Any]) -> str:
    failure_job = str(scenario["job"])
    success_or_fail = "python scripts/panopticon_failure.py" if scenario["failure"] else "python -c \"print('showcase checks passed')\""
    return f"""stages:
  - setup
  - validate
  - security
  - test
  - build
  - deploy

workflow:
  rules:
    - when: always

lint:
  image: python:3.12-slim
  stage: validate
  script:
    - python -c "print('lint completed for {scenario['name']}')"

unit-tests:
  image: python:3.12-slim
  stage: test
  script:
    - python -c "print('unit tests completed for {scenario['name']}')"

{failure_job}:
  image: python:3.12-slim
  stage: {scenario['stage']}
  script:
    - {success_or_fail}
"""


def _failure_script(scenario: dict[str, Any]) -> str:
    if not scenario["failure"]:
        return "print('Panopticon showcase project is healthy')\n"
    lines = scenario["trace"].strip().splitlines()
    escaped = "\n".join(f"print({line!r})" for line in lines)
    return f"{escaped}\nraise SystemExit(1)\n"


def _readme(scenario: dict[str, Any]) -> str:
    return f"""# {scenario['name']}

This is a real GitLab project created for Panopticon end-to-end testing.

It is designed to test:

- GitLab project discovery and sync
- Merge request discovery
- Pipeline and failed job ingestion
- Failed job trace classification
- Repository context indexing
- Chat answers grounded in real GitLab data
- Slack and GitLab action recommendations
- Fix-plan generation

Scenario: {scenario['summary']}
"""


def _scenario_doc(scenario: dict[str, Any]) -> str:
    return f"""# Panopticon Scenario

Project: {scenario['name']}
Branch: {scenario['branch']}
Merge request: {scenario['mr']}
Risk: {scenario['risk']}/100 {scenario['level']}
Failure type: {scenario['failure'] or 'none'}

Expected recommendation:
{_recommendation_text(scenario)}
"""


def _primary_file(scenario: dict[str, Any]) -> str:
    for path in scenario["files"]:
        if not path.startswith(".") and not path.lower().endswith((".md", ".json", ".lock")):
            return path
    return next(iter(scenario["files"]))


def _recommendation_text(scenario: dict[str, Any]) -> str:
    if scenario["failure"] == "timeout":
        return "Inspect rollout readiness and timeout configuration before retrying deployment."
    if scenario["failure"] == "test_failure":
        return "Fix the event contract or test fixture, then rerun the focused contract test."
    if scenario["failure"] == "auth_or_permission":
        return "Validate OAuth credential rotation and add an integration smoke test."
    if scenario["failure"] == "deployment_failure":
        return "Fix infrastructure syntax and require infrastructure owner review."
    if scenario["failure"] == "docker_build":
        return "Regenerate the dependency lockfile and rebuild the image."
    if scenario["failure"] == "dependency_install":
        return "Pin a valid dependency version and rerun dependency installation."
    return "Proceed with review and monitor release metrics."


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "panopticon-showcase"


def _decoded_content(file_payload: dict) -> str:
    if file_payload.get("encoding") != "base64":
        return str(file_payload.get("content") or "")
    try:
        return base64.b64decode(str(file_payload.get("content") or "").encode("ascii")).decode("utf-8")
    except Exception:
        return ""


if __name__ == "__main__":
    main()
