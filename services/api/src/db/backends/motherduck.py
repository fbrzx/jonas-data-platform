"""MotherDuckBackend — wraps a MotherDuck cloud connection.

Connection strategy
-------------------
* Default: ``md:`` — connects to the user's default MotherDuck database.
  Schema-per-tenant is maintained within that single database (Phase 5 design).

* Database-per-tenant (opt-in): set ``MOTHERDUCK_DB_PER_TENANT=true``.
  Each tenant gets ``md:jonas_{tenant_slug}``.  The backend exposes
  ``use_tenant_db(tenant_id)`` which switches the active database via
  ``USE <db>``.  Only enable this for new deployments — migrating from
  schema-per-tenant requires a data migration.

Connection pooling
------------------
MotherDuck handles connection multiplexing server-side; the client holds a
single ``md:`` connection per process.  A ``threading.Lock`` guards
``use_tenant_db()`` to prevent concurrent tenant switches.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import duckdb

_log = logging.getLogger("db.backends.motherduck")


class MotherDuckBackend:
    """StorageBackend backed by MotherDuck (cloud DuckDB)."""

    def __init__(self, token: str, db_per_tenant: bool = False) -> None:
        self._token = token
        self._db_per_tenant = db_per_tenant
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def open(self) -> None:
        os.environ.setdefault("MOTHERDUCK_TOKEN", self._token)
        self._conn = duckdb.connect("md:")
        _log.info("[motherduck] connected (db_per_tenant=%s)", self._db_per_tenant)

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            _log.info("[motherduck] connection closed")

    # ── Raw connection ────────────────────────────────────────────────────────

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise RuntimeError("MotherDuckBackend not opened — call open() first")
        return self._conn

    # ── Tenant-aware database switching (db-per-tenant mode) ─────────────────

    def use_tenant_db(self, tenant_slug: str) -> None:
        """Switch the active MotherDuck database for database-per-tenant mode.

        This is a no-op when ``db_per_tenant`` is False (schema-per-tenant).
        Thread-safe: holds the lock for the duration of the USE statement.
        """
        if not self._db_per_tenant:
            return
        db_name = f"jonas_{_safe_slug(tenant_slug)}"
        with self._lock:
            try:
                self.conn.execute(
                    f"CREATE DATABASE IF NOT EXISTS {db_name}"
                )  # noqa: S608
                self.conn.execute(f"USE {db_name}")  # noqa: S608
                _log.debug("[motherduck] switched to database %s", db_name)
            except Exception as exc:
                _log.warning("[motherduck] could not switch to %s: %s", db_name, exc)

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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe_slug(s: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s)
