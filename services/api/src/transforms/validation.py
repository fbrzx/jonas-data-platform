"""SQL validation utilities for transforms — pure functions, no DB access."""

import re

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_ALLOWED_STMT = re.compile(
    r"^\s*(SELECT|INSERT\s+OR\s+REPLACE|INSERT\s+OR\s+IGNORE|CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?TABLE)",
    re.IGNORECASE | re.DOTALL,
)


def split_sql_statements(sql: str) -> list[str]:
    """Split semicolon-delimited SQL into individual non-empty statements.

    Strips leading comment lines so a statement beginning with comments
    is not mistakenly treated as empty.
    """
    stmts = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            stmts.append(cleaned)
    return stmts


def validate_transform_sql(sql: str) -> None:
    """Raise ValueError if any statement uses forbidden operations."""
    for stmt in split_sql_statements(sql):
        if not _ALLOWED_STMT.match(stmt):
            raise ValueError(
                "Transform SQL must only contain SELECT, INSERT OR REPLACE, "
                "INSERT OR IGNORE, or CREATE TABLE statements. "
                "DROP, DELETE, UPDATE, and TRUNCATE are not permitted."
            )


def extract_select_blocks(sql: str) -> list[str]:
    """Return all SELECT sub-queries from a (possibly multi-statement) SQL block.

    Used for dry-run validation — executes only the SELECT parts,
    not CREATE TABLE or INSERT INTO (which reference tables that may not exist yet).
    """
    blocks: list[str] = []
    for stmt in split_sql_statements(sql):
        m = re.search(r"(?i)\bAS\s+(SELECT\b.+)", stmt, re.DOTALL)
        if m:
            blocks.append(m.group(1).strip())
            continue
        m = re.search(
            r"(?i)\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+\S+\s+(SELECT\b.+)", stmt, re.DOTALL
        )
        if m:
            blocks.append(m.group(1).strip())
            continue
        if re.match(r"(?i)\s*SELECT\b", stmt):
            blocks.append(stmt)
    return blocks


def validate_identifier(value: str, field_name: str) -> str:
    candidate = value.strip().lower()
    if not _SAFE_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"Invalid {field_name}: {value!r}")
    return candidate


def safe_table_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip().lower())
    cleaned = cleaned.strip("_")
    if not cleaned:
        return "transform_output"
    if cleaned[0].isdigit():
        return f"t_{cleaned}"
    return cleaned
