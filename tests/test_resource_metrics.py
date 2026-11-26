from __future__ import annotations

from pathlib import Path

from linux_mcp_agent.resource_metrics import get_resource_pressure


def _write_psi_files(root: Path) -> None:
    (root / "cpu").write_text(
        "some avg10=1.25 avg60=0.50 avg300=0.10 total=12000\n",
        encoding="ascii",
    )
    (root / "memory").write_text(
        "some avg10=2.00 avg60=1.00 avg300=0.25 total=24000\n"
        "full avg10=0.10 avg60=0.05 avg300=0.01 total=500\n",
        encoding="ascii",
    )
    (root / "io").write_text(
        "some avg10=3.00 avg60=2.00 avg300=1.00 total=36000\n"
        "full avg10=0.20 avg60=0.10 avg300=0.02 total=900\n",
        encoding="ascii",
    )


def test_resource_pressure_parses_cpu_memory_and_io_psi(tmp_path: Path) -> None:
    _write_psi_files(tmp_path)

    result = get_resource_pressure(tmp_path)

    assert result["status"] == "ok"
    assert result["availableResourceCount"] == 3
    assert result["resources"]["cpu"]["pressure"]["some"]["avg10Percent"] == 1.25
    assert result["resources"]["memory"]["pressure"]["full"]["totalStallMicroseconds"] == 500
    assert result["resources"]["io"]["pressure"]["some"]["avg300Percent"] == 1.0
    assert result["timestamp"].endswith("+00:00")


def test_resource_pressure_reports_partial_support(tmp_path: Path) -> None:
    (tmp_path / "cpu").write_text(
        "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
        encoding="ascii",
    )

    result = get_resource_pressure(tmp_path)

    assert result["status"] == "partial"
    assert result["availableResourceCount"] == 1
    assert result["resources"]["memory"]["status"] == "unavailable"
    assert result["resources"]["io"]["status"] == "unavailable"


def test_resource_pressure_rejects_malformed_or_impossible_psi_values(
    tmp_path: Path,
) -> None:
    for name in ("cpu", "memory", "io"):
        (tmp_path / name).write_text(
            "some avg10=101 avg60=0 avg300=0 total=12\n",
            encoding="ascii",
        )

    result = get_resource_pressure(tmp_path)

    assert result["status"] == "unavailable"
    assert all(
        item["status"] == "invalid-data"
        for item in result["resources"].values()
    )
    assert all(not item["pressure"] for item in result["resources"].values())
