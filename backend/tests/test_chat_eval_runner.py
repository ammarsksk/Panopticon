import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.scripts.seed_showcase import seed_showcase
from app.services.auth import AuthService
from app.services.chat_eval import ChatEvalCase, ChatEvalRunner, load_cases, write_reports


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_showcase_workspace(db):
    context = AuthService(db).local_dev_context()
    seed_showcase(db, context.workspace.id)
    db.commit()
    return context.workspace.id


def test_chat_eval_runner_scores_deterministic_showcase_case():
    db = _session()
    try:
        workspace_id = _seed_showcase_workspace(db)
        case = ChatEvalCase(
            id="checkout-timeout",
            category="pipeline",
            project_path="showcase/checkout-core",
            question="Why did the checkout pipeline fail?",
            expected_intent="pipeline_failure",
            required_terms=["Pipeline analysis", "timeout"],
            forbidden_terms=["invoice_total", "client_secret="],
        )

        summary = ChatEvalRunner(db, workspace_id=workspace_id).run([case])

        assert summary.total == 1
        assert summary.passed == 1
        assert summary.by_category["pipeline"]["passed"] == 1
        assert summary.by_check["intent"]["passed"] == 1
        assert summary.results[0].actual_intent == "pipeline_failure"
    finally:
        db.close()


def test_chat_eval_runner_reports_forbidden_claim_failures():
    db = _session()
    try:
        workspace_id = _seed_showcase_workspace(db)
        case = ChatEvalCase(
            id="intentional-forbidden",
            category="pipeline",
            project_path="showcase/billing-ledger",
            question="Why did the billing pipeline fail?",
            expected_intent="pipeline_failure",
            forbidden_terms=["invoice_total"],
        )

        result = ChatEvalRunner(db, workspace_id=workspace_id).run([case]).results[0]

        assert result.passed is False
        assert "forbidden_terms" in result.failures
    finally:
        db.close()


def test_load_cases_expands_question_variants(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": "variant-case",
                "category": "pipeline",
                "project_path": "showcase/checkout-core",
                "expected_intent": "pipeline_failure",
                "question_variants": ["Why did CI fail?", "What pipeline failed?"],
            }
        ),
        encoding="utf-8",
    )

    cases = load_cases([path])

    assert [case.id for case in cases] == ["variant-case_01", "variant-case_02"]
    assert [case.question for case in cases] == ["Why did CI fail?", "What pipeline failed?"]


def test_write_reports_creates_json_and_markdown(tmp_path: Path):
    db = _session()
    try:
        workspace_id = _seed_showcase_workspace(db)
        case = ChatEvalCase(
            id="checkout-timeout",
            category="pipeline",
            project_path="showcase/checkout-core",
            question="Why did the checkout pipeline fail?",
            expected_intent="pipeline_failure",
            required_terms=["Pipeline analysis"],
        )
        summary = ChatEvalRunner(db, workspace_id=workspace_id).run([case])

        write_reports(summary, output_dir=tmp_path)

        payload = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
        markdown = (tmp_path / "latest.md").read_text(encoding="utf-8")
        assert payload["total"] == 1
        assert "Chat Evaluation Report" in markdown
        assert "By Check" in markdown
    finally:
        db.close()
