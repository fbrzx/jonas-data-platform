"""DuckDB connection management.

Priority:
  1. MOTHERDUCK_TOKEN set → connect to MotherDuck ("md:")
  2. DUCKDB_PATH set      → connect to local file (persisted)
  3. fallback             → in-memory (tests / CI)
"""

import logging
import os
import pathlib

import duckdb

from src.config import settings

_log = logging.getLogger("db.connection")
_conn: duckdb.DuckDBPyConnection | None = None


async def init_connection() -> None:
    """Open the DuckDB connection on startup."""
    global _conn
    if settings.motherduck_token:
        os.environ.setdefault("MOTHERDUCK_TOKEN", settings.motherduck_token)
        _conn = duckdb.connect("md:")
    elif settings.duckdb_path:
        db_path = pathlib.Path(settings.duckdb_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _conn = duckdb.connect(str(db_path))
        except duckdb.InternalException as exc:
            # Corrupted WAL — back it up (for manual recovery) and retry.
            # Data in the WAL that wasn't checkpointed will be lost.
            wal_path = pathlib.Path(str(db_path) + ".wal")
            if wal_path.exists():
                backup = wal_path.with_suffix(".wal.corrupt")
                _log.critical(
                    "DuckDB WAL replay failed: %s. "
                    "Backing up WAL to %s and retrying. "
                    "Un-checkpointed data may be lost — inspect the backup.",
                    exc,
                    backup,
                )
                wal_path.rename(backup)
                _conn = duckdb.connect(str(db_path))
            else:
                raise
    else:
        _conn = duckdb.connect(":memory:")


async def close_connection() -> None:
    """Close the connection on shutdown."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return the active connection, raising if not initialised."""
    if _conn is None:
        raise RuntimeError(
            "Database connection not initialised. Call init_connection() first."
        )
    return _conn
