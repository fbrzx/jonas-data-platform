"""Shared test fixtures — ensures db._backend is always clean between tests."""

import pytest


@pytest.fixture(autouse=True)
def _reset_db_backend():
    """Ensure db._backend does not leak between tests.

    test_health.py triggers the FastAPI lifespan via ASGITransport(app=app), which calls
    init_connection() and sets db._backend to a file-based DuckDB. Tests that rely on
    their own in-memory backend (e.g. test_smart_import.py) fail if this leaked state
    is not cleaned up.

    This fixture records the backend before the test, and after the test, if the backend
    changed (meaning something leaked a new one), it nullifies it. Test-specific fixtures
    like _isolated_db manage their own cleanup on teardown (after this one yields).
    """
    from src.db import connection as db

    prev_backend = db._backend
    yield
    # If something set a *new* backend during the test (e.g. lifespan init), clear it.
    # Test-specific fixtures that manage their own backend (like _isolated_db) will have
    # already set db._backend = None in their teardown, so this is a no-op for them.
    if db._backend is not None and db._backend is not prev_backend:
        db._backend = None
