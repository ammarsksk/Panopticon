from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from app import models
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.scripts.seed_showcase import clear_showcase, seed_showcase
from app.services.auth import AuthService
from app.services.chat_eval import ChatEvalRunner, load_cases, write_reports
from app.services.metrics import MetricsService


DEFAULT_CASES = Path(__file__).resolve().parents[3] / "docs" / "chat_eval_cases" / "seed.jsonl"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "artifacts" / "chat_eval"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic or live Gemini chat evaluations.")
    parser.add_argument("--cases", action="append", default=[], help="JSONL case file. Can be passed more than once.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT), help="Directory for latest.json and latest.md reports.")
    parser.add_argument("--workspace", default="", help="Workspace slug. Defaults to local development workspace.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N expanded cases.")
    parser.add_argument("--live-gemini", action="store_true", help="Use live Gemini instead of deterministic draft mode.")
    parser.add_argument("--seed-showcase", action="store_true", help="Reset and seed local showcase records before evaluation.")
    args = parser.parse_args()

    case_paths = [Path(path).resolve() for path in (args.cases or [str(DEFAULT_CASES)])]
    cases = load_cases(case_paths)
    if args.limit:
        cases = cases[: args.limit]

    settings = get_settings()
    if args.seed_showcase and settings.is_production:
        raise SystemExit("--seed-showcase is blocked when APP_ENV=production")

    init_db()
    db = SessionLocal()
    try:
        workspace = _workspace(db, args.workspace)
        if args.seed_showcase:
            clear_showcase(db, workspace.id)
            seed_showcase(db, workspace.id)
            MetricsService(db, workspace_id=workspace.id).refresh_snapshots()
            db.commit()

        summary = ChatEvalRunner(db, workspace_id=workspace.id, live_gemini=args.live_gemini).run(cases)
        write_reports(summary, output_dir=Path(args.output_dir).resolve())
        print(f"chat_eval total={summary.total} passed={summary.passed} failed={summary.failed} pass_rate={summary.pass_rate:.1%} p95_ms={summary.p95_latency_ms:.1f}")
        if summary.top_failures:
            print("top_failures=" + ", ".join(f"{item['check']}:{item['count']}" for item in summary.top_failures))
    finally:
        db.close()


def _workspace(db, slug: str) -> models.Workspace:
    if slug:
        workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == slug))
        if not workspace:
            raise SystemExit(f"Workspace not found: {slug}")
        return workspace
    return AuthService(db).local_dev_context().workspace


if __name__ == "__main__":
    main()
