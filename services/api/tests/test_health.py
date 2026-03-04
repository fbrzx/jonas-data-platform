"""Smoke test — verifies the FastAPI app starts and /health returns 200."""

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.fixture(autouse=True)
async def _init_db() -> None:
    """Use an in-memory DuckDB for tests."""
    from src.db import connection as db
    import duckdb

    db._conn = duckdb.connect(":memory:")
    yield
    db._conn.close()
    db._conn = None


@pytest.mark.asyncio
async def test_health() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
