"""LocalDuckDBBackend — wraps a local DuckDB file or in-memory connection."""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import duckdb

_log = logging.getLogger("db.backends.local")


class LocalDuckDBBackend:
    """StorageBackend backed by a local DuckDB file (or in-memory for tests)."""

    def __init__(self, path: str = ":memory:") -> None:
        self._path = path
        self._conn: duckdb.DuckDBPyConnection | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def open(self) -> None:
        if self._path == ":memory:":
            self._conn = duckdb.connect(":memory:")
            _log.info("[local] connected to in-memory DuckDB")
            return

        db_path = pathlib.Path(self._path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = duckdb.connect(str(db_path))
            _log.info("[local] connected to %s", db_path)
        except duckdb.InternalException as exc:
            # Corrupted WAL — back it up and retry.
            wal_path = pathlib.Path(str(db_path) + ".wal")
            if wal_path.exists():
                backup = wal_path.with_suffix(".wal.corrupt")
                _log.critical(
                    "DuckDB WAL replay failed: %s. Backing up to %s and retrying.",
                    exc,
                    backup,
                )
                wal_path.rename(backup)
                self._conn = duckdb.connect(str(db_path))
            else:
                raise

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            _log.info("[local] connection closed")

    # ── Raw connection ────────────────────────────────────────────────────────

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("LocalDuckDBBackend not opened — call open() first")
        return self._conn

    # ── Query helpers ─────────────────────────────────────────────────────────

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        self.conn.execute(sql, params or [])

    def fetch(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        return self.conn.execute(sql, params or []).fetchall()

    def fetchone(self, sql: str, params: list[Any] | None = None) -> tuple | None:
        return self.conn.execute(sql, params or []).fetchone()

    # ── Schema helpers ────────────────────────────────────────────────────────

    def list_schemas(self) -> list[str]:
        rows = self.fetch(
            "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name"
        )
        return [r[0] for r in rows]

    def create_schema(self, name: str) -> None:
        self.execute(f"CREATE SCHEMA IF NOT EXISTS {name}")  # noqa: S608
