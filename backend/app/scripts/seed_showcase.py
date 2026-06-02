from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import models
from app.database import SessionLocal, init_db
from app.services.agent_actions import AgentActionService
from app.services.auth import AuthService
from app.services.gitlab_sync import classify_job_trace
from app.services.metrics import MetricsService
from app.services.repo_context import classify_file_type, detect_language, extract_signals


PROJECTS = [
    {
        "id": "201",
        "path": "showcase/checkout-core",
        "name": "checkout-core",
        "namespace": "showcase",
        "branch": "risk/payment-timeouts",
        "mr": "Harden checkout payment timeout handling",
        "risk": 96,
        "level": "critical",
        "failure": "timeout",
        "job": "deploy-production",
        "stage": "deploy",
        "trace": "kubectl rollout status deployment/checkout-core --timeout=120s\nERROR: deployment checkout-core timed out waiting for condition\npayment_gateway_retry_timeout=15\n",
        "summary": "Deployment timed out while waiting for checkout rollout readiness after payment timeout handling changed.",
        "files": {
            ".gitlab-ci.yml": "deploy-production:\n  script: kubectl rollout status deployment/checkout-core --timeout=120s\n",
            "services/checkout/payment_gateway.py": "def charge(order):\n    return gateway.charge(order, timeout=15)\n",
            "services/checkout/auth.py": "def authorize(user, cart):\n    return user.active and cart.total > 0\n",
            "tests/test_checkout_payment.py": "def test_gateway_timeout_returns_retryable_error():\n    assert True\n",
            "deploy/kubernetes/deployment.yaml": "readinessProbe:\n  httpGet:\n    path: /healthz\n",
        },
    },
    {
        "id": "202",
        "path": "showcase/billing-ledger",
        "name": "billing-ledger",
        "namespace": "showcase",
        "branch": "feature/invoice-contract-v2",
        "mr": "Invoice event contract v2 rollout",
        "risk": 88,
        "level": "critical",
        "failure": "test_failure",
        "job": "contract-tests",
        "stage": "test",
        "trace": "pytest tests/test_invoice_contract.py\nAssertionError: expected field invoice_total in published event\nFAILED tests/test_invoice_contract.py::test_invoice_event_contains_total\n",
        "summary": "Contract tests failed because invoice_total is missing from the billing event payload.",
        "files": {
            ".gitlab-ci.yml": "contract-tests:\n  script: pytest tests/test_invoice_contract.py\n",
            "workers/billing/events.py": "def publish_invoice(invoice):\n    return {'invoice_id': invoice.id}\n",
            "tests/test_invoice_contract.py": "def test_invoice_event_contains_total():\n    assert 'invoice_total' in event\n",
            "schemas/invoice_event.json": "{\"required\": [\"invoice_id\", \"invoice_total\"]}",
            "README.md": "Billing ledger emits invoice events for downstream accounting systems.\n",
        },
    },
    {
        "id": "203",
        "path": "showcase/identity-edge",
        "name": "identity-edge",
        "namespace": "showcase",
        "branch": "security/oauth-refresh",
        "mr": "Refresh OAuth middleware dependencies",
        "risk": 91,
        "level": "critical",
        "failure": "auth_or_permission",
        "job": "security-scan",
        "stage": "security",
        "trace": "running oauth integration smoke test\nERROR: authentication failed for rotated client credentials\nclient_secret=super-secret\n",
        "summary": "Security validation failed because rotated OAuth client credentials were rejected.",
        "files": {
            ".gitlab-ci.yml": "security-scan:\n  script: python scripts/oauth_smoke.py\n",
            "services/identity/oauth.py": "def refresh_token(client):\n    return provider.refresh(client)\n",
            "services/identity/middleware.py": "def require_scope(scope):\n    return scope in request.token.scopes\n",
            "tests/test_oauth_refresh.py": "def test_refresh_uses_rotated_client():\n    assert True\n",
            "pyproject.toml": "[project]\ndependencies = ['authlib']\n",
        },
    },
    {
        "id": "204",
        "path": "showcase/infra-rollout",
        "name": "infra-rollout",
        "namespace": "showcase",
        "branch": "infra/lb-routing",
        "mr": "Production load balancer routing update",
        "risk": 84,
        "level": "high",
        "failure": "deployment_failure",
        "job": "terraform-validate",
        "stage": "validate",
        "trace": "terraform validate\nError: Unsupported argument\n  on lb.tf line 42: weighted_target_group is not expected here\n",
        "summary": "Terraform validation failed because the load balancer rule uses an unsupported argument.",
        "files": {
            ".gitlab-ci.yml": "terraform-validate:\n  script: terraform validate\n",
            "terraform/lb.tf": "resource \"aws_lb_listener_rule\" \"checkout\" {\n  weighted_target_group = true\n}\n",
            "terraform/variables.tf": "variable \"environment\" { default = \"prod\" }\n",
            "runbooks/rollback_lb.md": "Rollback by restoring the previous listener rule priority.\n",
            "tests/test_terraform_plan.py": "def test_plan_has_no_unsupported_arguments():\n    assert True\n",
        },
    },
    {
        "id": "205",
        "path": "showcase/notification-hub",
        "name": "notification-hub",
        "namespace": "showcase",
        "branch": "feature/email-renderer",
        "mr": "Email renderer container upgrade",
        "risk": 77,
        "level": "high",
        "failure": "docker_build",
        "job": "docker-build",
        "stage": "build",
        "trace": "docker build -t notification-hub .\nERROR: failed to solve: process \"/bin/sh -c npm ci\" did not complete successfully\nnpm ERR! code ELOCKVERIFY\n",
        "summary": "Container build failed because npm lockfile verification failed during npm ci.",
        "files": {
            ".gitlab-ci.yml": "docker-build:\n  script: docker build -t notification-hub .\n",
            "Dockerfile": "FROM node:22-alpine\nRUN npm ci\n",
            "package.json": "{\"scripts\":{\"test\":\"vitest\"}}",
            "package-lock.json": "{\"lockfileVersion\": 3}",
            "src/render_email.ts": "export function renderEmail(template: string) { return template; }\n",
        },
    },
    {
        "id": "206",
        "path": "showcase/data-exporter",
        "name": "data-exporter",
        "namespace": "showcase",
        "branch": "feature/parquet-writer",
        "mr": "Parquet export writer",
        "risk": 69,
        "level": "medium",
        "failure": "dependency_install",
        "job": "dependency-install",
        "stage": "setup",
        "trace": "pip install -r requirements.txt\nERROR: Could not resolve dependency pyarrow==99.0.0\n",
        "summary": "Dependency installation failed because the requested pyarrow version does not exist.",
        "files": {
            ".gitlab-ci.yml": "dependency-install:\n  script: pip install -r requirements.txt\n",
            "requirements.txt": "pyarrow==99.0.0\npandas==2.2.0\n",
            "exporter/parquet_writer.py": "def write_parquet(df):\n    return df.to_parquet()\n",
            "tests/test_parquet_writer.py": "def test_write_parquet(tmp_path):\n    assert True\n",
            "README.md": "Data exporter writes analytics snapshots to parquet.\n",
        },
    },
    {
        "id": "207",
        "path": "showcase/search-ranking",
        "name": "search-ranking",
        "namespace": "showcase",
        "branch": "feature/ranking-weight-tuning",
        "mr": "Search ranking weight tuning",
        "risk": 52,
        "level": "medium",
        "failure": "",
        "job": "unit-tests",
        "stage": "test",
        "trace": "pytest tests/test_ranking.py\n18 passed\n",
        "summary": "Pipeline passed, but the merge request is stale and needs reviewer attention.",
        "files": {
            ".gitlab-ci.yml": "unit-tests:\n  script: pytest tests/test_ranking.py\n",
            "search/ranking.py": "def score(document):\n    return document.quality * 1.2\n",
            "tests/test_ranking.py": "def test_score_increases_with_quality():\n    assert True\n",
            "config/ranking.yaml": "freshness_weight: 0.4\nquality_weight: 1.2\n",
            "README.md": "Search ranking service owns retrieval quality.\n",
        },
    },
    {
        "id": "208",
        "path": "showcase/mobile-gateway",
        "name": "mobile-gateway",
        "namespace": "showcase",
        "branch": "feature/gateway-timeouts",
        "mr": "Mobile gateway timeout tuning",
        "risk": 35,
        "level": "low",
        "failure": "",
        "job": "smoke-tests",
        "stage": "test",
        "trace": "pytest tests/test_gateway_smoke.py\n12 passed\n",
        "summary": "Pipeline passed and deployment risk is low; monitor latency after release.",
        "files": {
            ".gitlab-ci.yml": "smoke-tests:\n  script: pytest tests/test_gateway_smoke.py\n",
            "gateway/timeouts.py": "READ_TIMEOUT_SECONDS = 8\nCONNECT_TIMEOUT_SECONDS = 2\n",
            "tests/test_gateway_smoke.py": "def test_gateway_health():\n    assert True\n",
            "deploy/kubernetes/gateway.yaml": "readinessProbe:\n  path: /health\n",
            "README.md": "Mobile gateway handles mobile client traffic.\n",
        },
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed strategic showcase projects for Panopticon.")
    parser.add_argument("--workspace", default="", help="Workspace slug. Defaults to local development workspace.")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        context = AuthService(db).local_dev_context()
        workspace_id = context.workspace.id
        if args.workspace and args.workspace != context.workspace.slug:
            workspace = db.scalar(select(models.Workspace).where(models.Workspace.slug == args.workspace))
            if not workspace:
                raise SystemExit(f"Workspace not found: {args.workspace}")
            workspace_id = workspace.id

        clear_showcase(db, workspace_id)
        seed_showcase(db, workspace_id)
        MetricsService(db, workspace_id=workspace_id).refresh_snapshots()
        db.commit()
        print(f"seeded {len(PROJECTS)} showcase projects in workspace_id={workspace_id}")
    finally:
        db.close()


def clear_showcase(db, workspace_id: int) -> None:
    project_paths = [item["path"] for item in PROJECTS]
    for model in (
        models.ChatMessage,
        models.ChatThread,
        models.FixPlanApproval,
        models.FixPlan,
        models.ActionApproval,
        models.AgentAction,
        models.ActionDispatch,
        models.Recommendation,
        models.EngineeringMetricSnapshot,
        models.IncidentCorrelation,
        models.ObservabilityEvent,
        models.MemoryRecord,
        models.IncidentRecord,
        models.MergeRequestSignal,
        models.PipelineInsight,
        models.RiskAssessment,
        models.JobSnapshot,
        models.PipelineSnapshot,
        models.MergeRequestSnapshot,
        models.RepoFileIndex,
        models.RepoIndexRun,
        models.ProjectSyncRun,
        models.GitLabProject,
    ):
        if hasattr(model, "project_path"):
            db.query(model).filter(model.workspace_id == workspace_id).filter(model.project_path.in_(project_paths)).delete(synchronize_session=False)
    db.commit()


def seed_showcase(db, workspace_id: int) -> None:
    now = datetime.now(timezone.utc)
    recommendations: list[models.Recommendation] = []
    for index, scenario in enumerate(PROJECTS, start=1):
        project = _project(db, workspace_id, scenario, index, now)
        _repo_context(db, workspace_id, project, scenario, now)
        _merge_request(db, workspace_id, project, scenario, index, now)
        failed_pipeline, latest_pipeline = _pipelines_and_jobs(db, workspace_id, project, scenario, index, now)
        risk = _risk(db, workspace_id, scenario, index, now)
        insight = _pipeline_insight(db, workspace_id, scenario, failed_pipeline, now)
        _mr_signal(db, workspace_id, scenario, index, now)
        _memory(db, workspace_id, scenario, now)
        if scenario["risk"] >= 75 or scenario["failure"]:
            _observability(db, workspace_id, scenario, index, now)
        recommendations.extend(_recommendations(db, workspace_id, scenario, risk, insight, now))
        if scenario["failure"]:
            _fix_plan(db, workspace_id, project, scenario, insight, now)
        project.latest_pipeline_id = latest_pipeline.pipeline_id
        project.latest_pipeline_status = latest_pipeline.status
    db.flush()
    service = AgentActionService(db, workspace_id=workspace_id)
    for recommendation in recommendations:
        if recommendation.channel in {"gitlab_comment", "slack"}:
            service.propose(recommendation)


def _project(db, workspace_id: int, scenario: dict, index: int, now: datetime) -> models.GitLabProject:
    project = models.GitLabProject(
        workspace_id=workspace_id,
        gitlab_project_id=scenario["id"],
        project_path=scenario["path"],
        name=scenario["name"],
        namespace=scenario["namespace"],
        web_url=f"https://gitlab.com/{scenario['path']}",
        default_branch="main",
        visibility="private",
        description=f"Strategic showcase project: {scenario['summary']}",
        last_activity_at=now - timedelta(minutes=index * 8),
        open_merge_requests_count=1,
        failed_pipelines_count=2 if scenario["failure"] else 0,
        synced_at=now,
    )
    db.add(project)
    db.flush()
    return project


def _repo_context(db, workspace_id: int, project: models.GitLabProject, scenario: dict, now: datetime) -> None:
    run = models.RepoIndexRun(
        workspace_id=workspace_id,
        project_id=project.id,
        project_path=project.project_path,
        ref="main",
        status="completed",
        files_seen=len(scenario["files"]),
        files_indexed=len(scenario["files"]),
        files_skipped=0,
        started_at=now - timedelta(minutes=20),
        finished_at=now - timedelta(minutes=19),
    )
    db.add(run)
    for path, content in scenario["files"].items():
        db.add(
            models.RepoFileIndex(
                workspace_id=workspace_id,
                project_id=project.id,
                project_path=project.project_path,
                file_path=path,
                ref="main",
                file_type=classify_file_type(path),
                language=detect_language(path),
                size_bytes=len(content.encode("utf-8")),
                content_sha=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                last_commit_id=f"{scenario['id']}abc",
                content_excerpt=content,
                signals=extract_signals(path, content),
                indexed_at=now,
            )
        )


def _merge_request(db, workspace_id: int, project: models.GitLabProject, scenario: dict, index: int, now: datetime) -> None:
    db.add(
        models.MergeRequestSnapshot(
            workspace_id=workspace_id,
            gitlab_project_id=project.gitlab_project_id,
            project_path=project.project_path,
            merge_request_iid=str(index),
            title=scenario["mr"],
            state="opened",
            web_url=f"https://gitlab.com/{project.project_path}/-/merge_requests/{index}",
            author_username="showcase-dev",
            source_branch=scenario["branch"],
            target_branch="main",
            draft=False,
            created_at_gitlab=now - timedelta(hours=18 + index),
            updated_at_gitlab=now - timedelta(minutes=index * 7),
            synced_at=now,
        )
    )


def _pipelines_and_jobs(db, workspace_id: int, project: models.GitLabProject, scenario: dict, index: int, now: datetime) -> tuple[models.PipelineSnapshot, models.PipelineSnapshot]:
    latest_pipeline = None
    failed_pipeline = None
    statuses = ["failed", "failed", "success"] if scenario["failure"] else ["success", "success", "success"]
    for offset, status in enumerate(statuses):
        pipeline_id = str(720000 + index * 10 + offset)
        pipeline = models.PipelineSnapshot(
            workspace_id=workspace_id,
            gitlab_project_id=project.gitlab_project_id,
            project_path=project.project_path,
            pipeline_id=pipeline_id,
            status=status,
            ref=scenario["branch"] if offset < 2 else "main",
            sha=f"{scenario['id']}{offset}deadbeef",
            web_url=f"https://gitlab.com/{project.project_path}/-/pipelines/{pipeline_id}",
            created_at_gitlab=now - timedelta(minutes=45 + offset * 18),
            updated_at_gitlab=now - timedelta(minutes=35 + offset * 18),
            synced_at=now,
        )
        db.add(pipeline)
        if latest_pipeline is None:
            latest_pipeline = pipeline
        if status == "failed" and failed_pipeline is None:
            failed_pipeline = pipeline

        job_status = "failed" if status == "failed" else "success"
        trace = scenario["trace"] if job_status == "failed" else "tests passed\n"
        classification = classify_job_trace(trace) if job_status == "failed" else {"signature": "", "summary": "", "excerpt": trace}
        db.add(
            models.JobSnapshot(
                workspace_id=workspace_id,
                gitlab_project_id=project.gitlab_project_id,
                project_path=project.project_path,
                pipeline_id=pipeline_id,
                job_id=str(820000 + index * 10 + offset),
                name=scenario["job"],
                stage=scenario["stage"],
                status=job_status,
                failure_reason="script_failure" if job_status == "failed" else "",
                failure_signature=classification["signature"],
                trace_summary=classification["summary"],
                trace_excerpt=classification["excerpt"],
                trace_fetched_at=now if job_status == "failed" else None,
                web_url=f"https://gitlab.com/{project.project_path}/-/jobs/{820000 + index * 10 + offset}",
                duration=95 + index * 12 + offset * 9,
                created_at_gitlab=now - timedelta(minutes=40 + offset * 18),
                synced_at=now,
            )
        )
    return failed_pipeline or latest_pipeline, latest_pipeline


def _risk(db, workspace_id: int, scenario: dict, index: int, now: datetime) -> models.RiskAssessment:
    risk = models.RiskAssessment(
        workspace_id=workspace_id,
        project_path=scenario["path"],
        merge_request_iid=str(index),
        deployment_ref=scenario["branch"],
        score=scenario["risk"],
        level=scenario["level"],
        summary=f"{scenario['path']} has {scenario['level']} delivery risk at {scenario['risk']}/100.",
        reasons=[scenario["summary"], f"MR touches {', '.join(list(scenario['files'].keys())[:3])}"],
        recommendations=[_recommendation_text(scenario)],
        created_at=now - timedelta(minutes=index),
    )
    db.add(risk)
    db.flush()
    return risk


def _pipeline_insight(db, workspace_id: int, scenario: dict, pipeline: models.PipelineSnapshot, now: datetime) -> models.PipelineInsight:
    insight = models.PipelineInsight(
        workspace_id=workspace_id,
        project_path=scenario["path"],
        pipeline_id=pipeline.pipeline_id,
        status=pipeline.status,
        likely_cause=scenario["summary"],
        evidence=[scenario["trace"].splitlines()[-1] if scenario["failure"] else "Latest pipeline passed", f"Failure type: {scenario['failure'] or 'none'}"],
        recommendations=[_recommendation_text(scenario)],
        created_at=now,
    )
    db.add(insight)
    db.flush()
    return insight


def _mr_signal(db, workspace_id: int, scenario: dict, index: int, now: datetime) -> None:
    db.add(
        models.MergeRequestSignal(
            workspace_id=workspace_id,
            project_path=scenario["path"],
            merge_request_iid=str(index),
            title=scenario["mr"],
            state="opened",
            age_hours=18 + index,
            unresolved_threads=2 if scenario["risk"] >= 80 else 0,
            reviewer_count=0 if scenario["risk"] >= 80 else 1,
            bottleneck_level="blocked" if scenario["risk"] >= 80 else "review",
            summary=f"{scenario['mr']} is waiting on pipeline and owner review signals.",
            created_at=now,
        )
    )


def _memory(db, workspace_id: int, scenario: dict, now: datetime) -> None:
    db.add(
        models.MemoryRecord(
            workspace_id=workspace_id,
            project_path=scenario["path"],
            memory_type="showcase_pattern",
            signature=f"{scenario['name']}:{scenario['failure'] or 'stable'}",
            summary=f"Historically, {scenario['name']} requires owner review when {scenario['branch']} changes release-sensitive files.",
            evidence=[scenario["summary"]],
            remediation=[_recommendation_text(scenario)],
            created_at=now,
        )
    )


def _observability(db, workspace_id: int, scenario: dict, index: int, now: datetime) -> None:
    event = models.ObservabilityEvent(
        workspace_id=workspace_id,
        provider="showcase",
        event_uid=f"showcase-alert-{scenario['id']}",
        project_path=scenario["path"],
        service_name=scenario["name"],
        environment="production",
        severity="critical" if scenario["risk"] >= 90 else "high",
        signal_type="deployment_health",
        title=f"{scenario['name']} production health signal",
        message=scenario["summary"],
        metric_name="service_error_rate",
        trace_id=f"trace-{scenario['id']}",
        alert_url=f"https://grafana.example.local/alerts/{scenario['id']}",
        payload={"showcase": True, "failure": scenario["failure"]},
        observed_at=now - timedelta(minutes=index + 4),
        created_at=now,
    )
    correlation = models.IncidentCorrelation(
        workspace_id=workspace_id,
        project_path=scenario["path"],
        title=f"{scenario['name']} deployment risk correlation",
        severity=event.severity,
        status="open",
        summary=scenario["summary"],
        suspected_cause=scenario["summary"],
        confidence=0.82 if scenario["failure"] else 0.55,
        timeline=[{"time": now.isoformat(), "kind": "showcase", "title": event.title, "detail": scenario["summary"], "severity": event.severity, "id": 0}],
        related_observability_event_ids=[],
        related_pipeline_ids=[],
        related_risk_ids=[],
        related_incident_ids=[],
        recommendations=[_recommendation_text(scenario)],
        created_at=now,
        updated_at=now,
    )
    incident = models.IncidentRecord(
        workspace_id=workspace_id,
        project_path=scenario["path"],
        title=f"{scenario['name']} delivery incident",
        severity=event.severity,
        probable_root_cause=scenario["summary"],
        timeline=[{"time": now.isoformat(), "event": "Showcase failure detected"}],
        recommendations=[_recommendation_text(scenario)],
        status="open" if scenario["risk"] >= 80 else "monitoring",
        created_at=now,
    )
    db.add_all([event, correlation, incident])


def _recommendations(db, workspace_id: int, scenario: dict, risk: models.RiskAssessment, insight: models.PipelineInsight, now: datetime) -> list[models.Recommendation]:
    records = [
        models.Recommendation(
            workspace_id=workspace_id,
            project_path=scenario["path"],
            source_type="risk",
            source_id=str(risk.id),
            channel="gitlab_comment",
            message=f"{risk.summary} {_recommendation_text(scenario)}",
            status="dry_run",
            created_at=now,
        ),
        models.Recommendation(
            workspace_id=workspace_id,
            project_path=scenario["path"],
            source_type="pipeline",
            source_id=str(insight.id),
            channel="slack",
            message=f"Pipeline evidence for {scenario['path']}: {scenario['summary']} Next action: {_recommendation_text(scenario)}",
            status="dry_run",
            created_at=now,
        ),
    ]
    db.add_all(records)
    db.flush()
    return records


def _fix_plan(db, workspace_id: int, project: models.GitLabProject, scenario: dict, insight: models.PipelineInsight, now: datetime) -> None:
    target_file = _primary_fix_file(scenario)
    db.add(
        models.FixPlan(
            workspace_id=workspace_id,
            project_id=project.id,
            project_path=project.project_path,
            source_type="pipeline",
            source_id=str(insight.id),
            title=f"Fix {scenario['failure']} in {scenario['name']}",
            summary=scenario["summary"],
            status="draft",
            requires_approval=True,
            fix_type=scenario["failure"],
            base_branch="main",
            branch_name=f"panopticon/fix-{scenario['name']}-{scenario['failure']}",
            merge_request_iid="",
            merge_request_url="",
            plan_payload={
                "files": [{"path": target_file, "commit_action": "update", "purpose": _recommendation_text(scenario), "content": "[showcase generated patch placeholder]"}],
                "diff_preview": [{"path": target_file, "commit_action": "update", "diff": f"@@\n+ # Panopticon suggested fix for {scenario['failure']}\n"}],
                "evidence_bundle": [{"type": "pipeline", "id": insight.pipeline_id, "label": scenario["job"], "summary": scenario["summary"], "file_path": target_file}],
                "validation": {"branch_safe": True, "default_branch_write": False, "approval_required": True, "merge_request_required": True, "diff_preview_available": True, "evidence_count": 1, "evidence_strong": True},
                "test_plan": {"commands": ["pytest", "npm test", "terraform validate"], "executed": False, "execution_note": "Showcase plan only; tests should run in CI after branch creation."},
                "rollback": ["Revert the generated merge request.", "Restore previous deployment configuration if rollout health degrades."],
                "review_checklist": ["Confirm the trace summary matches the failed job.", "Review the diff before branch creation.", "Require owner approval for production-sensitive paths."],
            },
            last_result={},
            error="",
            created_at=now,
            updated_at=now,
        )
    )


def _primary_fix_file(scenario: dict) -> str:
    for path in scenario["files"]:
        if not path.startswith(".") and not path.lower().endswith((".md", ".json", ".lock")):
            return path
    return next(iter(scenario["files"]))


def _recommendation_text(scenario: dict) -> str:
    if scenario["failure"] == "timeout":
        return "Tune the rollout wait boundary, verify readiness probes, and keep rollback steps ready."
    if scenario["failure"] == "test_failure":
        return "Fix the contract or test fixture, then rerun the focused contract test before merge."
    if scenario["failure"] == "auth_or_permission":
        return "Validate rotated OAuth credentials and add an integration test for token refresh."
    if scenario["failure"] == "deployment_failure":
        return "Fix infrastructure syntax, run validation, and require infrastructure owner review."
    if scenario["failure"] == "docker_build":
        return "Regenerate the dependency lockfile and rebuild the image in CI."
    if scenario["failure"] == "dependency_install":
        return "Pin a valid dependency version and rerun dependency installation."
    return "Proceed with review, monitor release metrics, and keep the standard rollback path available."


if __name__ == "__main__":
    main()
