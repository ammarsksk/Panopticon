from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app import models
from app.actions.dispatcher import ActionDispatcher
from app.agents.ci_failure import analyze_pipeline_failure
from app.agents.gemini import GeminiReasoner
from app.agents.incidents import build_incident_analysis
from app.agents.mr_coordination import detect_bottleneck
from app.agents.risk_engine import assess_deployment_risk
from app.integrations.gitlab import GitLabClient, enrich_payload_from_gitlab, event_type_from_payload, project_path_from_payload, title_from_payload
from app.memory.repository import OperationalMemory


def _hours_since(timestamp: str | None) -> float:
    if not timestamp:
        return 0
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, (datetime.now(timezone.utc) - parsed).total_seconds() / 3600)


def _historical_match_count(memory: OperationalMemory, project_path: str) -> int:
    return len(memory.recent_failures(project_path))


def _payload_with_pipeline_logs(payload: dict, project_path: str) -> dict:
    if payload.get("build_log") or payload.get("pipeline_log") or payload.get("logs"):
        return payload

    attrs = payload.get("object_attributes", {})
    pipeline_id = str(attrs.get("id") or attrs.get("iid") or "")
    if not pipeline_id:
        return payload

    client = GitLabClient()
    if not client.configured:
        return payload

    jobs = client.get_pipeline_jobs(project_path, pipeline_id)
    failed_jobs = [job for job in jobs if isinstance(job, dict) and job.get("status") == "failed"]
    traces: list[str] = []
    for job in failed_jobs[:3]:
        job_id = str(job.get("id") or "")
        if job_id:
            trace = client.get_job_trace(project_path, job_id)
            if trace:
                traces.append(trace[-8000:])

    if not traces:
        return payload

    enriched = dict(payload)
    enriched["build_log"] = "\n".join(traces)
    enriched["builds"] = failed_jobs
    return enriched


