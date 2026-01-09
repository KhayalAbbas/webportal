"""Encryption service for tenant-scoped integration secrets."""

import base64
import hashlib
import os
from typing import Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from fastapi import status

from app.core.config import settings
from app.errors import raise_app_error


# In-memory runtime master key set via UI (not persisted across restarts).
_runtime_master_key: Optional[str] = None


def _is_relaxed_mode() -> bool:
    flag = os.getenv("ATS_RELAX_MASTER_KEY")
    if flag is None:
        return bool(settings.DEBUG)
    return flag.strip().lower() in {"1", "true", "yes", "on"}


MISSING_MASTER_KEY_MSG = (
    "ATS_SECRETS_MASTER_KEY is required to manage integration secrets. Set it in your environment "
    "(e.g., LOCAL_COMMANDS.ps1 for local) before saving or viewing integrations."
)


def _derive_key(master_key: str) -> bytes:
    digest = hashlib.sha256(master_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def set_runtime_master_key(value: Optional[str]) -> None:
    """Allow setting the master key at runtime (in-memory only)."""
    global _runtime_master_key
    _runtime_master_key = value or None


def get_master_key_value() -> str:
    # Runtime key (if set) takes precedence and lives only for this process lifetime.
    if _runtime_master_key:
        return _runtime_master_key
    return os.getenv("ATS_SECRETS_MASTER_KEY") or (settings.ATS_SECRETS_MASTER_KEY or "")


def get_key_version() -> int:
    raw = os.getenv("ATS_SECRETS_KEY_VERSION") or str(settings.ATS_SECRETS_KEY_VERSION or "1")
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return 1


def require_master_key() -> str:
    master_key = get_master_key_value()
    if master_key:
        return master_key

    if _is_relaxed_mode():
        # Dev/testing fallback to keep UI usable without env configuration.
        fallback = "dev-insecure-master-key"
        set_runtime_master_key(fallback)
        return fallback

    raise_app_error(status.HTTP_400_BAD_REQUEST, "SECRETS_MASTER_KEY_MISSING", MISSING_MASTER_KEY_MSG)


class SecretsService:
    """Encrypts/decrypts secrets using a master key."""

    def __init__(self, master_key: Optional[str] = None, key_version: Optional[int] = None) -> None:
        self.master_key = master_key or require_master_key()
        self.key_version = key_version or get_key_version()
        self.fernet = Fernet(_derive_key(self.master_key))

    def encrypt(self, plaintext: str) -> Tuple[str, int, Optional[str]]:
        token = self.fernet.encrypt((plaintext or "").encode("utf-8")).decode("utf-8")
        last4 = plaintext[-4:] if plaintext else None
        return token, self.key_version, last4

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self.fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            raise_app_error(status.HTTP_400_BAD_REQUEST, "SECRET_DECRYPT_FAILED", "Could not decrypt stored secret")
