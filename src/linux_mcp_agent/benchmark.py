from __future__ import annotations

import math
from typing import Any


def calculate_percentile(samples: list[float], percentile: float) -> float | None:
    """Return a nearest-rank percentile in milliseconds, or None for no samples."""
    if not 0 <= percentile <= 1:
        raise ValueError("percentile must be between 0 and 1")
    if not samples:
        return None

    ordered = sorted(samples)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def evaluate_tool_acceptance(
    samples_ms: list[float],
    *,
    errors: int,
    requested_samples: int,
    minimum_successful_samples: int,
    minimum_success_rate_percent: float,
    p95_target_ms: float,
) -> dict[str, Any]:
    """Evaluate sample coverage, error count, success rate and p95 latency."""
    successful = len(samples_ms)
    success_rate = (successful / requested_samples) * 100 if requested_samples else 0.0
    p95 = calculate_percentile(samples_ms, 0.95)
    reasons: list[str] = []

    if successful < minimum_successful_samples:
        reasons.append(
            f"successful samples {successful} < minimum {minimum_successful_samples}"
        )
    if success_rate < minimum_success_rate_percent:
        reasons.append(
            f"success rate {success_rate:.2f}% < minimum {minimum_success_rate_percent:.2f}%"
        )
    if errors:
        reasons.append(f"{errors} request(s) failed")
    if p95 is None:
        reasons.append("p95 is unavailable because there are no successful samples")
    elif p95 > p95_target_ms:
        reasons.append(f"p95 {p95:.3f} ms > target {p95_target_ms:.3f} ms")

    return {
        "successRatePercent": round(success_rate, 2),
        "p95TargetMs": round(p95_target_ms, 3),
        "minimumSuccessfulSamples": minimum_successful_samples,
        "minimumSuccessRatePercent": round(minimum_success_rate_percent, 2),
        "acceptancePassed": not reasons,
        "acceptanceReasons": reasons,
    }
