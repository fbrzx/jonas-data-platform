"""Schema inference: JSON/CSV samples → proposed entity field definitions.

Detects:
- Data types (string, int, float, bool, timestamp, json, array)
- PII fields by name patterns (email, phone, first_name, last_name, etc.)
- Nullable fields (any field missing from ≥10% of sample rows)
"""

from __future__ import annotations

import re
from typing import Any

# ── PII heuristics ──────────────────────────────────────────────────────────

_PII_PATTERNS = re.compile(
    r"""
    (^|_)(
        email | phone | mobile | fax |
        first_name | last_name | full_name | display_name |
        address | street | postcode | zip | city |
        ssn | passport | national_id | dob | date_of_birth |
        ip_address | user_agent |
        credit_card | card_number | iban | account_number
    )(_|$)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _is_pii(field_name: str) -> bool:
    return bool(_PII_PATTERNS.search(field_name))


# ── Type detection ───────────────────────────────────────────────────────────

_ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

# Field names that are semantically identifiers — never coerce to int/float
_ID_FIELD = re.compile(
    r"(^|_)(id|uuid|guid|key|token|hash|ref|code|sku|slug)$",
    re.IGNORECASE,
)


def _detect_type(values: list[Any], field_name: str = "") -> str:
    """Infer a platform type from a list of sample values (non-null)."""
    if not values:
        return "string"

    # Check structure first
    if all(isinstance(v, list) for v in values):
        return "array"
    if all(isinstance(v, dict) for v in values):
        return "json"

    # Booleans (before int, because bool is a subclass of int in Python)
    if all(isinstance(v, bool) for v in values):
        return "bool"

    is_id_field = bool(field_name and _ID_FIELD.search(field_name))

    # Native numeric types — always respected (id=299 should be int)
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "int"
    if all(
        isinstance(v, float) or (isinstance(v, int) and not isinstance(v, bool))
        for v in values
    ):
        return "float"

    # String-based detection
    str_values = [str(v).strip() for v in values if v is not None]
    if not str_values:
        return "string"

    # UUID — must check before numeric, as some UUIDs contain only hex digits
    if all(_UUID.match(s) for s in str_values):
        return "string"

    if all(_ISO_TIMESTAMP.match(s) for s in str_values):
        return "timestamp"
    if all(_ISO_DATE.match(s) for s in str_values):
        return "timestamp"

    if all(_EMAIL.match(s) for s in str_values):
        return "string"  # email is string; PII flag handles the sensitivity

    if all(_URL.match(s) for s in str_values):
        return "string"

    # Numeric strings — skip if this is an identifier field
    if not is_id_field:

        def _is_int(s: str) -> bool:
            try:
                int(s)
                return True
            except ValueError:
                return False

        def _is_float(s: str) -> bool:
            try:
                float(s)
                return True
            except ValueError:
                return False

        if all(_is_int(s) for s in str_values):
            return "int"
        if all(_is_float(s) for s in str_values):
            return "float"

    return "string"


# ── Public API ───────────────────────────────────────────────────────────────


def infer_from_json(
    sample: dict[str, Any] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer field definitions from a JSON object or array of objects.

    Returns a list of field dicts compatible with catalogue.FieldDefinition.
    """
    if isinstance(sample, dict):
        records = [sample]
    elif isinstance(sample, list):
        records = [r for r in sample if isinstance(r, dict)]
    else:
        return []

    if not records:
        return []

    # Collect all keys across records
    all_keys: list[str] = []
    seen: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    total = len(records)
    fields: list[dict[str, Any]] = []

    for ordinal, key in enumerate(all_keys):
        values = [r[key] for r in records if key in r and r[key] is not None]
        present = sum(1 for r in records if key in r)
        nullable = (total - present) / total >= 0.1 or len(values) < total

        # Unwrap single-level lists for type detection
        flat_values: list[Any] = []
        for v in values:
            if isinstance(v, list):
                flat_values.append(v)  # keep as-is; will detect "array"
            else:
                flat_values.append(v)

        data_type = _detect_type(flat_values, field_name=key)
        is_pii = _is_pii(key)

        # Collect a few sample values (non-PII only, for safety)
        sample_vals: list[Any] = []
        if not is_pii:
            for v in values[:3]:
                sample_vals.append(
                    v if not isinstance(v, (dict, list)) else str(v)[:80]
                )

        fields.append(
            {
                "name": key,
                "data_type": data_type,
                "nullable": nullable,
                "is_pii": is_pii,
                "description": "",
                "ordinal": ordinal,
                "sample_values": sample_vals,
            }
        )

    return fields


def infer_from_csv(
    headers: list[str],
    sample_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Infer field definitions from CSV headers + sample rows."""
    # Delegate to JSON inference using the sample rows as records
    return infer_from_json(sample_rows or [{h: None for h in headers}])
