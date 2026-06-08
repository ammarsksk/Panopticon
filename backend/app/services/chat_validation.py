from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app import models


@dataclass(frozen=True)
class ChatValidationResult:
    answer: str
    errors: list[str]
    warnings: list[str]
    used_fallback: bool = False


class ChatValidationService:
    """Final safety pass for agent answers before persistence."""

    def validate(
        self,
        *,
        answer: str,
        deterministic_answer: str,
        intent: str,
        context: dict[str, Any],
        citations: list[dict[str, Any]],
        prepared_actions: list[models.AgentAction],
        prepared_fix_plans: list[models.FixPlan],
    ) -> ChatValidationResult:
        redacted = _ensure_complete(_redact_secret_text(answer))
        fallback = _ensure_complete(_redact_secret_text(deterministic_answer))
        errors: list[str] = []
        warnings: list[str] = []

        if _claims_external_write(redacted) and _only_has_proposals(context, prepared_actions, prepared_fix_plans):
            errors.append("Answer claimed a Slack/GitLab/code write even though only approval-gated proposals exist.")

        if intent == "pipeline_failure" and _overstates_pipeline_root_cause(redacted, context):
            errors.append("Answer named a pipeline root cause without failed-job or parsed insight evidence.")

        unsupported_paths = _unsupported_repo_paths(redacted, context)
        if unsupported_paths:
            warnings.append(f"Answer mentioned path(s) outside indexed repo context: {', '.join(unsupported_paths[:3])}.")

        if errors:
            safe_answer = fallback
            if not _mentions_approval_gate(safe_answer) and (prepared_actions or prepared_fix_plans):
                safe_answer = f"{safe_answer}\n\nSafety note: I prepared reviewable proposal(s) only; nothing has been sent, branched, merged, or executed without approval."
            return ChatValidationResult(answer=safe_answer, errors=errors, warnings=warnings, used_fallback=True)

        if warnings and not _is_failure_notice(redacted):
            redacted = f"{redacted}\n\nValidation note: {warnings[0]}"
        return ChatValidationResult(answer=redacted, errors=errors, warnings=warnings, used_fallback=False)


def _claims_external_write(answer: str) -> bool:
    lowered = answer.lower()
    live_claims = [
        "sent to slack",
        "posted to slack",
        "sent the slack",
        "posted the comment",
        "commented on gitlab",
        "opened a merge request",
        "created a merge request",
        "created the branch",
        "pushed the branch",
        "committed the change",
        "executed the action",
        "deployed the fix",
        "merged the change",
    ]
    return any(claim in lowered for claim in live_claims)


def _only_has_proposals(context: dict[str, Any], prepared_actions: list[models.AgentAction], prepared_fix_plans: list[models.FixPlan]) -> bool:
    action_statuses = {str(action.status) for action in prepared_actions}
    action_statuses.update(str(action.status) for action in context.get("actions", []))
    plan_statuses = {str(plan.status) for plan in prepared_fix_plans}
    plan_statuses.update(str(plan.status) for plan in context.get("fix_plans", []))
    live_statuses = {"sent", "dry_run", "executing", "branch_created", "dry_run_branch_ready", "mr_opened", "dry_run_mr_ready"}
    proposal_statuses = {"pending_approval", "approved", "rejected", "draft"}
    if any(status in live_statuses for status in action_statuses | plan_statuses):
        return False
    return bool((action_statuses | plan_statuses) & proposal_statuses or prepared_actions or prepared_fix_plans)


def _overstates_pipeline_root_cause(answer: str, context: dict[str, Any]) -> bool:
    has_failed_job = bool(context.get("failed_jobs"))
    has_failed_insight = any(getattr(item, "status", "") == "failed" for item in context.get("pipeline_insights", []))
    if has_failed_job or has_failed_insight:
        return False
    failed_pipeline_only = any(getattr(item, "status", "") == "failed" for item in context.get("pipelines", []))
    if not failed_pipeline_only:
        return False
    lowered = answer.lower()
    uncertainty = ["unknown", "cannot determine", "not enough", "no parsed", "specific cause is not proven", "inspect"]
    if any(term in lowered for term in uncertainty):
        return False
    return any(term in lowered for term in ["because", "caused by", "root cause", "failed due to", "likely caused"])


def _unsupported_repo_paths(answer: str, context: dict[str, Any]) -> list[str]:
    supported = {getattr(item, "file_path", "") for item in context.get("repo_files", [])}
    supported = {item.replace("\\", "/") for item in supported if item}
    if not supported:
        return []
    found = {match.replace("\\", "/") for match in re.findall(r"(?<![A-Za-z0-9_/.-])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z0-9]+|(?<![A-Za-z0-9_.-])[\w.-]+\.(?:ya?ml|py|ts|tsx|js|json|md|toml|txt)", answer)}
    allowed_suffixes = {path.rsplit("/", 1)[-1] for path in supported}
    unsupported = []
    for path in found:
        if path in supported or path in allowed_suffixes:
            continue
        if path.startswith("http") or path.startswith("gitlab.com"):
            continue
        unsupported.append(path)
    return sorted(unsupported)


def _mentions_approval_gate(answer: str) -> bool:
    lowered = answer.lower()
    return "approval" in lowered or "approve" in lowered or "requires review" in lowered


def _ensure_complete(answer: str) -> str:
    stripped = answer.strip()
    if not stripped:
        return "I do not have enough stored evidence to answer that safely yet."
    if stripped.endswith((".", "!", "?", "`", "|", "]", ")")):
        return stripped
    return f"{stripped}."


def _is_failure_notice(answer: str) -> bool:
    return "Gemini is configured" in answer or "Gemini live reasoning failed" in answer


def _redact_secret_text(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)\b(client_secret|password|api_key|private_key)\s*=\s*[^\s,;]+", "[REDACTED_SECRET]", text)
    text = re.sub(r"(?i)\b(authorization:\s*bearer)\s+[^\s,;]+", r"\1 [REDACTED_SECRET]", text)
    text = re.sub(r"(?i)\b(xox[baprs]-|glpat-)[A-Za-z0-9_\-]+", "[REDACTED_SECRET]", text)
    text = re.sub(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", "[REDACTED_SECRET]", text, flags=re.DOTALL)
    return text
