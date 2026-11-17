from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from linux_mcp_agent.system import (
    NotAllowedError,
    get_disk_usage,
    get_system_metrics,
    list_processes,
)


def test_system_metrics_has_expected_non_negative_values() -> None:
    result = get_system_metrics()
    assert result["status"] == "ok"
    assert 0 <= result["cpuUsagePercent"] <= 100
    assert result["memoryTotalBytes"] > 0
    assert result["memoryUsedBytes"] >= 0
    assert result["memoryAvailableBytes"] >= 0
    assert result["cpuLogicalCores"] >= 1
    assert result["timestamp"].endswith("+00:00")


def test_disk_usage_rejects_unknown_mount_point(tmp_path: Path) -> None:
    with pytest.raises(NotAllowedError):
        get_disk_usage(["/etc"], (str(tmp_path),))


def test_disk_usage_returns_only_allowlisted_paths(tmp_path: Path) -> None:
    result = get_disk_usage([str(tmp_path)], (str(tmp_path),))
    item = result["filesystems"][0]
    assert item["mountPoint"] == str(tmp_path)
    assert item["totalBytes"] > 0
    assert item["usedBytes"] >= 0
    assert item["availableBytes"] >= 0
    assert 0 <= item["usagePercent"] <= 100


def test_list_processes_limits_and_omits_sensitive_fields() -> None:
    result = list_processes(limit=3, sort_by="memory", sample_window_seconds=0.02)
    assert len(result["processes"]) <= 3
    assert result["status"] in {"ok", "partial"}
    for item in result["processes"]:
        assert item["pid"] > 0
        assert item["name"]
        assert 0 <= item["cpuPercent"] <= 100
        assert item["memoryPercent"] >= 0
        assert "cmdline" not in item
        assert "username" not in item
        assert "environment" not in item


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_list_processes_rejects_invalid_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        list_processes(limit=limit, sample_window_seconds=0)


@pytest.mark.parametrize("sample_window", [-0.1, 1.01, float("nan"), float("inf")])
def test_list_processes_rejects_invalid_sample_window(sample_window: float) -> None:
    with pytest.raises(ValueError, match="sample_window_seconds"):
        list_processes(sample_window_seconds=sample_window)


@pytest.mark.parametrize("name_filter", ["", "   ", " " * 65])
def test_list_processes_rejects_blank_or_oversized_name_filter(name_filter: str) -> None:
    with pytest.raises(ValueError, match="name_contains"):
        list_processes(name_contains=name_filter, sample_window_seconds=0)


def test_list_processes_rejects_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    class InitialProcess:
        def __init__(self) -> None:
            self.info = {
                "pid": 4242,
                "name": "worker",
                "memory_info": SimpleNamespace(rss=1024),
                "create_time": 100.0,
            }

        @staticmethod
        def cpu_times() -> SimpleNamespace:
            return SimpleNamespace(user=1.0, system=0.5)

    class ReusedProcess:
        @staticmethod
        def create_time() -> float:
            return 101.0

    host_samples = iter([(100.0, 200.0, 700.0), (101.0, 200.0, 700.0)])

    def fake_process_iter(**_kwargs: object) -> list[InitialProcess]:
        return [InitialProcess()]

    def fake_process(_pid: int) -> ReusedProcess:
        return ReusedProcess()

    def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("linux_mcp_agent.system.psutil.virtual_memory", lambda: SimpleNamespace(total=4096))
    monkeypatch.setattr("linux_mcp_agent.system.psutil.cpu_times", lambda: next(host_samples))
    monkeypatch.setattr("linux_mcp_agent.system.psutil.process_iter", fake_process_iter)
    monkeypatch.setattr("linux_mcp_agent.system.psutil.Process", fake_process)
    monkeypatch.setattr("linux_mcp_agent.system.time.sleep", no_sleep)

    result = list_processes(sample_window_seconds=0)

    assert result["processes"] == []
    assert result["inaccessibleOrExitedCount"] == 1
    assert result["status"] == "partial"


def test_cpu_semantics_are_machine_capacity_share() -> None:
    assert "total_host_cpu_time_delta" in list_processes(limit=1, sample_window_seconds=0)["cpuPercentSemantics"]
