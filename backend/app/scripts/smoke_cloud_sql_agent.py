from __future__ import annotations

from sqlalchemy import desc, func, select

from app import models
from app.database import SessionLocal
from app.services.agent_tools import AgentToolService
from app.services.auth import AuthService
from app.services.chat import ChatService


def main() -> None:
    with SessionLocal() as db:
        context = AuthService(db).agent_runtime_context()
        project = db.scalar(
            select(models.GitLabProject)
            .where(models.GitLabProject.workspace_id == context.workspace.id)
            .order_by(desc(models.GitLabProject.synced_at))
            .limit(1)
        )
        if not project:
            raise SystemExit("No GitLab projects are synced in this Cloud SQL workspace.")

        chunk_count = db.scalar(select(func.count(models.RepoCodeChunk.id)).where(models.RepoCodeChunk.project_id == project.id)) or 0
        vector_ready = (
            db.scalar(
                select(func.count(models.RepoCodeChunk.id))
                .where(models.RepoCodeChunk.project_id == project.id)
                .where(models.RepoCodeChunk.embedding_provider == "vertex")
                .where(models.RepoCodeChunk.embedding_status == "ready")
            )
            or 0
        )
        tools = AgentToolService(db, workspace_id=context.workspace.id)
        context_pack = tools.call_tool("build_context_pack", {"project_id": project.id, "query": "failed pipeline deployment risk", "limit": 5})
        chat = ChatService(db, workspace_id=context.workspace.id).answer(
            project_id=project.id,
            message="Which risks or failures should I inspect first, and which repository files are relevant?",
        )

        answer = chat["assistant_message"].content
        print("Cloud SQL agent smoke")
        print("=====================")
        print(f"workspace={context.workspace.slug} ({context.workspace.id})")
        print(f"project={project.project_path}")
        print(f"repo_chunks={chunk_count}")
        print(f"vertex_ready_chunks={vector_ready}")
        print(f"context_pack_chunks={len(context_pack.get('chunks') or [])}")
        print(f"context_pack_files={len(context_pack.get('files') or [])}")
        print(f"chat_answer_chars={len(answer)}")
        print()
        print("Answer preview")
        print("--------------")
        print(answer[:1200])


if __name__ == "__main__":
    main()
