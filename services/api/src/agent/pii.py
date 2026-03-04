"""PII masking for query results.

Applies field-level masking when the requesting user lacks PII access.
Masking is deterministic (same value → same mask) so joins still work.
"""

from __future__ import annotations

import re
from typing import Any


def _mask_email(value: str) -> str:
    """j.doe@example.com → j***@example.com"""
    if "@" not in value:
        return "***"
    local, domain = value.split("@", 1)
    return f"{local[0]}***@{domain}"


def _mask_phone(value: str) -> str:
    """Keep last 4 digits: +44 7700 900123 → ***-***-0123"""
    digits = re.sub(r"\D", "", str(value))
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***"


def _mask_name(value: str) -> str:
    """Jane Doe → J*** D***"""
    parts = str(value).split()
    return " ".join(f"{p[0]}***" for p in parts if p)


_EMAIL_RE = re.compile(r"email", re.IGNORECASE)
_PHONE_RE = re.compile(r"phone|mobile|fax", re.IGNORECASE)
_NAME_RE = re.compile(r"(first|last|full|display)_?name|^name$", re.IGNORECASE)


def mask_value(field_name: str, value: Any) -> Any:
    """Apply the appropriate mask for a single PII field value."""
    if value is None:
        return None
    s = str(value)
    if _EMAIL_RE.search(field_name):
        return _mask_email(s)
    if _PHONE_RE.search(field_name):
        return _mask_phone(s)
    if _NAME_RE.search(field_name):
        return _mask_name(s)
    return "[REDACTED]"


def mask_rows(
    rows: list[dict[str, Any]],
    pii_fields: set[str],
    has_pii_access: bool,
) -> list[dict[str, Any]]:
    """Return rows with PII fields masked if the user lacks PII access."""
    if has_pii_access or not pii_fields:
        return rows
    masked = []
    for row in rows:
        masked.append(
            {k: (mask_value(k, v) if k in pii_fields else v) for k, v in row.items()}
        )
    return masked
