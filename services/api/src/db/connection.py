"""DuckDB connection management — now backed by StorageBackend implementations.

Priority (auto-detected from settings):
  1. MOTHERDUCK_TOKEN set            → MotherDuckBackend
  2. DUCKDB_PATH set                 → LocalDuckDBBackend (file)
  3. fallback                        → LocalDuckDBBackend (":memory:", tests/CI)

Backward compatibility
----------------------
``get_conn()`` is preserved for all existing call sites — it delegates to
``get_backend().conn`` so nothing breaks.  New code should prefer
``get_backend()`` and its higher-level helpers (``execute``, ``fetch``, etc.).
"""

from __future__ import annotations

import logging

import duckdb

from src.config import settings
from src.db.backend import StorageBackend
from src.db.backends import LocalDuckDBBackend, MotherDuckBackend

_log = logging.getLogger("db.connection")
_backend: StorageBackend | None = None


async def init_connection() -> None:
    """Instantiate and open the active StorageBackend."""
    global _backend
    if settings.motherduck_token:
        db_per_tenant = getattr(settings, "motherduck_db_per_tenant", False)
        _backend = MotherDuckBackend(
            token=settings.motherduck_token,
            db_per_tenant=db_per_tenant,
        )
    else:
        path = settings.duckdb_path or ":memory:"
        _backend = LocalDuckDBBackend(path=path)

    await _backend.open()


async def close_connection() -> None:
    """Close the active backend on shutdown."""
    global _backend
    if _backend is not None:
        await _backend.close()
        _backend = None


def get_backend() -> StorageBackend:
    """Return the active StorageBackend.  Raises if not yet initialised."""
    if _backend is None:
        raise RuntimeError(
            "Storage backend not initialised. Call init_connection() first."
        )
    return _backend


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return the underlying DuckDB connection (backward-compat shim).

    Prefer ``get_backend()`` for new code — this exists solely so the ~18
    existing call sites continue to work without modification.
    """
    return get_backend().conn
