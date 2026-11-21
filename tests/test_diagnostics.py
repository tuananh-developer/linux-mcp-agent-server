from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

import linux_mcp_agent.diagnostics as diagnostics


def test_network_stats_returns_counters_without_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counters = SimpleNamespace(
        bytes_sent=10, bytes_recv=20, packets_sent=3, packets_recv=4,
        errin=0, errout=1, dropin=2, dropout=0,
    )
    def fake_net_io_counters(*, pernic: bool) -> dict[str, Any]:
        assert pernic is True
        return {"eth0": counters}

    monkeypatch.setattr(diagnostics.psutil, "net_io_counters", fake_net_io_counters)
    monkeypatch.setattr(
        diagnostics.psutil,
        "net_if_stats",
        lambda: {"eth0": SimpleNamespace(isup=True, mtu=1500, speed=1000)},
    )

    result = diagnostics.get_network_stats()
    interface = result["interfaces"][0]
    assert result["status"] == "ok"
    assert interface["name"] == "eth0"
    assert interface["bytesReceived"] == 20
    assert interface["isUp"] is True
    assert "addresses" not in interface


def test_network_stats_rejects_unknown_interface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_net_io_counters(*, pernic: bool) -> dict[str, Any]:
        assert pernic is True
        return {"eth0": SimpleNamespace()}

    monkeypatch.setattr(
        diagnostics.psutil, "net_io_counters", fake_net_io_counters
    )
    with pytest.raises(ValueError, match="Unknown"):
        diagnostics.get_network_stats("wlan0")


def test_service_status_requires_allowlist_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoked = False

    def fake_run(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal invoked
        invoked = True
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    with pytest.raises(diagnostics.NotAllowedError):
        diagnostics.get_service_status("attacker.service", ("ssh.service",))
    assert invoked is False


def test_service_status_uses_fixed_read_only_systemctl_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "Id=ssh.service\nLoadState=loaded\nActiveState=active\n"
                "SubState=running\nUnitFileState=enabled\nMainPID=123\nResult=success\n"
            ),
        )

    monkeypatch.setattr(diagnostics.subprocess, "run", fake_run)
    result = diagnostics.get_service_status("ssh.service", ("ssh.service",))

    assert result["activeState"] == "active"
    assert result["mainPid"] == 123
    assert captured["shell"] is False
    assert captured["command"][1:3] == ["show", "ssh.service"]


def test_check_port_uses_loopback_only_and_reports_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(address: tuple[str, int], **kwargs: Any) -> Any:
        captured["address"] = address
        captured.update(kwargs)
        return nullcontext()

    monkeypatch.setattr(diagnostics.socket, "create_connection", fake_connect)
    result = diagnostics.check_port(3002)

    assert result["isListening"] is True
    assert captured["address"] == ("127.0.0.1", 3002)


@pytest.mark.parametrize("port", [True, 0, -1, 65536, "3002"])
def test_check_port_rejects_invalid_port(port: Any) -> None:
    with pytest.raises(ValueError, match="port"):
        diagnostics.check_port(port)


def test_check_port_reports_closed_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionRefusedError

    monkeypatch.setattr(diagnostics.socket, "create_connection", refuse)
    result = diagnostics.check_port(6553)
    assert result["isListening"] is False
    assert result["state"] == "closed"


def test_system_alerts_reports_cpu_memory_and_disk_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "linux_mcp_agent.system.get_system_metrics",
        lambda: {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "cpuUsagePercent": 90.0,
            "memoryUsagePercent": 95.0,
        },
    )
    def fake_get_disk_usage(
        _mount_points: list[str] | None,
        _allowed_paths: tuple[str, ...],
    ) -> dict[str, Any]:
        return {"filesystems": [{"mountPoint": "/", "usagePercent": 91.0}]}

    monkeypatch.setattr(
        "linux_mcp_agent.system.get_disk_usage", fake_get_disk_usage
    )

    result = diagnostics.get_system_alerts(("/",))
    assert result["overallStatus"] == "warning"
    assert {alert["metric"] for alert in result["alerts"]} == {"cpu", "memory", "disk"}
    assert result["alertCount"] == 3


def test_system_alerts_rejects_invalid_threshold() -> None:
    with pytest.raises(ValueError, match="threshold"):
        diagnostics.get_system_alerts(("/",), cpu_threshold_percent=0)
