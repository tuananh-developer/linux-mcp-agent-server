from __future__ import annotations

from scripts.benchmark_mcp import _evaluate_tool, _percentile


def test_percentile_uses_nearest_rank() -> None:
    assert _percentile([40.0, 10.0, 30.0, 20.0], 0.95) == 40.0


def test_tool_acceptance_requires_complete_success_and_target_p95() -> None:
    result = _evaluate_tool(
        [100.0, 200.0, 300.0, 400.0],
        errors=0,
        requested_samples=4,
        minimum_successful_samples=4,
        minimum_success_rate_percent=100.0,
        p95_target_ms=500.0,
    )

    assert result["acceptancePassed"] is True
    assert result["successRatePercent"] == 100.0
    assert result["p95TargetMs"] == 500.0
    assert result["acceptanceReasons"] == []


def test_tool_acceptance_fails_when_any_request_errors() -> None:
    result = _evaluate_tool(
        [100.0, 200.0, 300.0],
        errors=1,
        requested_samples=4,
        minimum_successful_samples=3,
        minimum_success_rate_percent=95.0,
        p95_target_ms=500.0,
    )

    assert result["acceptancePassed"] is False
    assert result["successRatePercent"] == 75.0
    assert any("request(s) failed" in item for item in result["acceptanceReasons"])


def test_tool_acceptance_fails_when_p95_exceeds_target() -> None:
    result = _evaluate_tool(
        [100.0, 3000.0],
        errors=0,
        requested_samples=2,
        minimum_successful_samples=2,
        minimum_success_rate_percent=100.0,
        p95_target_ms=2000.0,
    )

    assert result["acceptancePassed"] is False
    assert any("p95" in item for item in result["acceptanceReasons"])
