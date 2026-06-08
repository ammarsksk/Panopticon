from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AgentAction, FixPlan, MemoryRecord, Workspace
from app.services.agent_actions import AgentActionService
from app.services.agent_memory import AgentMemoryService
from app.services.fix_plans import FixPlanService


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_memory_retrieval_is_workspace_scoped():
    db = _session()
    workspace_a = Workspace(name="A", slug="a")
    workspace_b = Workspace(name="B", slug="b")
    db.add_all([workspace_a, workspace_b])
    db.flush()

    AgentMemoryService(db, workspace_id=workspace_a.id)._upsert_memory(
        project_path="",
        memory_type="workspace_policy_memory",
        signature="policy-table-answers",
        summary="Use tables for incident comparisons.",
        evidence=["admin_preference"],
        remediation=["Prefer tabular incident summaries when requested."],
    )
    db.commit()

    visible = AgentMemoryService(db, workspace_id=workspace_a.id).retrieve(project=None, question="incident table", limit=5)
    hidden = AgentMemoryService(db, workspace_id=workspace_b.id).retrieve(project=None, question="incident table", limit=5)

    assert [record.summary for record in visible] == ["Use tables for incident comparisons."]
    assert hidden == []


def test_action_decision_writes_agent_memory():
    db = _session()
    action = AgentAction(
        project_path="demo/checkout-service",
        action_type="slack_alert",
        channel="slack",
        title="Pipeline failure detected",
        summary="Tell Slack about the failed pipeline.",
        status="pending_approval",
        requires_approval=True,
        payload_preview={"message": "failed"},
        execution_context={},
        last_result={},
        error="",
    )
    db.add(action)
    db.commit()

    AgentActionService(db).approve(action.id, actor="ammar", reason="matches evidence")
    memory = db.query(MemoryRecord).filter(MemoryRecord.memory_type == "approved_action_memory").one()

    assert "Action #" in memory.summary
    assert "approved" in memory.summary
    assert any("matches evidence" in item for item in memory.evidence)


def test_fix_plan_rejection_writes_agent_memory():
    db = _session()
    plan = FixPlan(
        project_path="demo/checkout-service",
        source_type="pipeline",
        source_id="1",
        title="Stabilize checkout pipeline",
        summary="Prepare a safe fix plan.",
        status="draft",
        requires_approval=True,
        fix_type="pipeline_timeout",
        base_branch="main",
        branch_name="panopticon/checkout-timeout",
        merge_request_iid="",
        merge_request_url="",
        plan_payload={"branch_name": "panopticon/checkout-timeout"},
        last_result={},
        error="",
    )
    db.add(plan)
    db.commit()

    FixPlanService(db).reject(plan.id, actor="ammar", reason="too broad")
    memory = db.query(MemoryRecord).filter(MemoryRecord.memory_type == "fix_plan_memory").one()

    assert "Fix plan #" in memory.summary
    assert "rejected" in memory.summary
    assert any("too broad" in item for item in memory.evidence)
