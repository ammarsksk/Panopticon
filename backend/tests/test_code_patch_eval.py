from app.services.code_patch_eval import generate_code_patch_cases, run_code_patch_eval
from app.services.repo_context import _draft_patch_suggestion


def test_code_patch_eval_generates_500_cases_and_passes():
    cases = generate_code_patch_cases(500)
    results = run_code_patch_eval(cases)

    assert len(cases) == 500
    assert len(results) == 500
    assert all(result.passed for result in results)
    assert {case.category for case in cases} >= {
        "python_validation",
        "python_bug_fix",
        "python_inventory_bug_fix",
        "python_shipping_bug_fix",
        "python_http_robustness",
        "python_config_robustness",
        "python_retry_robustness",
        "python_logging",
        "typescript_validation",
        "typescript_logging",
        "ci_timeout",
        "deployment_config",
        "json_config",
        "test_note",
        "docs_update",
        "generic_source",
    }


def test_draft_patch_returns_concrete_diff_and_policy_for_normal_code_change():
    result = _draft_patch_suggestion(
        "export function getSession(token?: string) {\n  return token;\n}\n",
        file_path="src/lib/session.ts",
        instructions="add a validation guard for missing token",
    )

    assert result["changed"] is True
    assert result["safety"]["requires_approval"] is True
    assert result["safety"]["writes_to_gitlab"] is False
    assert "assertPanopticonRequired" in result["proposed_content"]
    assert "--- a/src/lib/session.ts" in result["unified_diff"]
    assert "+++ b/src/lib/session.ts" in result["unified_diff"]
    assert "+export function assertPanopticonRequired" in result["unified_diff"]


def test_draft_patch_fixes_real_discount_bug_from_failing_test_request():
    result = _draft_patch_suggestion(
        "def apply_coupon(total, coupon):\n    if coupon == \"SAVE10\":\n        return total - 10\n    return total\n",
        file_path="services/discounts/discounts.py",
        instructions="fix the failing discount coupon bug: SAVE10 should apply a 10 percent discount",
    )

    assert result["changed"] is True
    assert "return round(total * 0.90, 2)" in result["proposed_content"]
    assert "-        return total - 10" in result["unified_diff"]
    assert "+        return round(total * 0.90, 2)" in result["unified_diff"]


def test_draft_patch_fixes_multiple_known_source_bug_patterns():
    inventory = _draft_patch_suggestion(
        "def reserve_stock(available, requested):\n    return available - requested\n",
        file_path="services/inventory/reservations.py",
        instructions="fix all failing inventory reservation tests",
    )
    shipping = _draft_patch_suggestion(
        "def estimate_delivery_days(country, expedited=False):\n    if expedited:\n        return 2\n    return 5\n",
        file_path="services/shipping/estimate.py",
        instructions="fix all failing shipping estimate tests",
    )
    http = _draft_patch_suggestion(
        "def fetch_status(url, client):\n    return client.get(url)\n",
        file_path="services/platform/http_client.py",
        instructions="make the project more robust by adding network timeouts",
    )
    retry = _draft_patch_suggestion(
        "def call_with_retry(fn, attempts=3):\n    return fn()\n",
        file_path="services/platform/retry.py",
        instructions="make transient dependency calls more robust with retry handling",
    )

    assert "requested quantity must be positive" in inventory["proposed_content"]
    assert "return 1 if expedited else 3" in shipping["proposed_content"]
    assert "client.get(url, timeout=5)" in http["proposed_content"]
    assert "for _attempt in range" in retry["proposed_content"]
