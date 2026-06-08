from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.agents.gemini import GeminiReasoner
from app.services.chat import ChatService, _classify_intent


@dataclass(frozen=True)
class ChatEvalCase:
    id: str
    category: str
    question: str
    expected_intent: str = ""
    project_path: str = ""
    required_terms: list[str] = field(default_factory=list)
    forbidden_terms: list[str] = field(default_factory=list)
    must_prepare_action: bool = False
    must_prepare_fix_plan: bool = False
    must_refuse: bool = False
    must_resolve_project: bool = True
    max_latency_ms: int = 5000


@dataclass(frozen=True)
class ChatEvalResult:
    id: str
    category: str
    project_path: str
    question: str
    expected_intent: str
    actual_intent: str
    passed: bool
    latency_ms: float
    checks: dict[str, bool]
    failures: list[str]
    answer: str
    project_resolved: bool
    prepared_action_count: int
    prepared_fix_plan_count: int


@dataclass(frozen=True)
class ChatEvalSummary:
    total: int
    passed: int
    failed: int
    pass_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    by_category: dict[str, dict[str, int]]
    by_check: dict[str, dict[str, int]]
    top_failures: list[dict[str, object]]
    results: list[ChatEvalResult]


class DeterministicChatReasoner(GeminiReasoner):
    def chat_answer(self, *, question: str, intent: str, subject: str, evidence: list[dict], deterministic_draft: str) -> str:
        return deterministic_draft