def process_gitlab_event(payload: dict, db: Session, event_uid: str | None = None) -> dict:
    payload = enrich_payload_from_gitlab(payload)
    memory = OperationalMemory(db)
    dispatcher = ActionDispatcher(db)
    reasoner = GeminiReasoner()
    event_type = event_type_from_payload(payload)
    project_path = project_path_from_payload(payload)

    if event_uid:
        existing_receipt = memory.get_webhook_receipt(event_uid)
        if existing_receipt and existing_receipt.status == "processed":
            return {
                "event_id": existing_receipt.created_event_id,
                "risk_id": None,
                "pipeline_insight_id": None,
                "incident_id": None,
                "mr_signal_id": None,
                "duplicate": True,
            }
        receipt = existing_receipt or memory.add_webhook_receipt(event_uid=event_uid, event_type=event_type, project_path=project_path)
    else:
        receipt = None

    if event_type.startswith("pipeline.") and event_type.endswith(".failed"):
        payload = _payload_with_pipeline_logs(payload, project_path)
    title = title_from_payload(payload)
    severity = "info"
    if ".failed" in event_type or "rollback" in event_type:
        severity = "high"

    event = memory.add_event(
        event_type=event_type,
        project_path=project_path,
        title=title,
        severity=severity,
        payload=payload,
    )
    if receipt:
        memory.mark_webhook_processed(receipt, event.id)

    created: dict[str, int | bool | None] = {"event_id": event.id, "risk_id": None, "pipeline_insight_id": None, "incident_id": None, "mr_signal_id": None, "duplicate": False}
    historical_count = _historical_match_count(memory, project_path)

    if event_type.startswith("merge_request."):
        attrs = payload.get("object_attributes", {})
        risk = assess_deployment_risk(payload, historical_count)
        risk_row = memory.add_risk(
            event_id=event.id,
            project_path=project_path,
            merge_request_iid=str(attrs.get("iid") or attrs.get("id") or ""),
            deployment_ref=str(attrs.get("source_branch") or attrs.get("target_branch") or ""),
            score=risk.score,
            level=risk.level,
            summary=risk.summary,
            reasons=risk.reasons,
            recommendations=risk.recommendations,
        )
        created["risk_id"] = risk_row.id
        reasoning_note = reasoner.summarize(
            task="deployment_risk",
            context={"project_path": project_path, "reasons": risk.reasons, "recommendations": risk.recommendations},
        )
        risk_recommendation = memory.add_recommendation(
            project_path=project_path,
            source_type="risk",
            source_id=str(risk_row.id),
            channel="gitlab_comment",
            message=f"{risk.summary} {' '.join(risk.recommendations)}\n\nVertex Gemini analysis:\n{reasoning_note}",
        )
        dispatcher.dispatch(risk_recommendation, {"merge_request_iid": str(attrs.get("iid") or attrs.get("id") or "")})

        reviewers = attrs.get("reviewers") or payload.get("reviewers") or []
        signal = detect_bottleneck(
            age_hours=_hours_since(attrs.get("created_at")),
            unresolved_threads=int(attrs.get("unresolved_discussions_count") or payload.get("unresolved_threads") or 0),
            reviewer_count=len(reviewers),
            state=str(attrs.get("state") or "opened"),
        )
        signal_row = memory.add_mr_signal(
            project_path=project_path,
            merge_request_iid=str(attrs.get("iid") or attrs.get("id") or ""),
            title=str(attrs.get("title") or title),
            state=str(attrs.get("state") or "opened"),
            age_hours=_hours_since(attrs.get("created_at")),
            unresolved_threads=int(attrs.get("unresolved_discussions_count") or payload.get("unresolved_threads") or 0),
            reviewer_count=len(reviewers),
            bottleneck_level=signal.bottleneck_level,
            summary=signal.summary,
        )
        created["mr_signal_id"] = signal_row.id

    if event_type.startswith("pipeline.") and event_type.endswith(".failed"):
        attrs = payload.get("object_attributes", {})
        analysis = analyze_pipeline_failure(payload, historical_count)
        insight = memory.add_pipeline_insight(
            event_id=event.id,
            project_path=project_path,
            pipeline_id=str(attrs.get("id") or attrs.get("iid") or ""),
            status="failed",
            likely_cause=analysis.likely_cause,
            evidence=analysis.evidence,
            recommendations=analysis.recommendations,
        )
        created["pipeline_insight_id"] = insight.id
        reasoning_note = reasoner.summarize(
            task="pipeline_failure_analysis",
            context={"project_path": project_path, "evidence": analysis.evidence, "recommendations": analysis.recommendations},
        )
        memory.add_memory(
            project_path=project_path,
            memory_type="pipeline_failure",
            signature=analysis.likely_cause[:240],
            summary=analysis.likely_cause,
            evidence=analysis.evidence,
            remediation=analysis.recommendations,
        )
        pipeline_recommendation = memory.add_recommendation(
            project_path=project_path,
            source_type="pipeline",
            source_id=str(insight.id),
            channel="slack",
            message=f"Pipeline failure detected: {analysis.likely_cause}\n\nVertex Gemini analysis:\n{reasoning_note}",
        )
        dispatcher.dispatch(pipeline_recommendation)

    if event_type.startswith("deployment.") and (event_type.endswith(".failed") or event_type.endswith(".rollback") or event_type.endswith(".rolled_back")):
        recent_titles = list(
            db.scalars(
                select(models.OperationalEvent.title)
                .where(models.OperationalEvent.project_path == project_path)
                .order_by(desc(models.OperationalEvent.created_at))
                .limit(5)
            )
        )
        analysis = build_incident_analysis(payload, recent_titles)
        incident = memory.add_incident(
            event_id=event.id,
            project_path=project_path,
            title=analysis.title,
            severity=analysis.severity,
            probable_root_cause=analysis.probable_root_cause,
            timeline=analysis.timeline,
            recommendations=analysis.recommendations,
        )
        created["incident_id"] = incident.id
        reasoning_note = reasoner.summarize(
            task="incident_timeline",
            context={"project_path": project_path, "evidence": [entry["event"] for entry in analysis.timeline]},
        )
        memory.add_memory(
            project_path=project_path,
            memory_type="incident",
            signature=analysis.probable_root_cause[:240],
            summary=analysis.probable_root_cause,
            evidence=[entry["event"] for entry in analysis.timeline],
            remediation=analysis.recommendations,
        )
        incident_recommendation = memory.add_recommendation(
            project_path=project_path,
            source_type="incident",
            source_id=str(incident.id),
            channel="slack",
            message=f"{analysis.title}: {analysis.probable_root_cause}\n\nVertex Gemini analysis:\n{reasoning_note}",
        )
        dispatcher.dispatch(incident_recommendation)

    db.commit()
    return created
