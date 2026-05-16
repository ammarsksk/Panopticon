from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class IncidentAnalysis:
    title: str
    severity: str
    probable_root_cause: str
    timeline: list[dict]
    recommendations: list[str]


def build_incident_analysis(payload: dict, related_event_titles: list[str]) -> IncidentAnalysis:
    project = payload.get("project", {}).get("path_with_namespace") or payload.get("project_path") or "unknown project"
    attrs = payload.get("object_attributes", {})
    status = attrs.get("status") or payload.get("status") or "unknown"
    ref = attrs.get("ref") or payload.get("ref") or attrs.get("environment") or "unknown ref"
    now = datetime.now(timezone.utc).isoformat()

    timeline = [
        {"time": now, "event": f"Incident signal received for {project} on {ref} with status {status}."},
    ]
    for title in related_event_titles[:5]:
        timeline.append({"time": now, "event": f"Related operational context: {title}"})

    root_cause = "Recent deployment or rollback activity is the leading correlation signal."
    if related_event_titles:
        root_cause = f"Recent deployment activity correlates with prior signals: {related_event_titles[0]}"

    return IncidentAnalysis(
        title=f"Operational incident detected for {project}",
        severity="critical" if status in {"failed", "rollback", "rolled_back"} else "high",
        probable_root_cause=root_cause,
        timeline=timeline,
        recommendations=[
            "Freeze further deployments for the affected service until the incident is triaged.",
            "Compare the deployment commit range with pipeline failures and rollback history.",
            "Prepare rollback if customer-facing error rates continue to rise.",
        ],
    )

