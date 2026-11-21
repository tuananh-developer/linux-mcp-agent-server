"""Read-only Linux network, service and diagnostic checks."""

from __future__ import annotations

import math
import socket
import subprocess
from datetime import UTC, datetime
from typing import Any

import psutil


class NotAllowedError(ValueError):
    """Raised when a requested diagnostic target is outside server policy."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def get_network_stats(interface: str | None = None) -> dict[str, Any]:
    """Return bounded per-interface counters without exposing interface addresses."""
    counters_by_interface = psutil.net_io_counters(pernic=True) or {}
    stats_by_interface = psutil.net_if_stats()

    if interface is not None:
        requested = interface.strip()
        if not 1 <= len(requested) <= 64 or requested not in counters_by_interface:
            raise ValueError("Unknown or invalid network interface")
        selected = {requested: counters_by_interface[requested]}
    else:
        selected = dict(sorted(counters_by_interface.items())[:64])

    interfaces: list[dict[str, Any]] = []
    for name, counters in selected.items():
        link = stats_by_interface.get(name)
        interfaces.append(
            {
                "name": name,
                "isUp": bool(link.isup) if link is not None else False,
                "mtu": int(link.mtu) if link is not None else None,
                "speedMbps": int(link.speed) if link is not None else None,
                "bytesSent": int(counters.bytes_sent),
                "bytesReceived": int(counters.bytes_recv),
                "packetsSent": int(counters.packets_sent),
                "packetsReceived": int(counters.packets_recv),
                "errorsIn": int(counters.errin),
                "errorsOut": int(counters.errout),
                "dropsIn": int(counters.dropin),
                "dropsOut": int(counters.dropout),
            }
        )

    return {
        "timestamp": _timestamp(),
        "interfaceCount": len(interfaces),
        "interfaces": interfaces,
        "status": "ok" if interfaces else "unavailable",
    }


def get_service_status(
    unit: str,
    allowed_units: tuple[str, ...],
    systemctl_path: str = "/usr/bin/systemctl",
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Read selected systemd service properties for an administrator-allowlisted unit."""
    if unit not in allowed_units:
        raise NotAllowedError("The requested systemd unit is not allowlisted")
    if (
        not unit.endswith(".service")
        or not 1 <= len(unit) <= 128
        or not unit[0].isascii()
        or not unit[0].isalnum()
        or not all(
            character.isascii() and (character.isalnum() or character in "_.@:-")
            for character in unit
        )
    ):
        raise ValueError("unit must be a valid systemd .service unit name")
    if not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 5.0:
        raise ValueError("timeout_seconds must be between 0.1 and 5 seconds")

    command = [
        systemctl_path,
        "show",
        unit,
        "--no-pager",
        "--property=Id,LoadState,ActiveState,SubState,UnitFileState,MainPID,Result",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("systemctl is not available on this host") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("systemctl query timed out") from exc

    if completed.returncode != 0:
        raise RuntimeError("systemctl could not read the requested service")

    properties: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key] = value

    load_state = properties.get("LoadState", "unknown")
    main_pid_raw = properties.get("MainPID", "0")
    try:
        main_pid = max(0, int(main_pid_raw))
    except ValueError:
        main_pid = 0

    return {
        "timestamp": _timestamp(),
        "unit": properties.get("Id", unit),
        "loadState": load_state,
        "activeState": properties.get("ActiveState", "unknown"),
        "subState": properties.get("SubState", "unknown"),
        "unitFileState": properties.get("UnitFileState", "unknown"),
        "mainPid": main_pid,
        "result": properties.get("Result", "unknown"),
        "status": "not-found" if load_state == "not-found" else "ok",
    }


def check_port(port: int, timeout_seconds: float = 0.5) -> dict[str, Any]:
    """Check one local TCP listener; callers cannot select a remote host or scan a range."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    if not math.isfinite(timeout_seconds) or not 0.1 <= timeout_seconds <= 2.0:
        raise ValueError("timeout_seconds must be between 0.1 and 2 seconds")

    listening = False
    state = "closed"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_seconds):
            listening = True
            state = "listening"
    except TimeoutError:
        state = "timeout"
    except OSError:
        state = "closed"

    return {
        "timestamp": _timestamp(),
        "host": "127.0.0.1",
        "port": port,
        "protocol": "tcp",
        "isListening": listening,
        "state": state,
        "status": "ok",
    }


def get_system_alerts(
    allowed_disk_paths: tuple[str, ...],
    cpu_threshold_percent: float = 85.0,
    memory_threshold_percent: float = 90.0,
    disk_threshold_percent: float = 85.0,
) -> dict[str, Any]:
    """Evaluate a small, explainable set of CPU, memory and allowlisted-disk thresholds."""
    thresholds = {
        "cpuUsagePercent": cpu_threshold_percent,
        "memoryUsagePercent": memory_threshold_percent,
        "diskUsagePercent": disk_threshold_percent,
    }
    for name, threshold in thresholds.items():
        if not math.isfinite(threshold) or not 1.0 <= threshold <= 100.0:
            raise ValueError(f"{name} threshold must be between 1 and 100")

    from linux_mcp_agent.system import get_disk_usage, get_system_metrics

    metrics = get_system_metrics()
    disks = get_disk_usage(None, allowed_disk_paths)
    alerts: list[dict[str, Any]] = []

    for metric_name, current_key, threshold in (
        ("cpu", "cpuUsagePercent", cpu_threshold_percent),
        ("memory", "memoryUsagePercent", memory_threshold_percent),
    ):
        current = float(metrics[current_key])
        if current >= threshold:
            alerts.append(
                {
                    "severity": "warning",
                    "metric": metric_name,
                    "currentPercent": round(current, 2),
                    "thresholdPercent": threshold,
                    "message": f"{metric_name.capitalize()} usage is at or above its configured threshold",
                }
            )

    for filesystem in disks["filesystems"]:
        current = float(filesystem["usagePercent"])
        if current >= disk_threshold_percent:
            alerts.append(
                {
                    "severity": "warning",
                    "metric": "disk",
                    "mountPoint": filesystem["mountPoint"],
                    "currentPercent": round(current, 2),
                    "thresholdPercent": disk_threshold_percent,
                    "message": "Filesystem usage is at or above its configured threshold",
                }
            )

    return {
        "timestamp": metrics["timestamp"],
        "overallStatus": "warning" if alerts else "healthy",
        "alertCount": len(alerts),
        "alerts": alerts,
        "thresholds": thresholds,
        "status": "ok",
    }