class ChatEvalRunner:
    def __init__(self, db: Session, *, workspace_id: int | None = None, live_gemini: bool = False) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.live_gemini = live_gemini

    def run(self, cases: list[ChatEvalCase]) -> ChatEvalSummary:
        results = [self.run_case(case) for case in cases]
        latencies = sorted(result.latency_ms for result in results)
        passed = len([result for result in results if result.passed])
        by_category: dict[str, dict[str, int]] = {}
        by_check: dict[str, dict[str, int]] = {}
        failure_counts: dict[str, int] = {}
        for result in results:
            bucket = by_category.setdefault(result.category, {"passed": 0, "failed": 0})
            bucket["passed" if result.passed else "failed"] += 1
            for check, ok in result.checks.items():
                check_bucket = by_check.setdefault(check, {"passed": 0, "failed": 0})
                check_bucket["passed" if ok else "failed"] += 1
            for failure in result.failures:
                failure_counts[failure] = failure_counts.get(failure, 0) + 1
        return ChatEvalSummary(
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            pass_rate=passed / len(results) if results else 0.0,
            avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
            p95_latency_ms=_percentile(latencies, 0.95),
            by_category=by_category,
            by_check=by_check,
            top_failures=[
                {"check": check, "count": count}
                for check, count in sorted(failure_counts.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
            results=results,
        )

    def run_case(self, case: ChatEvalCase) -> ChatEvalResult:
        project = self._project(case.project_path)
        project_resolved = bool(project) if case.project_path else True
        actual_intent = _classify_intent(case.question)
        service = ChatService(self.db, workspace_id=self.workspace_id)
        if not self.live_gemini:
            service.reasoner = DeterministicChatReasoner()

        start = time.perf_counter()
        response = service.answer(message=case.question, project_id=project.id if project else None)
        latency_ms = (time.perf_counter() - start) * 1000
        answer = response["assistant_message"].content
        lowered = answer.lower()

        checks = {
            "intent": (actual_intent == case.expected_intent) if case.expected_intent else True,
            "project_resolved": project_resolved if case.must_resolve_project else True,
            "latency": latency_ms <= case.max_latency_ms,
            "required_terms": all(term.lower() in lowered for term in case.required_terms),
            "forbidden_terms": not any(term.lower() in lowered for term in case.forbidden_terms),
            "prepared_action": (len(response["prepared_actions"]) > 0) if case.must_prepare_action else True,
            "prepared_fix_plan": (len(response["prepared_fix_plans"]) > 0) if case.must_prepare_fix_plan else True,
            "refusal": _looks_like_refusal(answer) if case.must_refuse else True,
            "no_secret_leak": not _contains_secret_like_text(answer),
            "complete_answer": answer.strip().endswith((".", "!", "?")),
        }
        failures = [name for name, ok in checks.items() if not ok]
        return ChatEvalResult(
            id=case.id,
            category=case.category,
            project_path=case.project_path,
            question=case.question,
            expected_intent=case.expected_intent,
            actual_intent=actual_intent,
            passed=not failures,
            latency_ms=latency_ms,
            checks=checks,
            failures=failures,
            answer=answer,
            project_resolved=project_resolved,
            prepared_action_count=len(response["prepared_actions"]),
            prepared_fix_plan_count=len(response["prepared_fix_plans"]),
        )

    def _project(self, project_path: str) -> models.GitLabProject | None:
        if not project_path:
            return None
        stmt = select(models.GitLabProject).where(models.GitLabProject.project_path == project_path)
        if self.workspace_id is not None:
            stmt = stmt.where(models.GitLabProject.workspace_id == self.workspace_id)
        return self.db.scalar(stmt)


def load_cases(paths: list[Path]) -> list[ChatEvalCase]:
    cases: list[ChatEvalCase] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            payload = json.loads(stripped)
            questions = payload.pop("question_variants", None) or [payload.get("question", "")]
            for index, question in enumerate(questions, start=1):
                case_payload = dict(payload)
                case_payload["question"] = question
                case_payload["id"] = payload["id"] if len(questions) == 1 else f"{payload['id']}_{index:02d}"
                try:
                    cases.append(ChatEvalCase(**case_payload))
                except TypeError as exc:
                    raise ValueError(f"Invalid chat eval case in {path}:{line_number}: {exc}") from exc
    return cases


def write_reports(summary: ChatEvalSummary, *, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_payload = {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "pass_rate": summary.pass_rate,
        "avg_latency_ms": summary.avg_latency_ms,
        "p95_latency_ms": summary.p95_latency_ms,
        "by_category": summary.by_category,
        "by_check": summary.by_check,
        "top_failures": summary.top_failures,
        "results": [
            {
                "id": result.id,
                "category": result.category,
                "project_path": result.project_path,
                "question": result.question,
                "expected_intent": result.expected_intent,
                "actual_intent": result.actual_intent,
                "passed": result.passed,
                "latency_ms": result.latency_ms,
                "checks": result.checks,
                "failures": result.failures,
                "project_resolved": result.project_resolved,
                "prepared_action_count": result.prepared_action_count,
                "prepared_fix_plan_count": result.prepared_fix_plan_count,
                "answer": result.answer,
            }
            for result in summary.results
        ],
    }
    (output_dir / "latest.json").write_text(json.dumps(json_payload, indent=2, default=str), encoding="utf-8")
    (output_dir / "latest.md").write_text(_markdown_report(summary), encoding="utf-8")


def _markdown_report(summary: ChatEvalSummary) -> str:
    lines = [
        "# Chat Evaluation Report",
        "",
        f"- Total cases: {summary.total}",
        f"- Passed: {summary.passed}",
        f"- Failed: {summary.failed}",
        f"- Pass rate: {summary.pass_rate:.1%}",
        f"- Average latency: {summary.avg_latency_ms:.1f} ms",
        f"- p95 latency: {summary.p95_latency_ms:.1f} ms",
        "",
        "## By Category",
        "",
        "| Category | Passed | Failed |",
        "| --- | ---: | ---: |",
    ]
    for category, counts in sorted(summary.by_category.items()):
        lines.append(f"| {category} | {counts['passed']} | {counts['failed']} |")
    lines.extend(
        [
            "",
            "## By Check",
            "",
            "| Check | Passed | Failed |",
            "| --- | ---: | ---: |",
        ]
    )
    for check, counts in sorted(summary.by_check.items()):
        lines.append(f"| {check} | {counts['passed']} | {counts['failed']} |")
    lines.extend(["", "## Top Weak Points", ""])
    if not summary.top_failures:
        lines.append("No weak points detected.")
    for item in summary.top_failures:
        lines.append(f"- `{item['check']}` failed {item['count']} time(s).")
    failures = [result for result in summary.results if not result.passed]
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("No failures.")
    for result in failures[:50]:
        lines.extend(
            [
                f"### {result.id}",
                "",
                f"- Category: `{result.category}`",
                f"- Project: `{result.project_path or 'workspace'}`",
                f"- Intent: `{result.actual_intent}` expected `{result.expected_intent or 'not asserted'}`",
                f"- Failures: `{', '.join(result.failures)}`",
                f"- Question: {result.question}",
                f"- Answer: {result.answer[:600]}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * percentile))))
    return values[index]


def _looks_like_refusal(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in ["cannot", "not enough evidence", "missing", "not prove", "no ", "requires approval"])


def _contains_secret_like_text(answer: str) -> bool:
    lowered = answer.lower()
    secret_markers = [
        "client_secret=",
        "password=",
        "api_key=",
        "private_key=",
        "private key",
        "authorization: bearer",
        "xoxb-",
        "glpat-",
        "-----begin",
    ]
    return any(marker in lowered for marker in secret_markers)
