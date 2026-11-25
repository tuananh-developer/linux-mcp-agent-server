from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from linux_mcp_agent.credential_vault import CredentialVault, CredentialVaultError


def test_vault_encrypts_and_isolates_credentials_by_subject(tmp_path: Path) -> None:
    key = os.urandom(32)
    store_path = tmp_path / "state" / "provider-credentials.json"
    vault = CredentialVault(store_path, key)

    vault.put("keycloak-user-a", "openrouter", "openrouter/free", "sk-or-a-secret")
    vault.put("keycloak-user-a", "gemini", "gemini-3.8-flash", "gemini-a-secret")

    stored = store_path.read_text(encoding="utf-8")
    assert "sk-or-a-secret" not in stored
    assert "gemini-a-secret" not in stored
    assert "keycloak-user-a" not in stored
    assert (store_path.stat().st_mode & 0o777) == 0o600
    assert (store_path.parent.stat().st_mode & 0o777) == 0o700

    assert vault.get("keycloak-user-a", "openrouter") == {
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "sk-or-a-secret",
    }
    assert vault.get("keycloak-user-b", "openrouter") is None
    assert [item["provider"] for item in vault.list_for_subject("keycloak-user-a")] == [
        "gemini",
        "openrouter",
    ]
    assert vault.list_for_subject("keycloak-user-b") == []


def test_vault_delete_is_scoped_to_subject_and_provider(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path / "provider-credentials.json", os.urandom(32))
    vault.put("user-a", "openrouter", "openrouter/free", "key-a")
    vault.put("user-b", "openrouter", "openrouter/free", "key-b")

    assert vault.delete("user-a", "openrouter") is True
    assert vault.delete("user-a", "openrouter") is False
    assert vault.get("user-a", "openrouter") is None
    user_b_credential = vault.get("user-b", "openrouter")
    assert user_b_credential is not None
    assert user_b_credential["api_key"] == "key-b"


def test_vault_rejects_tampered_ciphertext(tmp_path: Path) -> None:
    vault = CredentialVault(tmp_path / "provider-credentials.json", os.urandom(32))
    vault.put("user-a", "openrouter", "openrouter/free", "key-a")

    payload = json.loads(vault.storage_path.read_text(encoding="utf-8"))
    entry = next(iter(payload["entries"].values()))
    entry["ciphertext"] = entry["ciphertext"][:-4] + "AAAA"
    vault.storage_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CredentialVaultError, match="decrypt"):
        vault.get("user-a", "openrouter")


def test_vault_rejects_wrong_key_and_invalid_identity(tmp_path: Path) -> None:
    store_path = tmp_path / "provider-credentials.json"
    CredentialVault(store_path, os.urandom(32)).put("user-a", "openrouter", "openrouter/free", "key-a")
    other_vault = CredentialVault(store_path, os.urandom(32))

    with pytest.raises(CredentialVaultError, match="decrypt"):
        other_vault.get("user-a", "openrouter")
    with pytest.raises(CredentialVaultError, match="subject"):
        other_vault.get("", "openrouter")
    with pytest.raises(CredentialVaultError, match="provider"):
        other_vault.get("user-a", "ollama")


def test_vault_from_environment_requires_a_32_byte_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key_file = tmp_path / "provider-vault.key"
    key_file.write_bytes(b"short")
    key_file.chmod(0o600)
    monkeypatch.setenv("PROVIDER_VAULT_KEY_FILE", str(key_file))
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)

    with pytest.raises(CredentialVaultError, match="32 bytes"):
        CredentialVault.from_environment()


def test_vault_from_systemd_credential_accepts_systemd_managed_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials_dir = tmp_path / "systemd-credentials"
    credentials_dir.mkdir(mode=0o700)
    key_file = credentials_dir / "provider-vault-key"
    key_file.write_bytes(os.urandom(32))
    # systemd exposes credentials through its isolated per-unit runtime
    # directory; do not require the staged copy to retain the source file mode.
    key_file.chmod(0o444)

    store_path = tmp_path / "state" / "provider-credentials.json"
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials_dir))
    monkeypatch.setenv("PROVIDER_VAULT_FILE", str(store_path))
    monkeypatch.delenv("PROVIDER_VAULT_KEY_FILE", raising=False)

    vault = CredentialVault.from_environment()
    assert vault is not None
    vault.put("user-a", "openrouter", "openrouter/free", "key-a")
    assert vault.get("user-a", "openrouter") == {
        "provider": "openrouter",
        "model": "openrouter/free",
        "api_key": "key-a",
    }


def test_vault_from_explicit_key_file_rejects_permissive_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "provider-vault.key"
    key_file.write_bytes(os.urandom(32))
    key_file.chmod(0o640)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("PROVIDER_VAULT_KEY_FILE", str(key_file))

    with pytest.raises(CredentialVaultError, match="permissions"):
        CredentialVault.from_environment()

