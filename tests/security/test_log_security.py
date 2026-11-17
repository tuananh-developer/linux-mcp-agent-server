from unittest.mock import MagicMock, patch

import pytest

from linux_mcp_agent.log_reader import LogReadError, read_allowed_log


@pytest.fixture
def mock_sources() -> dict[str, str]:
    """Tạo một cấu hình nguồn log giả định để test"""
    return {
        "syslog": "syslog.service"
    }


@patch("linux_mcp_agent.log_reader.shutil.which")
def test_reject_path_traversal(mock_which: MagicMock, mock_sources: dict[str, str]) -> None:
    """Đảm bảo hệ thống chặn path traversal bằng cách kiểm tra executable"""
    mock_which.return_value = None
    
    with pytest.raises(LogReadError) as excinfo:
        read_allowed_log(
            alias="syslog", 
            lines=10, 
            sources=mock_sources, 
            journalctl_path="../../../../../etc/shadow"
        )
    
    assert "journalctl executable is unavailable" in str(excinfo.value)
    mock_which.assert_called_with("../../../../../etc/shadow")


def test_reject_excessive_lines(mock_sources: dict[str, str]) -> None:
    """Từ chối nếu request yêu cầu số dòng vượt quá mức cho phép"""
    with pytest.raises(ValueError) as excinfo:
        read_allowed_log(alias="syslog", lines=500, sources=mock_sources)
    assert "lines must be between 1 and 200" in str(excinfo.value)


def test_reject_unknown_alias(mock_sources: dict[str, str]) -> None:
    """Từ chối nếu alias log truyền vào không tồn tại trong danh sách allowlist"""
    with pytest.raises(PermissionError) as excinfo:
        read_allowed_log(alias="hacker_alias", lines=10, sources=mock_sources)
    assert "Log alias is not allowlisted" in str(excinfo.value)