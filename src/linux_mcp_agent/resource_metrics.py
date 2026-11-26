"""Read-only Linux Pressure Stall Information (PSI) telemetry."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_PRESSURE_DIR = Path("/proc/pressure")
_RESOURCES = ("cpu", "memory", "io")
_REQUIRED_FIELDS = ("avg10", "avg60", "avg300", "total")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _parse_pressure_text(contents: str) -> dict[str, dict[str, float | int]]:
    """Parse the stable PSI fields while rejecting malformed or impossible values."""
    pressure: dict[str, dict[str, float | int]] = {}
    for line in contents.splitlines():
        fields = line.split()
        if not fields:
            continue

        category = fields[0]
        if category not in {"some", "full"}:
            # Ignore future kernel categories rather than breaking older clients.
            continue

        values: dict[str, str] = {}
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if not separator or not key or key in values:
                raise ValueError("Malformed PSI field")
            values[key] = value

        if any(name not in values for name in _REQUIRED_FIELDS):
            raise ValueError("PSI row is missing required fields")

        averages: dict[str, float] = {}
        for name in ("avg10", "avg60", "avg300"):
            try:
                average = float(values[name])
            except ValueError as exc:
                raise ValueError("Invalid PSI average") from exc
            if not math.isfinite(average) or not 0.0 <= average <= 100.0:
                raise ValueError("PSI average is outside the valid range")
            averages[name] = round(average, 2)

        try:
            total = int(values["total"])
        except ValueError as exc:
            raise ValueError("Invalid PSI total") from exc
        if total < 0:
            raise ValueError("PSI total cannot be negative")

        pressure[category] = {
            "avg10Percent": averages["avg10"],
            "avg60Percent": averages["avg60"],
            "avg300Percent": averages["avg300"],
            "totalStallMicroseconds": total,
        }

    if not pressure:
        raise ValueError("PSI file contained no supported rows")
    return pressure


def _read_pressure_file(path: Path) -> dict[str, Any]:
    """Read one fixed procfs file with a strict size limit and safe error output."""
    try:
        with path.open("r", encoding="ascii") as stream:
            contents = stream.read(4097)
    except (OSError, UnicodeError):
        return {"supported": False, "status": "unavailable", "pressure": {}}

    if len(contents) > 4096:
        return {"supported": True, "status": "invalid-data", "pressure": {}}

    try:
        pressure = _parse_pressure_text(contents)
    except ValueError:
        return {"supported": True, "status": "invalid-data", "pressure": {}}

    return {"supported": True, "status": "ok", "pressure": pressure}


def get_resource_pressure(
    proc_pressure_dir: Path = _DEFAULT_PRESSURE_DIR,
) -> dict[str, Any]:
    """Return CPU, memory and I/O stall averages from the fixed Linux PSI interface.

    PSI averages describe the percentage of wall-clock time tasks were stalled
    over 10, 60 and 300 seconds. The cumulative total is reported in microseconds.
    No caller-controlled path or raw procfs content is returned.
    """
    resources = {
        name: _read_pressure_file(proc_pressure_dir / name)
        for name in _RESOURCES
    }
    available_count = sum(item["status"] == "ok" for item in resources.values())
    if available_count == len(_RESOURCES):
        status = "ok"
    elif available_count:
        status = "partial"
    else:
        status = "unavailable"

    return {
        "timestamp": _timestamp(),
        "semantics": (
            "PSI stall time percentages over 10/60/300 second windows; "
            "totalStallMicroseconds is cumulative since boot"
        ),
        "resources": resources,
        "availableResourceCount": available_count,
        "status": status,
    }
