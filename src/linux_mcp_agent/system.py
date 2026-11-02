"""Read-only Linux telemetry backed by psutil and kernel metadata."""

from __future__ import annotations

import os
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psutil


class NotAllowedError(ValueError):
    """Requested system resource is outside the server-side allowlist."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def get_system_metrics() -> dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    try:
        load_average = list(psutil.getloadavg())
    except (AttributeError, OSError):
        load_average = None
    boot_time = psutil.boot_time()
    return {
        "timestamp": _timestamp(),
        "cpuUsagePercent": round(cpu_percent, 2),
        "cpuLogicalCores": psutil.cpu_count(logical=True) or 0,
        "memoryTotalBytes": int(memory.total),
        "memoryUsedBytes": int(memory.total - memory.available),
        "memoryAvailableBytes": int(memory.available),
        "memoryUsagePercent": round(memory.percent, 2),
        "loadAverage1m5m15m": load_average,
        "uptimeSeconds": max(0, int(time.time() - boot_time)),
        "status": "ok",
    }


def get_disk_usage(mount_points: list[str] | None, allowed_paths: tuple[str, ...]) -> dict[str, Any]:
    requested = mount_points if mount_points is not None else list(allowed_paths)
    if not requested:
        raise ValueError("At least one configured mount point is required")
    if len(requested) > 10:
        raise ValueError("A maximum of 10 mount points can be requested")

    filesystems: list[dict[str, Any]] = []
    for path in requested:
        if path not in allowed_paths:
            raise NotAllowedError(f"Mount point is not allowlisted: {path}")
        if not Path(path).is_dir():
            raise FileNotFoundError(f"Configured mount point does not exist: {path}")
        stats = os.statvfs(path)
        total_bytes = int(stats.f_blocks * stats.f_frsize)
        used_bytes = int((stats.f_blocks - stats.f_bfree) * stats.f_frsize)
        available_bytes = int(stats.f_bavail * stats.f_frsize)
        usage_percent = (used_bytes / total_bytes * 100.0) if total_bytes else 0.0
        filesystems.append({
            "mountPoint": path,
            "totalBytes": total_bytes,
            "usedBytes": used_bytes,
            "availableBytes": available_bytes,
            "usagePercent": round(usage_percent, 2),
            "status": "ok",
        })
    return {"timestamp": _timestamp(), "filesystems": filesystems, "status": "ok"}


def list_processes(
    limit: int = 10,
    sort_by: Literal["cpu", "memory"] = "cpu",
    name_contains: str | None = None,
    sample_window_seconds: float = 0.1,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if sort_by not in {"cpu", "memory"}:
        raise ValueError("sort_by must be 'cpu' or 'memory'")
    if name_contains is not None and not 1 <= len(name_contains) <= 64:
        raise ValueError("name_contains must contain between 1 and 64 characters")

    memory_total = psutil.virtual_memory().total
    first_host = psutil.cpu_times()
    first_host_total = sum(first_host)
    snapshots: dict[int, dict[str, Any]] = {}
    inaccessible = 0
    for proc in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
        try:
            info = proc.info
            cpu_times = proc.cpu_times()
            name = info.get("name") or "<unknown>"
            if name_contains and name_contains.casefold() not in name.casefold():
                continue
            mem_info = info.get("memory_info")
            snapshots[int(info["pid"])] = {
                "name": name,
                "cpuSeconds": float(cpu_times.user + cpu_times.system),
                "rssBytes": int(mem_info.rss) if mem_info else None,
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, KeyError, TypeError):
            inaccessible += 1

    time.sleep(sample_window_seconds)
    second_host = psutil.cpu_times()
    host_delta = max(0.000001, sum(second_host) - first_host_total)
    results: list[dict[str, Any]] = []
    for pid, first in snapshots.items():
        try:
            current = psutil.Process(pid)
            cpu_times = current.cpu_times()
            delta = max(0.0, float(cpu_times.user + cpu_times.system) - first["cpuSeconds"])
            cpu_percent = min(100.0, max(0.0, delta / host_delta * 100.0))
            rss = first["rssBytes"]
            if rss is None:
                rss = int(current.memory_info().rss)
            memory_percent = (rss / memory_total * 100.0) if memory_total else 0.0
            results.append({
                "pid": pid,
                "name": first["name"],
                "cpuPercent": round(cpu_percent, 2),
                "memoryPercent": round(memory_percent, 2),
                "rssBytes": rss,
                "status": "ok",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            inaccessible += 1

    results.sort(key=lambda item: item["cpuPercent" if sort_by == "cpu" else "memoryPercent"], reverse=True)
    return {
        "timestamp": _timestamp(),
        "sampleWindowMs": int(sample_window_seconds * 1000),
        "cpuPercentSemantics": "process_cpu_time_delta_over_total_host_cpu_time_delta",
        "memoryPercentSemantics": "process_rss_over_physical_memory_total",
        "processes": results[:limit],
        "inaccessibleOrExitedCount": inaccessible,
        "status": "partial" if inaccessible else "ok",
    }


def system_summary(allowed_paths: tuple[str, ...]) -> dict[str, Any]:
    try:
        os_info = platform.freedesktop_os_release()
        distro = os_info.get("PRETTY_NAME", "Linux")
    except (AttributeError, OSError):
        distro = "Linux"
    metrics = get_system_metrics()
    disks = get_disk_usage(list(allowed_paths[:5]), allowed_paths) if allowed_paths else {"filesystems": []}
    return {
        "timestamp": metrics["timestamp"],
        "operatingSystem": distro,
        "kernelRelease": platform.release(),
        "architecture": platform.machine(),
        "logicalCpuCores": metrics["cpuLogicalCores"],
        "uptimeSeconds": metrics["uptimeSeconds"],
        "cpuUsagePercent": metrics["cpuUsagePercent"],
        "memoryUsagePercent": metrics["memoryUsagePercent"],
        "disk": disks["filesystems"],
    }
