"""Symmetric encryption for sensitive connector config fields.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` package,
which is already installed as a transitive dependency of python-jose.

Set ``CONNECTOR_ENCRYPT_KEY`` in .env to a Fernet key:
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If the env var is absent, encryption is skipped and plaintext is stored.
Existing plaintext values are decrypted transparently (detected by missing Fernet prefix).
"""

from __future__ import annotations

import logging

_log = logging.getLogger(__name__)
_FERNET_PREFIX = b"gAAAAA"  # All Fernet tokens start with this


def _get_fernet() -> object | None:
    from src.config import settings

    key = settings.connector_encrypt_key.strip()
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        _log.error(
            "[crypto] Invalid CONNECTOR_ENCRYPT_KEY — encryption disabled: %s", exc
        )
        return None


def encrypt_config(plaintext: str) -> str:
    """Encrypt a JSON string. Returns ciphertext, or plaintext if key is absent."""
    f = _get_fernet()
    if f is None:
        return plaintext
    try:
        return f.encrypt(plaintext.encode()).decode()  # type: ignore[union-attr]
    except Exception as exc:
        _log.error("[crypto] Encryption failed — storing plaintext: %s", exc)
        return plaintext


def decrypt_config(value: str) -> str:
    """Decrypt a config value. Returns as-is if plaintext or key is absent."""
    if not value:
        return value
    raw = value.encode() if isinstance(value, str) else value
    if not raw.startswith(_FERNET_PREFIX):
        return value  # Legacy plaintext — pass through unchanged
    f = _get_fernet()
    if f is None:
        _log.warning(
            "[crypto] Encrypted config present but CONNECTOR_ENCRYPT_KEY not set"
        )
        return value
    try:
        return f.decrypt(raw).decode()  # type: ignore[union-attr]
    except Exception as exc:
        _log.error("[crypto] Decryption failed: %s", exc)
        return value
