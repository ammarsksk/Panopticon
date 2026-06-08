from __future__ import annotations

import base64

from app.scripts.create_gitlab_showcase_projects import GitLabShowcaseProvisioner
from app.scripts.seed_showcase import PROJECTS


class FakeProvisioningGitLabClient:
    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.files: dict[tuple[str, str, str], str] = {}
        self.branches: set[tuple[str, str]] = set()
        self.merge_requests: list[dict] = []
        self.commits: list[dict] = []

    def current_user(self):
        return {"username": "ammarsaifeek"}

    def get_project(self, project_path):
        if project_path not in self.projects:
            import httpx

            raise httpx.HTTPStatusError("not found", request=httpx.Request("GET", "https://gitlab.test"), response=httpx.Response(404))
        return self.projects[project_path]

    def create_project(self, *, name, path, description="", visibility="private", namespace_id=""):
        project_path = f"ammarsaifeek/{path}"
        self.projects[project_path] = {
            "path_with_namespace": project_path,
            "name": name,
            "web_url": f"https://gitlab.com/{project_path}",
            "default_branch": "main",
            "description": description,
            "visibility": visibility,
        }
        self.branches.add((project_path, "main"))
        return self.projects[project_path]

    def update_project(self, project_path, payload):
        self.projects[project_path].update(payload)
        return self.projects[project_path]

    def get_repository_file(self, project_path, file_path, ref):
        key = (project_path, ref, file_path)
        if key not in self.files:
            import httpx

            raise httpx.HTTPStatusError("not found", request=httpx.Request("GET", "https://gitlab.test"), response=httpx.Response(404))
        content = self.files[key]
        return {"encoding": "base64", "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}

    def get_branch(self, project_path, branch_name):
        if (project_path, branch_name) not in self.branches:
            import httpx

            raise httpx.HTTPStatusError("not found", request=httpx.Request("GET", "https://gitlab.test"), response=httpx.Response(404))
        return {"name": branch_name}

    def create_commit_live(self, project_path, branch_name, commit_message, actions, *, start_branch=""):
        if start_branch:
            self.branches.add((project_path, branch_name))
            for (stored_project, stored_branch, file_path), content in list(self.files.items()):
                if stored_project == project_path and stored_branch == start_branch:
                    self.files[(project_path, branch_name, file_path)] = content
        return self._apply_commit(project_path, branch_name, commit_message, actions)

    def _request(self, method, path, **kwargs):
        assert method == "POST"
        payload = kwargs["json"]
        project_path = path.split("/repository/commits", 1)[0].removeprefix("/projects/").replace("%2F", "/")
        if payload.get("start_branch"):
            self.branches.add((project_path, payload["branch"]))
            for (stored_project, stored_branch, file_path), content in list(self.files.items()):
                if stored_project == project_path and stored_branch == payload["start_branch"]:
                    self.files[(project_path, payload["branch"], file_path)] = content
        return self._apply_commit(project_path, payload["branch"], payload["commit_message"], payload["actions"])

    def _apply_commit(self, project_path, branch_name, commit_message, actions):
        self.commits.append({"project_path": project_path, "branch": branch_name, "message": commit_message, "actions": actions})
        self.branches.add((project_path, branch_name))
        for action in actions:
            self.files[(project_path, branch_name, action["file_path"])] = action["content"]
        return {"id": f"commit-{len(self.commits)}"}

    def list_open_merge_requests(self, project_path, limit=100):
        return [item for item in self.merge_requests if item["project_path"] == project_path]

    def create_merge_request_live(self, project_path, source_branch, target_branch, title, description):
        item = {
            "project_path": project_path,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "web_url": f"https://gitlab.com/{project_path}/-/merge_requests/1",
        }
        self.merge_requests.append(item)
        return item

    def create_pipeline_live(self, project_path, ref):
        return {"id": len(self.commits) + 100, "ref": ref, "status": "created"}


def test_gitlab_showcase_provisioner_creates_real_project_shape_and_mr():
    client = FakeProvisioningGitLabClient()
    provisioner = GitLabShowcaseProvisioner(client, prefix="panopticon-showcase")

    results = provisioner.provision([PROJECTS[0]])

    assert results[0].project_path == "ammarsaifeek/panopticon-showcase-checkout-core"
    assert results[0].created is True
    assert results[0].merge_request_url.endswith("/-/merge_requests/1")
    assert len(client.commits) == 2
    assert any(action["file_path"] == ".gitlab-ci.yml" for action in client.commits[0]["actions"])
    assert any(action["file_path"] == "docs/change_request.md" for action in client.commits[1]["actions"])
    assert "python scripts/panopticon_failure.py" in client.files[(results[0].project_path, "main", ".gitlab-ci.yml")]


def test_gitlab_showcase_provisioner_rerun_reuses_project_and_mr():
    client = FakeProvisioningGitLabClient()
    provisioner = GitLabShowcaseProvisioner(client, prefix="panopticon-showcase")

    first = provisioner.provision([PROJECTS[0]])
    second = provisioner.provision([PROJECTS[0]])

    assert first[0].project_path == second[0].project_path
    assert second[0].created is False
    assert len(client.merge_requests) == 1
