from app.agents.ci_failure import analyze_pipeline_failure
from app.agents.mr_coordination import detect_bottleneck
from app.agents.risk_engine import assess_deployment_risk


def test_deployment_risk_flags_sensitive_infra_without_tests():
    result = assess_deployment_risk(
        {
            "changed_files": [
                "services/checkout/auth.py",
                "infrastructure/terraform/main.tf",
                "Dockerfile",
            ]
        },
        historical_failure_count=2,
    )

    assert result.score >= 80
    assert result.level == "critical"
    assert any("Sensitive" in reason for reason in result.reasons)


def test_pipeline_failure_detects_docker_signature():
    result = analyze_pipeline_failure({"build_log": "Docker build failed after image size increased"})

    assert "Docker" in result.likely_cause
    assert result.recommendations


def test_mr_bottleneck_detects_unreviewed_old_merge_request():
    result = detect_bottleneck(age_hours=60, unresolved_threads=0, reviewer_count=0, state="opened")

    assert result.bottleneck_level == "blocked"

