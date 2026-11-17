"""Bounded journald reader. Client input selects aliases only, never commands or units."""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

_ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,128}$")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r'(?i)("?(?:password|passwd|secret|token|client_secret|access_token|refresh_token|api[_-]?key)"?\s*[=:]\s*)"?[^\s",;]+"?'
    ),
    re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+(@)"),
)


class LogReadError(RuntimeError):
    """Safe-to-display error from the journal reader."""


def run_journalctl_bounded(
    args: list[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[str, bool, int]:
    """Read a bounded stdout stream and enforce a wall-clock timeout on Linux."""
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            close_fds=True,
            shell=False,
        )
    except OSError as exc:
        raise LogReadError("journalctl could not be started") from exc

    if process.stdout is None:
        process.kill()
        process.wait()
        raise LogReadError("journalctl stdout pipe could not be opened")

    chunks: list[bytes] = []
    captured = 0
    truncated = False
    deadline = time.monotonic() + timeout_seconds
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Journal query exceeded its configured time limit")
                ready = selector.select(remaining)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(process.stdout.fileno(), min(8192, max_output_bytes + 1 - captured))
                if not chunk:
                    break
                chunks.append(chunk)
                captured += len(chunk)
                if captured > max_output_bytes:
                    truncated = True
                    process.terminate()
                    break

        if truncated:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Journal query exceeded its configured time limit")
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("Journal query exceeded its configured time limit") from exc
    except TimeoutError:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise
    except OSError as exc:
        if process.poll() is None:
            process.kill()
            process.wait()
        raise LogReadError("journalctl output could not be read") from exc
    finally:
        process.stdout.close()

    return b"".join(chunks).decode("utf-8", errors="replace"), truncated, int(process.returncode or 0)


def load_log_sources(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LogReadError("Log source configuration file was not found") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LogReadError("Log source configuration file is unreadable or invalid JSON") from exc
    if (
        not isinstance(raw, dict)
        or not raw
        or not all(isinstance(key, str) for key in raw)
    ):
        raise LogReadError("Log source configuration must be a non-empty string-keyed JSON object")

    sources: dict[str, str] = {}
    for alias, config_object in raw.items():
        if not isinstance(alias, str):
            raise LogReadError("Log source configuration contains an invalid alias")
        if not _ALIAS_RE.fullmatch(alias):
            raise LogReadError("Log source configuration contains an invalid alias")
        if not isinstance(config_object, dict):
            raise LogReadError(f"Log source '{alias}' must define a systemd unit")
        raw_unit: object = config_object.get("unit")
        if not isinstance(raw_unit, str):
            raise LogReadError(f"Log source '{alias}' must define a systemd unit")
        unit = raw_unit
        if not _UNIT_RE.fullmatch(unit) or not unit.endswith(".service"):
            raise LogReadError(f"Log source '{alias}' has an invalid systemd unit")
        sources[alias] = unit
    return sources


def _redact(message: str) -> str:
    value = message
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 1:
            value = pattern.sub(r"\1[REDACTED]", value)
        else:
            value = pattern.sub(r"\1[REDACTED]\2", value)
    return value


def _parse_entry(line: str) -> dict[str, Any] | None:
    try:
        entry_object: object = json.loads(line)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(entry_object, dict)
        or not all(isinstance(key, str) for key in entry_object)
    ):
        return None
    entry = cast(dict[str, object], entry_object)
    raw_ts = entry.get("__REALTIME_TIMESTAMP")
    timestamp = None
    if isinstance(raw_ts, str) and raw_ts.isdigit():
        timestamp = datetime.fromtimestamp(int(raw_ts) / 1_000_000, UTC).isoformat()
    raw_priority = entry.get("PRIORITY")
    priority: int | None = None
    if isinstance(raw_priority, (str, int, float)) and not isinstance(raw_priority, bool):
        try:
            priority = int(raw_priority)
        except (TypeError, ValueError, OverflowError):
            priority = None
    raw_message: object = entry.get("MESSAGE", "")
    message = raw_message if isinstance(raw_message, str) else "[non-text journal message omitted]"
    return {"timestamp": timestamp, "priority": priority, "message": _redact(message)}


def read_allowed_log(
    alias: str,
    lines: int,
    *,
    sources: dict[str, str],
    journalctl_path: str = "/usr/bin/journalctl",
    timeout_seconds: float = 1.5,
    max_output_bytes: int = 65536,
) -> dict[str, Any]:
    if alias not in sources:
        raise PermissionError("Log alias is not allowlisted")
    if isinstance(lines, bool) or not 1 <= lines <= 200:
        raise ValueError("lines must be between 1 and 200")
    unit = sources[alias]
    if not _UNIT_RE.fullmatch(unit):
        raise LogReadError("Configured journal unit is invalid")
    executable = shutil.which(journalctl_path)
    if executable is None:
        raise LogReadError("journalctl executable is unavailable")

    output, output_truncated, return_code = run_journalctl_bounded(
        [
            executable,
            "--no-pager",
            "--output=json",
            "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,MESSAGE",
            "--unit",
            unit,
            "--lines",
            str(lines),
        ],
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
    )
    if return_code != 0 and not output_truncated:
        raise LogReadError("journalctl returned an error; verify the unit and service permissions")

    entries = [entry for line in output.splitlines() if (entry := _parse_entry(line)) is not None]
    serialized = json.dumps(entries, ensure_ascii=False).encode("utf-8")
    truncated = output_truncated or len(serialized) > max_output_bytes
    if truncated:
        bounded: list[dict[str, Any]] = []
        used = 2
        for entry in entries:
            encoded = json.dumps(entry, ensure_ascii=False).encode("utf-8")
            if used + len(encoded) + 1 > max_output_bytes:
                break
            bounded.append(entry)
            used += len(encoded) + 1
        entries = bounded
    return {
        "logName": alias,
        "sourceType": "systemd-journal",
        "unit": unit,
        "linesReturned": len(entries),
        "truncated": truncated,
        "content": entries,
        "status": "partial" if truncated else "ok",
    }
