from dataclasses import dataclass


ERROR_SIGNATURES = {
    "timeout": ("Pipeline job timed out or exceeded an external service wait limit.", "Increase timeout only after checking dependency latency and artifact size."),
    "no space left": ("Runner disk exhaustion or oversized build artifacts.", "Prune build artifacts and review dependency or Docker layer growth."),
    "out of memory": ("Build or test job exceeded memory limits.", "Inspect recent dependency changes and tune runner memory or test parallelism."),
    "connection refused": ("A dependent service was unavailable during CI.", "Check service container startup order, network aliases, and health checks."),
    "npm err": ("Node package installation or script execution failed.", "Review package-lock changes and the failing npm lifecycle script."),
    "migration": ("Database migration or schema validation failure.", "Run migration checks against a clean database and review rollback safety."),
    "docker": ("Docker build or image publishing failure.", "Inspect Dockerfile changes, layer size, registry auth, and base image availability."),
}


@dataclass(frozen=True)
class PipelineAnalysis:
    likely_cause: str
    evidence: list[str]
    recommendations: list[str]


def _collect_log_text(payload: dict) -> str:
    fields = [
        payload.get("build_log"),
        payload.get("pipeline_log"),
        payload.get("logs"),
        payload.get("object_attributes", {}).get("failure_reason"),
    ]
    builds = payload.get("builds") or []
    for build in builds:
        if isinstance(build, dict):
            fields.extend([build.get("failure_reason"), build.get("name"), build.get("stage")])
    return "\n".join(str(item) for item in fields if item).lower()


def analyze_pipeline_failure(payload: dict, historical_matches: int = 0) -> PipelineAnalysis:
    text = _collect_log_text(payload)
    evidence: list[str] = []
    recommendations: list[str] = []

    for signature, (cause, recommendation) in ERROR_SIGNATURES.items():
        if signature in text:
            evidence.append(f"Matched CI failure signature: {signature}.")
            recommendations.append(recommendation)
            if historical_matches:
                evidence.append(f"{historical_matches} similar historical failure records were found.")
                recommendations.append("Reuse prior remediation notes if the failing stage and signature match.")
            return PipelineAnalysis(cause, evidence, recommendations)

    if historical_matches:
        return PipelineAnalysis(
            "Pipeline failed with a pattern similar to previous operational memory records.",
            [f"{historical_matches} related historical records exist."],
            ["Compare failing stage, commit range, and recent dependency changes with prior remediations."],
        )

    return PipelineAnalysis(
        "Pipeline failed, but no known failure signature was detected in the provided payload.",
        ["Webhook payload did not include enough log detail for a precise diagnosis."],
        ["Fetch full job logs from GitLab and rerun analysis with complete failure output."],
    )

