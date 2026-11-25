"""Encrypted per-Keycloak-user provider credential storage.

Only ciphertext and non-secret metadata are persisted. The 256-bit AES-GCM key
is loaded from a systemd credential or an operator-provided protected key file.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROVIDERS = ("gemini", "openai", "openrouter", "anthropic")
_DEFAULT_STORE = Path("/var/lib/linux-mcp-agent/provider-credentials.json")
_SYSTEMD_CREDENTIAL = "provider-vault-key"
_MAX_STORE_BYTES = 2 * 1024 * 1024


class CredentialVaultError(RuntimeError):
    """Raised when encrypted credential storage is unavailable or corrupt."""


class CredentialVault:
    """Small, atomic, per-subject encrypted credential vault."""

    def __init__(self, storage_path: Path, encryption_key: bytes) -> None:
        if len(encryption_key) != 32:
            raise CredentialVaultError("Provider vault key must contain exactly 32 bytes.")
        self.storage_path = storage_path
        self.lock_path = storage_path.with_name(storage_path.name + ".lock")
        self._aead = AESGCM(encryption_key)
        self._thread_lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> CredentialVault | None:
        """Load a key from systemd credentials or an explicitly configured file."""
        credentials_dir = os.getenv("CREDENTIALS_DIRECTORY", "").strip()
        key_file_value = os.getenv("PROVIDER_VAULT_KEY_FILE", "").strip()
        if credentials_dir:
            key_file = Path(credentials_dir) / _SYSTEMD_CREDENTIAL
        elif key_file_value:
            key_file = Path(key_file_value).expanduser()
        else:
            return None

        try:
            metadata = key_file.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise CredentialVaultError("Provider vault key must be a regular file.")
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                raise CredentialVaultError("Provider vault key permissions must be 0600 or stricter.")
            key = key_file.read_bytes()
        except OSError as exc:
            raise CredentialVaultError("Cannot read the provider vault key.") from exc

        storage_value = os.getenv("PROVIDER_VAULT_FILE", str(_DEFAULT_STORE)).strip()
        storage_path = Path(storage_value).expanduser()
        if not storage_path.is_absolute():
            raise CredentialVaultError("PROVIDER_VAULT_FILE must be an absolute path.")
        return cls(storage_path, key)

    @staticmethod
    def _validate_identity(subject: str, provider: str) -> None:
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise CredentialVaultError("A valid authenticated Keycloak subject is required.")
        if provider not in PROVIDERS:
            raise CredentialVaultError("Unsupported hosted AI provider.")

    @staticmethod
    def _entry_key(subject: str, provider: str) -> str:
        return hashlib.sha256((subject + "\0" + provider).encode("utf-8")).hexdigest()

    @staticmethod
    def _aad(subject: str, provider: str, model: str) -> bytes:
        return f"linux-mcp-agent/provider-vault/v1/{subject}/{provider}/{model}".encode("utf-8")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        with self._thread_lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chmod(self.storage_path.parent, 0o700)
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(self.lock_path, flags, 0o600)
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "a+b") as lock_file:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                raise CredentialVaultError("Cannot access the provider credential store.") from exc

    def _read_store(self) -> dict[str, Any]:
        try:
            metadata = self.storage_path.lstat()
        except FileNotFoundError:
            return {"version": 1, "entries": {}}
        except OSError as exc:
            raise CredentialVaultError("Cannot inspect the provider credential store.") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise CredentialVaultError("Provider credential store must be a regular file.")
        if metadata.st_size > _MAX_STORE_BYTES:
            raise CredentialVaultError("Provider credential store exceeds the size limit.")
        try:
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                os.chmod(self.storage_path, 0o600)
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialVaultError("Provider credential store is unreadable or corrupt.") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or not isinstance(payload.get("entries"), dict)
        ):
            raise CredentialVaultError("Provider credential store has an unsupported format.")
        return payload

    def _write_store(self, payload: dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.storage_path.parent, 0o700)
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(encoded) > _MAX_STORE_BYTES:
            raise CredentialVaultError("Provider credential store exceeds the size limit.")
        descriptor = -1
        temporary_path: str | None = None
        try:
            descriptor, temporary_path = tempfile.mkstemp(
                prefix=".provider-credentials-", dir=self.storage_path.parent
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as temporary_file:
                descriptor = -1
                temporary_file.write(encoded)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.storage_path)
            temporary_path = None
            directory_fd = os.open(self.storage_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise CredentialVaultError("Cannot safely persist provider credentials.") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def put(self, subject: str, provider: str, model: str, api_key: str) -> None:
        self._validate_identity(subject, provider)
        if not isinstance(model, str) or not 1 <= len(model) <= 128:
            raise CredentialVaultError("Invalid provider model.")
        if not isinstance(api_key, str) or not 1 <= len(api_key) <= 1024:
            raise CredentialVaultError("Invalid provider API key.")
        nonce = secrets.token_bytes(12)
        ciphertext = self._aead.encrypt(
            nonce,
            json.dumps({"api_key": api_key}, separators=(",", ":")).encode("utf-8"),
            self._aad(subject, provider, model),
        )
        entry = {
            "provider": provider,
            "model": model,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "updated_at": int(time.time()),
        }
        with self._locked():
            store = self._read_store()
            entries = store["entries"]
            entries[self._entry_key(subject, provider)] = entry
            self._write_store(store)

    def get(self, subject: str, provider: str) -> dict[str, str] | None:
        self._validate_identity(subject, provider)
        with self._locked():
            entries = self._read_store()["entries"]
            entry = entries.get(self._entry_key(subject, provider))
            if entry is None:
                return None
            if (
                not isinstance(entry, dict)
                or entry.get("provider") != provider
                or not isinstance(entry.get("model"), str)
                or not isinstance(entry.get("nonce"), str)
                or not isinstance(entry.get("ciphertext"), str)
            ):
                raise CredentialVaultError("Stored provider credential has an invalid format.")
            try:
                plaintext = self._aead.decrypt(
                    base64.b64decode(entry["nonce"], validate=True),
                    base64.b64decode(entry["ciphertext"], validate=True),
                    self._aad(subject, provider, entry["model"]),
                )
                secret = json.loads(plaintext)
            except (ValueError, InvalidTag) as exc:
                raise CredentialVaultError("Cannot decrypt the stored provider credential.") from exc
            if not isinstance(secret, dict) or not isinstance(secret.get("api_key"), str):
                raise CredentialVaultError("Stored provider credential is invalid.")
            return {"provider": provider, "model": entry["model"], "api_key": secret["api_key"]}

    def list_for_subject(self, subject: str) -> list[dict[str, str | int]]:
        if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
            raise CredentialVaultError("A valid authenticated Keycloak subject is required.")
        result: list[dict[str, str | int]] = []
        with self._locked():
            entries = self._read_store()["entries"]
            for provider in PROVIDERS:
                entry = entries.get(self._entry_key(subject, provider))
                if isinstance(entry, dict) and entry.get("provider") == provider:
                    model = entry.get("model")
                    updated_at = entry.get("updated_at")
                    if isinstance(model, str) and isinstance(updated_at, int):
                        result.append({"provider": provider, "model": model, "updated_at": updated_at})
        return result

    def delete(self, subject: str, provider: str) -> bool:
        self._validate_identity(subject, provider)
        with self._locked():
            store = self._read_store()
            entries = store["entries"]
            key = self._entry_key(subject, provider)
            if key not in entries:
                return False
            del entries[key]
            self._write_store(store)
            return True
