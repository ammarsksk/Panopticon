from dataclasses import dataclass


@dataclass(frozen=True)
class MRSignalResult:
    bottleneck_level: str
    summary: str


def detect_bottleneck(*, age_hours: float, unresolved_threads: int, reviewer_count: int, state: str) -> MRSignalResult:
    if state not in {"opened", "open"}:
        return MRSignalResult("healthy", "Merge request is not currently open.")

    if unresolved_threads >= 3:
        return MRSignalResult("blocked", "Merge request has multiple unresolved review threads.")

    if age_hours >= 48 and reviewer_count == 0:
        return MRSignalResult("blocked", "Merge request has been open for more than 48 hours without reviewers.")

    if age_hours >= 24:
        return MRSignalResult("stale", "Merge request has been inactive long enough to risk delivery delay.")

    if reviewer_count == 0:
        return MRSignalResult("needs_review", "Merge request is open but has no assigned reviewers.")

    return MRSignalResult("healthy", "Merge request flow looks healthy.")

