from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request

from app.config import get_settings


def verify_gitlab_webhook(request: Request) -> None:
    settings = get_settings()
    if not settings.gitlab_webhook_secret:
        return
    token = request.headers.get("X-Gitlab-Token")
    if token != settings.gitlab_webhook_secret:
        raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")


def project_path_from_payload(payload: dict) -> str:
    project = payload.get("project") or {}
    return (
        project.get("path_with_namespace")
        or project.get("web_url", "").removeprefix("https://gitlab.com/")
        or payload.get("project_path")
        or "unknown/project"
    )


def title_from_payload(payload: dict) -> str:
    attrs = payload.get("object_attributes") or {}
    return attrs.get("title") or attrs.get("name") or payload.get("event_name") or payload.get("object_kind") or "GitLab event"


def event_type_from_payload(payload: dict) -> str:
    kind = payload.get("object_kind") or payload.get("event_name") or "unknown"
    if kind == "merge_request":
        action = payload.get("object_attributes", {}).get("action", "updated")
        return f"merge_request.{action}"
    if kind == "pipeline":
        status = payload.get("object_attributes", {}).get("status", "updated")
        return f"pipeline.{status}"
    if kind == "deployment":
        status = payload.get("object_attributes", {}).get("status", "updated")
        return f"deployment.{status}"
    return str(kind)


