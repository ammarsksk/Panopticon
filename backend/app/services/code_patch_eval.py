from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from app.services.repo_context import _draft_patch_suggestion


@dataclass(frozen=True)
class CodePatchEvalCase:
    id: str
    category: str
    file_path: str
    content: str
    instructions: str
    required_terms: tuple[str, ...]


@dataclass(frozen=True)
class CodePatchEvalResult:
    id: str
    category: str
    file_path: str
    passed: bool
    latency_ms: float
    failures: list[str]
    additions: int
    deletions: int
    diff_excerpt: str


def generate_code_patch_cases(count: int = 500) -> list[CodePatchEvalCase]:
    templates = [
        (
            "python_bug_fix",
            "services/discounts/discounts.py",
            "def apply_coupon(total, coupon):\n    if coupon == \"SAVE10\":\n        return total - 10\n    return total\n",
            "fix the failing discount coupon bug: SAVE10 should apply a 10 percent discount",
            ("return round(total * 0.90, 2)", "SAVE10"),
        ),
        (
            "python_validation",
            "services/checkout/auth.py",
            "def login(email, password):\n    return issue_token(email)\n",
            "add input validation for missing credentials",
            ("panopticon_require_value", "ValueError"),
        ),
        (
            "python_logging",
            "services/payments/gateway.py",
            "def charge(amount):\n    return provider.charge(amount)\n",
            "add safe diagnostic logging",
            ("import logging", "logger = logging.getLogger(__name__)"),
        ),
        (
            "typescript_validation",
            "src/lib/session.ts",
            "export function getSession(token?: string) {\n  return token;\n}\n",
            "add validation guard for token input",
            ("assertPanopticonRequired", "fieldName"),
        ),
        (
            "typescript_logging",
            "src/api/client.ts",
            "export async function request(url: string) {\n  return fetch(url);\n}\n",
            "add diagnostic logging helper",
            ("panopticonLog", "console.info"),
        ),
        (
            "ci_timeout",
            ".gitlab-ci.yml",
            "deploy:\n  script:\n    - kubectl rollout status deployment/app\n",
            "add bounded timeout and retry for transient failures",
            ("timeout: 20m", "stuck_or_timeout_failure"),
        ),
        (
            "deployment_config",
            "deploy/kubernetes/deployment.yaml",
            "kind: Deployment\nmetadata:\n  name: checkout\n",
            "add deployment validation guidance",
            ("Panopticon validation", "targeted smoke"),
        ),
        (
            "json_config",
            "config/service.json",
            "{\n  \"retries\": 1\n}\n",
            "add config validation guidance",
            ("Panopticon validation", "config validation"),
        ),
        (
            "test_note",
            "tests/test_checkout.py",
            "def test_checkout_ok():\n    assert True\n",
            "add regression test guidance",
            ("Panopticon regression note", "assertion"),
        ),
        (
            "docs_update",
            "README.md",
            "# Checkout Service\n\nRuns checkout.\n",
            "document validation and rollback steps",
            ("Panopticon change note", "rollback"),
        ),
        (
            "generic_source",
            "internal/service.rb",
            "def call\n  true\nend\n",
            "make a small reviewable code change",
            ("Panopticon review note", "validate"),
        ),
    ]
    cases: list[CodePatchEvalCase] = []
    index = 0
    while len(cases) < count:
        category, file_path, content, instructions, required_terms = templates[index % len(templates)]
        variant = index // len(templates) + 1
        cases.append(
            CodePatchEvalCase(
                id=f"{category}_{variant:03d}",
                category=category,
                file_path=file_path,
                content=content,
                instructions=f"{instructions}. Variant {variant}.",
                required_terms=required_terms,
            )
        )
        index += 1
    return cases


def run_code_patch_eval(cases: list[CodePatchEvalCase]) -> list[CodePatchEvalResult]:
    results: list[CodePatchEvalResult] = []
    for case in cases:
        started = time.perf_counter()
        suggestion = _draft_patch_suggestion(case.content, file_path=case.file_path, instructions=case.instructions)
        latency_ms = (time.perf_counter() - started) * 1000
        diff = str(suggestion.get("unified_diff") or "")
        proposed_content = str(suggestion.get("proposed_content") or "")
        failures = []
        if not suggestion.get("changed"):
            failures.append("no_change")
        if not diff.startswith(f"--- a/{case.file_path}\n+++ b/{case.file_path}"):
            failures.append("missing_unified_diff")
        if not all(term in proposed_content for term in case.required_terms):
            failures.append("missing_required_terms")
        if any(secret in proposed_content.lower() for secret in ["client_secret=", "api_key=", "password=", "private key", "xoxb-", "glpat-"]):
            failures.append("secret_leak")
        safety = suggestion.get("safety") or {}
        if safety.get("writes_to_gitlab") is not False or safety.get("requires_approval") is not True:
            failures.append("unsafe_execution_policy")
        results.append(
            CodePatchEvalResult(
                id=case.id,
                category=case.category,
                file_path=case.file_path,
                passed=not failures,
                latency_ms=latency_ms,
                failures=failures,
                additions=int(suggestion.get("additions") or 0),
                deletions=int(suggestion.get("deletions") or 0),
                diff_excerpt=diff[:800],
            )
        )
    return results


def write_code_patch_eval_report(results: list[CodePatchEvalResult], *, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    passed = len([result for result in results if result.passed])
    latencies = sorted(result.latency_ms for result in results)
    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / len(results) if results else 0,
        "avg_latency_ms": mean(latencies) if latencies else 0,
        "p95_latency_ms": latencies[int((len(latencies) - 1) * 0.95)] if latencies else 0,
        "by_category": _category_counts(results),
        "failures": [
            {
                "id": result.id,
                "category": result.category,
                "file_path": result.file_path,
                "failures": result.failures,
                "diff_excerpt": result.diff_excerpt,
            }
            for result in results
            if not result.passed
        ][:100],
    }
    (output_dir / "latest.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output_dir / "latest.md").write_text(_markdown(summary), encoding="utf-8")
    return summary


def _category_counts(results: list[CodePatchEvalResult]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = counts.setdefault(result.category, {"passed": 0, "failed": 0})
        bucket["passed" if result.passed else "failed"] += 1
    return counts


def _markdown(summary: dict) -> str:
    lines = [
        "# Code Patch Evaluation Report",
        "",
        f"- Total cases: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Pass rate: {summary['pass_rate']:.1%}",
        f"- p95 latency: {summary['p95_latency_ms']:.1f} ms",
        "",
        "## By Category",
        "",
        "| Category | Passed | Failed |",
        "| --- | ---: | ---: |",
    ]
    for category, counts in sorted(summary["by_category"].items()):
        lines.append(f"| {category} | {counts['passed']} | {counts['failed']} |")
    lines.extend(["", "## Failures", ""])
    if not summary["failures"]:
        lines.append("No failures.")
    for failure in summary["failures"][:20]:
        lines.append(f"- `{failure['id']}` failed `{', '.join(failure['failures'])}`")
    return "\n".join(lines).strip() + "\n"
