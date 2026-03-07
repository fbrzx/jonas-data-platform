"""StorageBackend protocol — the single abstraction over DuckDB / MotherDuck.

All code that previously called ``get_conn()`` directly can continue to do so;
``get_conn()`` now delegates to the active backend's ``.conn`` property.  New
code should prefer ``get_backend()`` and use the higher-level helper methods
(``execute``, ``fetch``, ``fetchone``) so that future backends (Postgres, cloud
DuckDB proxies, etc.) can satisfy the same interface without holding a raw
DuckDB connection.

Backends are instantiated by ``src.db.connection`` based on settings:

  MOTHERDUCK_TOKEN set  →  MotherDuckBackend
  DUCKDB_PATH set       →  LocalDuckDBBackend (file)
  (neither)             →  LocalDuckDBBackend (":memory:", tests/CI)
"""

from __future__ import annotations

from typing import Any, Protocol

import duckdb


class StorageBackend(Protocol):
    """Minimal interface required by every storage backend."""

    # ── Raw connection (backward compat) ──────────────────────────────────────

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        """Return the underlying DuckDB connection.

        Backends that wrap a different engine should raise ``NotImplementedError``
        here and only expose the higher-level helpers.
        """
        ...

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def open(self) -> None:
        """Open / initialise the connection."""
        ...

    async def close(self) -> None:
        """Close the connection gracefully."""
        ...

    # ── Query helpers ─────────────────────────────────────────────────────────

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        """Execute a statement, discarding any result set."""
        ...

    def fetch(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        """Execute a query and return all rows."""
        ...

    def fetchone(self, sql: str, params: list[Any] | None = None) -> tuple | None:
        """Execute a query and return the first row (or None)."""
        ...

    # ── Schema introspection ──────────────────────────────────────────────────

    def list_schemas(self) -> list[str]:
        """Return all schema names visible in the current connection."""
        ...

    def create_schema(self, name: str) -> None:
        """Create a schema if it does not already exist."""
        ...