class GitLabClient:
    def __init__(self, access_token: str | None = None, auth_mode: str = "private_token") -> None:
        self.settings = get_settings()
        self.base_url = self.settings.gitlab_base_url.rstrip("/")
        self.access_token = access_token or self.settings.gitlab_token
        self.auth_mode = auth_mode if access_token else "private_token"

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _headers(self) -> dict[str, str]:
        if self.auth_mode == "bearer":
            return {"Authorization": f"Bearer {self.access_token}"}
        return {"PRIVATE-TOKEN": self.access_token}

    def _project_id(self, project_path: str) -> str:
        return quote(project_path, safe="")

    def _request(self, method: str, path: str, **kwargs) -> dict | list | str:
        if not self.configured:
            return {"status": "skipped", "reason": "GITLAB_TOKEN is not configured"}
        url = f"{self.base_url}/api/v4{path}"
        with httpx.Client(timeout=20) as client:
            response = client.request(method, url, headers=self._headers(), **kwargs)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                return response.json()
            return response.text

    def get_project(self, project_path: str) -> dict:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}")
        return result if isinstance(result, dict) else {}

    def current_user(self) -> dict:
        result = self._request("GET", "/user")
        return result if isinstance(result, dict) else {}

    def create_project(self, *, name: str, path: str, description: str = "", visibility: str = "private", namespace_id: str = "") -> dict:
        payload: dict[str, str | bool | int] = {
            "name": name,
            "path": path,
            "description": description,
            "visibility": visibility,
            "initialize_with_readme": "true",
            "default_branch": "main",
            "shared_runners_enabled": True,
        }
        if namespace_id:
            payload["namespace_id"] = int(namespace_id)
        result = self._request("POST", "/projects", json=payload)
        return result if isinstance(result, dict) else {}

    def update_project(self, project_path: str, payload: dict) -> dict:
        result = self._request("PUT", f"/projects/{self._project_id(project_path)}", json=payload)
        return result if isinstance(result, dict) else {}

    def create_commit_live(self, project_path: str, branch_name: str, commit_message: str, actions: list[dict], *, start_branch: str = "") -> dict:
        payload: dict[str, str | list[dict]] = {"branch": branch_name, "commit_message": commit_message, "actions": actions}
        if start_branch:
            payload["start_branch"] = start_branch
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/repository/commits",
            json=payload,
        )
        return result if isinstance(result, dict) else {}

    def create_merge_request_live(self, project_path: str, source_branch: str, target_branch: str, title: str, description: str) -> dict:
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/merge_requests",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "remove_source_branch": False,
                "squash": False,
            },
        )
        return result if isinstance(result, dict) else {}

    def create_pipeline_live(self, project_path: str, ref: str) -> dict:
        result = self._request("POST", f"/projects/{self._project_id(project_path)}/pipeline", json={"ref": ref})
        return result if isinstance(result, dict) else {}

    def get_merge_request(self, project_path: str, merge_request_iid: str) -> dict:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/merge_requests/{merge_request_iid}")
        return result if isinstance(result, dict) else {}

    def get_merge_request_changes(self, project_path: str, merge_request_iid: str) -> list[dict]:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/merge_requests/{merge_request_iid}/changes")
        if isinstance(result, dict):
            changes = result.get("changes")
            return changes if isinstance(changes, list) else []
        return []

    def get_pipeline_jobs(self, project_path: str, pipeline_id: str) -> list[dict]:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/pipelines/{pipeline_id}/jobs")
        return result if isinstance(result, list) else []

    def get_branch(self, project_path: str, branch_name: str) -> dict:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/repository/branches/{quote(branch_name, safe='')}")
        return result if isinstance(result, dict) else {}

    def get_job_trace(self, project_path: str, job_id: str) -> str:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/jobs/{job_id}/trace")
        return result if isinstance(result, str) else ""

    def get_deployments(self, project_path: str, environment: str | None = None) -> list[dict]:
        params = {"environment": environment} if environment else None
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/deployments", params=params)
        return result if isinstance(result, list) else []

    def list_projects(self, limit: int = 50) -> list[dict]:
        base_params = {
            "simple": "true",
            "order_by": "last_activity_at",
            "sort": "desc",
            "per_page": min(limit, 100),
        }
        membership = self._safe_list_projects({**base_params, "membership": "true"})
        owned = self._safe_list_projects({**base_params, "owned": "true"})
        return _dedupe_projects(
            (membership if isinstance(membership, list) else [])
            + (owned if isinstance(owned, list) else [])
        )[:limit]

    def _safe_list_projects(self, params: dict) -> list[dict]:
        try:
            result = self._request("GET", "/projects", params=params)
        except httpx.HTTPStatusError:
            return []
        return result if isinstance(result, list) else []

    def list_open_merge_requests(self, project_path: str, limit: int = 20) -> list[dict]:
        params = {
            "state": "opened",
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": min(limit, 100),
        }
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/merge_requests", params=params)
        return result if isinstance(result, list) else []

    def list_pipelines(self, project_path: str, limit: int = 10) -> list[dict]:
        params = {
            "order_by": "updated_at",
            "sort": "desc",
            "per_page": min(limit, 100),
        }
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/pipelines", params=params)
        return result if isinstance(result, list) else []

    def get_pipeline(self, project_path: str, pipeline_id: str) -> dict:
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/pipelines/{pipeline_id}")
        return result if isinstance(result, dict) else {}

    def list_repository_tree(self, project_path: str, ref: str, *, recursive: bool = True, limit: int = 100) -> list[dict]:
        params = {
            "ref": ref,
            "recursive": "true" if recursive else "false",
            "per_page": min(limit, 100),
        }
        result = self._request("GET", f"/projects/{self._project_id(project_path)}/repository/tree", params=params)
        return result if isinstance(result, list) else []

    def get_repository_file(self, project_path: str, file_path: str, ref: str) -> dict:
        result = self._request(
            "GET",
            f"/projects/{self._project_id(project_path)}/repository/files/{quote(file_path, safe='')}",
            params={"ref": ref},
        )
        return result if isinstance(result, dict) else {}

    def create_merge_request_note(self, project_path: str, merge_request_iid: str, body: str) -> dict:
        if self.settings.dry_run_actions:
            return {
                "status": "dry_run",
                "target": f"{project_path}!{merge_request_iid}",
                "body": body,
            }
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/merge_requests/{merge_request_iid}/notes",
            json={"body": body},
        )
        return result if isinstance(result, dict) else {"status": "sent"}

    def create_branch(self, project_path: str, branch_name: str, ref: str) -> dict:
        if self.settings.dry_run_actions:
            return {
                "status": "dry_run",
                "target": f"{project_path}:{branch_name}",
                "ref": ref,
            }
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/repository/branches",
            json={"branch": branch_name, "ref": ref},
        )
        return result if isinstance(result, dict) else {"status": "created", "branch": branch_name}

    def create_commit(self, project_path: str, branch_name: str, commit_message: str, actions: list[dict]) -> dict:
        if self.settings.dry_run_actions:
            return {
                "status": "dry_run",
                "target": f"{project_path}:{branch_name}",
                "commit_message": commit_message,
                "actions": actions,
            }
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/repository/commits",
            json={"branch": branch_name, "commit_message": commit_message, "actions": actions},
        )
        return result if isinstance(result, dict) else {"status": "committed", "branch": branch_name}

    def create_merge_request(self, project_path: str, source_branch: str, target_branch: str, title: str, description: str) -> dict:
        if self.settings.dry_run_actions:
            return {
                "status": "dry_run",
                "target": f"{project_path}:{source_branch}->{target_branch}",
                "title": title,
                "description": description,
                "web_url": f"{self.base_url.rstrip('/')}/{project_path}/-/merge_requests/new?merge_request[source_branch]={source_branch}",
            }
        result = self._request(
            "POST",
            f"/projects/{self._project_id(project_path)}/merge_requests",
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "remove_source_branch": True,
                "squash": False,
            },
        )
        return result if isinstance(result, dict) else {"status": "opened", "source_branch": source_branch}


def enrich_payload_from_gitlab(payload: dict) -> dict:
    if payload.get("object_kind") != "merge_request" and payload.get("event_name") != "merge_request":
        return payload

    project_path = project_path_from_payload(payload)
    attrs = payload.get("object_attributes") or {}
    merge_request_iid = str(attrs.get("iid") or attrs.get("id") or "")
    if not merge_request_iid or payload.get("changed_files"):
        return payload

    client = GitLabClient()
    if not client.configured:
        return payload

    changes = client.get_merge_request_changes(project_path, merge_request_iid)
    if changes:
        enriched = dict(payload)
        enriched["changed_files"] = changes
        return enriched
    return payload


def _dedupe_projects(projects: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for project in projects:
        key = str(project.get("id") or project.get("path_with_namespace") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(project)
    return unique
