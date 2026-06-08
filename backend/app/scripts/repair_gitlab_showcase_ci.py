from __future__ import annotations

from app.config import get_settings
from app.database import SessionLocal
from app.scripts.create_gitlab_showcase_projects import _ci_config, _failure_script, _client_from_env_or_oauth, _slug
from app.scripts.seed_showcase import PROJECTS


def main() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        client, _workspace_id = _client_from_env_or_oauth(db)
        namespace_path = settings.gitlab_showcase_namespace_path.strip().strip("/") or str(client.current_user().get("username") or "").strip()
        prefix = _slug(settings.gitlab_showcase_project_prefix or "panopticon-showcase")
        for scenario in PROJECTS:
            project_slug = _slug(f"{prefix}-{scenario['name']}")
            project_path = f"{namespace_path}/{project_slug}"
            branch = f"panopticon/{_slug(str(scenario['branch']))}"
            files = {
                ".gitlab-ci.yml": _ci_config(scenario),
                "scripts/panopticon_failure.py": _failure_script(scenario),
            }
            for ref in ["main", branch]:
                actions = []
                for path, content in files.items():
                    try:
                        client.get_repository_file(project_path, path, ref)
                        action = "update"
                    except Exception:
                        action = "create"
                    actions.append({"action": action, "file_path": path, "content": content})
                try:
                    result = client.create_commit_live(project_path, ref, "Repair Panopticon showcase CI stages", actions)
                    print(f"repaired: {project_path}:{ref} commit={result.get('short_id') or result.get('id')}", flush=True)
                except Exception as exc:
                    print(f"repair failed: {project_path}:{ref}: {exc}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
