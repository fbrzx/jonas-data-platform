"""Database + schema bootstrapping.

Runs the DuckDB DDL migration against the active connection (local or MotherDuck).
The DDL file itself creates all required schemas (platform, catalogue, transforms,
integrations, permissions, audit, bronze, silver, gold).
"""

import pathlib

from src.db.connection import get_conn

_DDL_FILENAME = "001_core_duckdb.sql"


def _find_ddl() -> pathlib.Path:
    """Search upward from this file for db/001_core_duckdb.sql.

    Works in both layouts:
      Docker:   /app/src/db/init.py  → /app/db/
      Local dev: services/api/src/db/init.py → jonas-data-platform/db/
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "db" / _DDL_FILENAME
        if candidate.exists():
            return candidate
    # Explicit fallback for Docker image layout
    return pathlib.Path("/app/db") / _DDL_FILENAME


def bootstrap() -> None:
    """Idempotently run DDL migrations against the active connection."""
    conn = get_conn()
    DDL_PATH = _find_ddl()

    if not DDL_PATH.exists():
        print(f"[db.init] DDL file not found at {DDL_PATH} — skipping")
        return

    ddl = DDL_PATH.read_text()
    # DuckDB execexecutemany doesn't handle multi-statement strings well;
    # split on semicolons and execute each statement individually.
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    for stmt in statements:
        try:
            conn.execute(stmt)
        except Exception as exc:
            print(f"[db.init] Warning: {exc!r} for statement starting: {stmt[:60]!r}")

    print(f"[db.init] Bootstrap complete ({len(statements)} statements)")
