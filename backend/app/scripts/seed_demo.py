import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal, init_db
from app.event_handlers.gitlab import process_gitlab_event
from app import models
from app.services.agent_actions import AgentActionService
from app.services.observability import ObservabilityService


ROOT = Path(__file__).resolve().parents[3]
PAYLOAD_DIR = ROOT / "workflows" / "demo_payloads"


def reset_demo_data(db) -> None:
    for model in (
        models.ChatMessage,
        models.ChatThread,
        models.ActionApproval,
        models.AgentAction,
        models.IncidentCorrelation,
        models.ObservabilityEvent,
        models.ActionDispatch,
        models.Recommendation,
        models.MemoryRecord,
        models.IncidentRecord,
        models.MergeRequestSignal,
        models.PipelineInsight,
        models.RiskAssessment,
        models.JobSnapshot,
        models.PipelineSnapshot,
        models.MergeRequestSnapshot,
        models.ProjectSyncRun,
        models.GitLabProject,
        models.WebhookReceipt,
        models.OperationalEvent,
    ):
        db.query(model).delete()
    db.commit()


def seed_rich_demo(db) -> None:
    now = datetime.now(timezone.utc)
    scenarios = [
        {
            "id": "101",
            "path": "demo/checkout-service",
            "name": "checkout-service",
            "namespace": "demo",
            "risk": 94,
            "level": "critical",
            "pipeline": "failed",
            "cause": "The deploy job timed out while waiting for Kubernetes rollout readiness.",
            "evidence": ["Kubernetes rollout exceeded wait limit.", "Checkout auth and payment paths changed together."],
            "recommendation": "Pause deployment, inspect rollout events, and confirm rollback for checkout.",
            "mr": "Risky checkout auth and payment rollout",
            "branch": "risk/checkout-auth",
            "job": "deploy-production",
            "failure": "script_failure",
            "incident": True,
        },
        {
            "id": "102",
            "path": "demo/billing-worker",
            "name": "billing-worker",
            "namespace": "demo",
            "risk": 86,
            "level": "critical",
            "pipeline": "failed",
            "cause": "The test job failed after a payment gateway contract mismatch.",
            "evidence": ["Contract test reported missing invoice_total field.", "No billing migration test changed."],
            "recommendation": "Run contract tests against the payment gateway stub before merge.",
            "mr": "Billing invoice event contract update",
            "branch": "feature/invoice-contract",
            "job": "contract-tests",
            "failure": "test_failure",
            "incident": False,
        },
        {
            "id": "103",
            "path": "demo/search-api",
            "name": "search-api",
            "namespace": "demo",
            "risk": 73,
            "level": "high",
            "pipeline": "success",
            "cause": "No current pipeline failure; stale reviews are slowing release.",
            "evidence": ["Merge request has no reviewer after 54 hours.", "Search ranking config changed."],
            "recommendation": "Assign a reviewer and add ranking regression coverage.",
            "mr": "Search ranking weight adjustment",
            "branch": "feature/ranking-weights",
            "job": "unit-tests",
            "failure": "",
            "incident": False,
        },
        {
            "id": "104",
            "path": "platform/identity",
            "name": "identity",
            "namespace": "platform",
            "risk": 89,
            "level": "critical",
            "pipeline": "failed",
            "cause": "The security scan failed after OAuth dependency upgrades.",
            "evidence": ["Security scanner flagged vulnerable transitive dependency.", "OAuth middleware changed without matching integration tests."],
            "recommendation": "Update the dependency lockfile and rerun auth integration tests.",
            "mr": "OAuth dependency refresh",
            "branch": "security/oauth-refresh",
            "job": "security-scan",
            "failure": "security_failure",
            "incident": True,
        },
        {
            "id": "105",
            "path": "infra/deploy-orchestrator",
            "name": "deploy-orchestrator",
            "namespace": "infra",
            "risk": 81,
            "level": "high",
            "pipeline": "failed",
            "cause": "Terraform validation failed after a production load balancer rule change.",
            "evidence": ["Terraform plan validation failed.", "Production ingress rule changed."],
            "recommendation": "Require infrastructure owner approval and validate rollback plan.",
            "mr": "Production load balancer routing update",
            "branch": "infra/lb-routing",
            "job": "terraform-validate",
            "failure": "validation_failure",
            "incident": False,
        },
        {
            "id": "106",
            "path": "mobile/api-gateway",
            "name": "api-gateway",
            "namespace": "mobile",
            "risk": 42,
            "level": "medium",
            "pipeline": "success",
            "cause": "No active failure; deployment risk is moderate due to gateway config changes.",
            "evidence": ["Gateway timeout configuration changed.", "Smoke tests passed."],
            "recommendation": "Monitor gateway latency after deployment.",
            "mr": "Mobile gateway timeout tuning",
            "branch": "feature/gateway-timeouts",
            "job": "smoke-tests",
            "failure": "",
            "incident": False,
        },
    ]

    for index, scenario in enumerate(scenarios, start=1):
        project = models.GitLabProject(
            gitlab_project_id=scenario["id"],
            project_path=scenario["path"],
            name=scenario["name"],
            namespace=scenario["namespace"],
            web_url=f"https://gitlab.com/{scenario['path']}",
            default_branch="main",
            visibility="private",
            description=f"Rich demo project for {scenario['name']}",
            last_activity_at=now - timedelta(hours=index),
            open_merge_requests_count=1,
            failed_pipelines_count=1 if scenario["pipeline"] == "failed" else 0,
            latest_pipeline_id=str(8000 + index),
            latest_pipeline_status=scenario["pipeline"],
            synced_at=now,
        )
        db.add(project)
        db.flush()

        mr = models.MergeRequestSnapshot(
            gitlab_project_id=scenario["id"],
            project_path=scenario["path"],
            merge_request_iid=str(index),
            title=scenario["mr"],
            state="opened",
            web_url=f"https://gitlab.com/{scenario['path']}/-/merge_requests/{index}",
            author_username="panopticon-demo",
            source_branch=scenario["branch"],
            target_branch="main",
            draft=False,
            created_at_gitlab=now - timedelta(hours=36 + index),
            updated_at_gitlab=now - timedelta(hours=index),
            synced_at=now,
        )
        pipeline = models.PipelineSnapshot(
            gitlab_project_id=scenario["id"],
            project_path=scenario["path"],
            pipeline_id=str(8000 + index),
            status=scenario["pipeline"],
            ref=scenario["branch"],
            sha=f"demo{index:04d}",
            web_url=f"https://gitlab.com/{scenario['path']}/-/pipelines/{8000 + index}",
            created_at_gitlab=now - timedelta(hours=index, minutes=20),
            updated_at_gitlab=now - timedelta(hours=index),
            synced_at=now,
        )
        job = models.JobSnapshot(
            gitlab_project_id=scenario["id"],
            project_path=scenario["path"],
            pipeline_id=str(8000 + index),
            job_id=str(9000 + index),
            name=scenario["job"],
            stage="deploy" if "deploy" in scenario["job"] else "test",
            status="failed" if scenario["pipeline"] == "failed" else "success",
            failure_reason=scenario["failure"],
            web_url=f"https://gitlab.com/{scenario['path']}/-/jobs/{9000 + index}",
            duration=420 + (index * 12),
            created_at_gitlab=now - timedelta(hours=index, minutes=15),
            synced_at=now,
        )
        risk = models.RiskAssessment(
            project_path=scenario["path"],
            merge_request_iid=str(index),
            deployment_ref=scenario["branch"],
            score=scenario["risk"],
            level=scenario["level"],
            summary=f"{scenario['path']} has {scenario['level']} delivery risk at {scenario['risk']}/100.",
            reasons=scenario["evidence"],
            recommendations=[scenario["recommendation"]],
            created_at=now - timedelta(minutes=index),
        )
        insight = models.PipelineInsight(
            project_path=scenario["path"],
            pipeline_id=str(8000 + index),
            status=scenario["pipeline"],
            likely_cause=scenario["cause"],
            evidence=scenario["evidence"],
            recommendations=[scenario["recommendation"]],
            created_at=now - timedelta(minutes=index),
        )
        signal = models.MergeRequestSignal(
            project_path=scenario["path"],
            merge_request_iid=str(index),
            title=scenario["mr"],
            state="opened",
            age_hours=36 + index,
            unresolved_threads=index % 3,
            reviewer_count=0 if scenario["risk"] >= 80 else 1,
            bottleneck_level="blocked" if scenario["risk"] >= 85 else "stale" if scenario["risk"] >= 70 else "healthy",
            summary=f"{scenario['mr']} needs focused review before merge.",
            created_at=now - timedelta(minutes=index),
        )
        db.add_all([mr, pipeline, job, risk, insight, signal])
        db.flush()

        if scenario["incident"]:
            db.add(
                models.IncidentRecord(
                    project_path=scenario["path"],
                    title=f"{scenario['name']} deployment instability",
                    severity="high",
                    probable_root_cause=scenario["cause"],
                    timeline=[
                        {"time": str(now - timedelta(hours=2)), "event": "Pipeline failed"},
                        {"time": str(now - timedelta(hours=1)), "event": "Deployment risk increased"},
                    ],
                    recommendations=[scenario["recommendation"]],
                    status="open",
                    created_at=now - timedelta(minutes=index),
                )
            )
        if scenario["incident"] or scenario["pipeline"] == "failed":
            db.flush()
            ObservabilityService(db).ingest(
                {
                    "event_uid": f"demo-alert-{scenario['id']}",
                    "project_path": scenario["path"],
                    "service_name": scenario["name"],
                    "environment": "production",
                    "severity": "critical" if scenario["risk"] >= 90 else "high",
                    "signal_type": "metric_alert",
                    "title": f"{scenario['name']} production health alert",
                    "message": scenario["cause"],
                    "metric_name": "service_error_rate",
                    "alert_url": f"https://grafana.example.local/alerts/{scenario['id']}",
                    "observed_at": (now - timedelta(minutes=index + 5)).isoformat(),
                },
                provider="demo_grafana",
            )

        db.add(
            models.MemoryRecord(
                project_path=scenario["path"],
                memory_type="delivery_pattern",
                signature=f"{scenario['name']}:risk:{scenario['level']}",
                summary=f"{scenario['name']} previously needed owner review when {scenario['branch']} touched release-sensitive paths.",
                evidence=scenario["evidence"],
                remediation=[scenario["recommendation"]],
                created_at=now - timedelta(minutes=index),
            )
        )
        db.add_all(
            [
                models.Recommendation(
                    project_path=scenario["path"],
                    source_type="risk",
                    source_id=str(risk.id),
                    channel="gitlab_comment",
                    message=f"{risk.summary} {scenario['recommendation']}",
                    status="dry_run",
                    created_at=now - timedelta(minutes=index),
                ),
                models.Recommendation(
                    project_path=scenario["path"],
                    source_type="pipeline",
                    source_id=str(insight.id),
                    channel="slack",
                    message=f"Pipeline {pipeline.pipeline_id} is {pipeline.status}: {scenario['cause']}",
                    status="dry_run",
                    created_at=now - timedelta(minutes=index),
                ),
            ]
        )
    db.commit()

    recommendations = db.query(models.Recommendation).order_by(models.Recommendation.created_at.desc()).limit(8).all()
    action_service = AgentActionService(db)
    for recommendation in recommendations:
        action_service.propose(recommendation)
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Panopticon demo GitLab events.")
    parser.add_argument("--reset", action="store_true", help="Clear existing local demo data before replaying payloads.")
    parser.add_argument("--rich", action="store_true", help="Add a rich multi-project demo dataset for chat and dashboard testing.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.reset:
            reset_demo_data(db)
        if args.rich:
            seed_rich_demo(db)
            print("seeded rich multi-project demo dataset")
        else:
            for path in sorted(PAYLOAD_DIR.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                result = process_gitlab_event(payload, db)
                print(f"seeded {path.name}: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
