from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from linux_mcp_agent.log_reader import (
    LogReadError,
    load_log_sources,
    read_allowed_log,
    run_journalctl_bounded,
)


def test_load_log_sources(tmp_path: Path) -> None:
    config = tmp_path / "logs.json"
    config.write_text(json.dumps({"ssh": {"unit": "ssh.service"}}), encoding="utf-8")
    assert load_log_sources(config) == {"ssh": "ssh.service"}


def test_load_log_sources_rejects_non_service_unit(tmp_path: Path) -> None:
    config = tmp_path / "logs.json"
    config.write_text(json.dumps({"ssh": {"unit": "../../etc/passwd"}}), encoding="utf-8")
    with pytest.raises(LogReadError):
        load_log_sources(config)


def test_read_allowed_log_uses_fixed_argv_and_redacts_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    output = json.dumps({
        "__REALTIME_TIMESTAMP": "1793520000000000",
        "PRIORITY": "6",
        "MESSAGE": "Authorization: Bearer abc.def.ghi password=hunter2 api_key=abcd1234 service started",
    })
    captured: dict[str, Any] = {}

    def fake_which(path: str) -> str:
        return "/usr/bin/journalctl"

    def fake_run(args: list[str], **kwargs: Any) -> tuple[str, bool, int]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return output + "\n", False, 0

    monkeypatch.setattr("linux_mcp_agent.log_reader.shutil.which", fake_which)
    monkeypatch.setattr("linux_mcp_agent.log_reader.run_journalctl_bounded", fake_run)
    result = read_allowed_log("ssh", 5, sources={"ssh": "ssh.service"})

    assert captured["args"] == [
        "/usr/bin/journalctl", "--no-pager", "--output=json",
        "--output-fields=__REALTIME_TIMESTAMP,PRIORITY,MESSAGE", "--unit", "ssh.service", "--lines", "5",
    ]
    assert captured["kwargs"]["max_output_bytes"] == 65536
    assert "[REDACTED]" in result["content"][0]["message"]
    assert "hunter2" not in result["content"][0]["message"]
    assert "abcd1234" not in result["content"][0]["message"]


def test_read_allowed_log_rejects_unknown_alias() -> None:
    with pytest.raises(PermissionError):
        read_allowed_log("../../etc/passwd", 5, sources={"ssh": "ssh.service"})


def test_read_allowed_log_rejects_out_of_range_lines() -> None:
    with pytest.raises(ValueError):
        read_allowed_log("ssh", 201, sources={"ssh": "ssh.service"})


def test_read_allowed_log_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_which(_path: str) -> str:
        return "/usr/bin/journalctl"

    monkeypatch.setattr("linux_mcp_agent.log_reader.shutil.which", fake_which)
    def timeout(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("Journal query exceeded its configured time limit")
    monkeypatch.setattr("linux_mcp_agent.log_reader._run_journalctl_bounded", timeout)
    with pytest.raises(TimeoutError):
        read_allowed_log("ssh", 5, sources={"ssh": "ssh.service"})


def test_bounded_process_reader_caps_output() -> None:
    output, truncated, return_code = run_journalctl_bounded(
        [sys.executable, "-c", "print('x' * 10000)"],
        timeout_seconds=2.0,
        max_output_bytes=128,
    )
    assert len(output.encode("utf-8")) <= 129
    assert truncated is True
    assert return_code != 0


def test_bounded_process_reader_enforces_timeout() -> None:
    with pytest.raises(TimeoutError):
        run_journalctl_bounded(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_seconds=0.05,
            max_output_bytes=128,
        )
