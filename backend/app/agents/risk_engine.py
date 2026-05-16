from dataclasses import dataclass


SENSITIVE_PATTERNS = (
    ".env",
    "secrets",
    "auth",
    "payment",
    "checkout",
    "database",
    "migration",
    "terraform",
    "kubernetes",
    "helm",
    "dockerfile",
    "requirements",
    "package-lock",
)

INFRA_PATTERNS = ("terraform", ".tf", "k8s", "kubernetes", "helm", "deployment.yaml", "dockerfile")
TEST_PATTERNS = ("test_", "_test.", ".spec.", ".test.", "/tests/")


@dataclass(frozen=True)
class RiskResult:
    score: float
    level: str
    summary: str
    reasons: list[str]
    recommendations: list[str]


def _changed_files(payload: dict) -> list[str]:
    attrs = payload.get("object_attributes", {})
    files = payload.get("changed_files") or attrs.get("changed_files") or payload.get("changes", {}).get("files", [])
    normalized: list[str] = []
    for item in files:
        if isinstance(item, str):
            normalized.append(item.lower())
        elif isinstance(item, dict):
            path = item.get("new_path") or item.get("old_path") or item.get("path")
            if path:
                normalized.append(str(path).lower())
    return normalized


def assess_deployment_risk(payload: dict, historical_failure_count: int = 0) -> RiskResult:
    files = _changed_files(payload)
    reasons: list[str] = []
    recommendations: list[str] = []
    score = 20.0

    if not files:
        reasons.append("No changed-file context was provided, so confidence is limited.")
        score += 10

    sensitive_matches = [path for path in files if any(pattern in path for pattern in SENSITIVE_PATTERNS)]
    if sensitive_matches:
        score += min(30, 8 * len(sensitive_matches))
        reasons.append(f"Sensitive operational files changed: {', '.join(sensitive_matches[:4])}.")
        recommendations.append("Require an owner review for the sensitive service or configuration area.")

    infra_matches = [path for path in files if any(pattern in path for pattern in INFRA_PATTERNS)]
    if infra_matches:
        score += min(25, 10 * len(infra_matches))
        reasons.append("Infrastructure or deployment configuration changed.")
        recommendations.append("Run infrastructure validation and confirm rollback steps before deployment.")

    test_matches = [path for path in files if any(pattern in path for pattern in TEST_PATTERNS)]
    if files and not test_matches:
        score += 15
        reasons.append("No obvious test file changes were included with the operational change.")
        recommendations.append("Add or confirm automated coverage for the touched service path.")

    if historical_failure_count:
        score += min(20, historical_failure_count * 6)
        reasons.append(f"{historical_failure_count} related historical failure records exist in operational memory.")
        recommendations.append("Compare this change against previous remediation notes before release.")

    score = min(score, 100)
    if score >= 80:
        level = "critical"
    elif score >= 60:
        level = "high"
    elif score >= 35:
        level = "medium"
    else:
        level = "low"

    if not recommendations:
        recommendations.append("Proceed with normal review and pipeline validation.")

    summary = f"Deployment risk is {level} at {round(score)}/100."
    return RiskResult(score=round(score, 1), level=level, summary=summary, reasons=reasons, recommendations=recommendations)

