"""Tests for Phase 12: paginated API pull, uniform payload format, smart_import, and flatten SQL."""

import json
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from src.db import connection as db
from src.db.backends.local import LocalDuckDBBackend
from src.db.init import bootstrap


TENANT = "tenant-test"


@pytest.fixture(autouse=True)
def _isolated_db():
    """Fresh in-memory DuckDB + full bootstrap for each test."""
    backend = LocalDuckDBBackend(":memory:")
    # Open synchronously — LocalDuckDBBackend.open() is sync under the hood.
    backend._conn = duckdb.connect(":memory:")
    db._backend = backend
    bootstrap()
    # Provision test tenant schemas (bootstrap only creates for tenant-acme)
    conn = db.get_conn()
    from src.db.tenant_schemas import safe_tenant_id

    tid = safe_tenant_id(TENANT)
    for layer in ("bronze", "silver", "gold"):
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {layer}_{tid}")
    yield
    backend._conn.close()
    backend._conn = None
    db._backend = None


# ── WS2: Uniform payload format ─────────────────────────────────────────────


def test_batch_csv_lands_as_payload():
    """CSV rows should be stored as JSON payloads via land_webhook (uniform format)."""
    from src.integrations.ingest import land_batch_csv

    csv_content = b"name,age,city\nAlice,30,NYC\nBob,25,LA"
    # Spy on land_webhook to capture the payloads it receives
    captured_calls: list[dict] = []
    original_land_webhook = __import__(
        "src.integrations.ingest", fromlist=["land_webhook"]
    ).land_webhook

    def spy_webhook(source, data, metadata, tenant_id, **kwargs):
        captured_calls.append({"data": data, "metadata": metadata})
        return original_land_webhook(source, data, metadata, tenant_id, **kwargs)

    with patch("src.integrations.ingest.land_webhook", side_effect=spy_webhook), \
         patch("src.storage.parquet.export_bronze", return_value=None):
        result = land_batch_csv("test_csv", csv_content, TENANT)

    assert result["rows_received"] == 2
    assert result["rows_landed"] == 2
    assert not result["errors"]

    # Verify each CSV row was passed as a dict payload to land_webhook
    assert len(captured_calls) == 2
    assert captured_calls[0]["data"] == {"name": "Alice", "age": "30", "city": "NYC"}
    assert captured_calls[1]["data"] == {"name": "Bob", "age": "25", "city": "LA"}


def test_batch_csv_metadata_has_row_number():
    """Each CSV row should have row_number in metadata for traceability."""
    from src.integrations.ingest import land_batch_csv

    csv_content = b"user_id,value\n1,foo\n2,bar"
    captured_calls: list[dict] = []
    original_land_webhook = __import__(
        "src.integrations.ingest", fromlist=["land_webhook"]
    ).land_webhook

    def spy_webhook(source, data, metadata, tenant_id, **kwargs):
        captured_calls.append({"data": data, "metadata": metadata})
        return original_land_webhook(source, data, metadata, tenant_id, **kwargs)

    with patch("src.integrations.ingest.land_webhook", side_effect=spy_webhook), \
         patch("src.storage.parquet.export_bronze", return_value=None):
        result = land_batch_csv("csv_meta2", csv_content, TENANT)
    assert result["rows_landed"] == 2

    # Verify metadata includes format=csv and sequential row_number
    assert len(captured_calls) == 2
    row_numbers = set()
    for call in captured_calls:
        meta = call["metadata"]
        assert meta["format"] == "csv"
        row_numbers.add(meta["row_number"])
    assert row_numbers == {0, 1}


def test_batch_csv_empty():
    """Empty CSV should return 0 rows without error."""
    from src.integrations.ingest import land_batch_csv

    result = land_batch_csv("empty_csv", b"", TENANT)
    assert result["rows_received"] == 0
    assert result["rows_landed"] == 0


# ── WS1: Paginated API pull ─────────────────────────────────────────────────


def test_api_pull_no_pagination():
    """Backward-compatible single fetch without pagination config."""
    from src.integrations.ingest import land_api_pull

    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"id": "1", "name": "Alice"},
        {"id": "2", "name": "Bob"},
    ]
    mock_response.status_code = 200
    mock_response.headers = {}

    with patch("src.integrations.ingest._fetch_page", return_value=mock_response):
        result = land_api_pull(
            "https://api.example.com/users", {}, "users", TENANT,
        )

    assert result["rows_received"] == 2
    assert result["rows_landed"] == 2
    assert not result["errors"]


def test_api_pull_with_json_path():
    """json_path should extract records from nested response."""
    from src.integrations.ingest import land_api_pull

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "items": [
                {"id": "1", "val": "a"},
                {"id": "2", "val": "b"},
            ]
        },
        "meta": {"total": 2},
    }
    mock_response.status_code = 200
    mock_response.headers = {}

    with patch("src.integrations.ingest._fetch_page", return_value=mock_response):
        result = land_api_pull(
            "https://api.example.com/data", {}, "nested", TENANT,
            json_path="data.items",
        )

    assert result["rows_received"] == 2
    assert result["rows_landed"] == 2


def test_api_pull_offset_pagination():
    """Offset pagination should fetch multiple pages until records < page_size."""
    from src.integrations.ingest import land_api_pull

    call_count = 0

    def mock_fetch(url, headers, params=None):
        nonlocal call_count
        resp = MagicMock()
        resp.headers = {}
        if call_count == 0:
            resp.json.return_value = {"data": [{"id": "1"}, {"id": "2"}]}
        elif call_count == 1:
            resp.json.return_value = {"data": [{"id": "3"}]}  # < page_size → stop
        else:
            resp.json.return_value = {"data": []}
        call_count += 1
        return resp

    with patch("src.integrations.ingest._fetch_page", side_effect=mock_fetch):
        result = land_api_pull(
            "https://api.example.com/items", {}, "offset_test", TENANT,
            json_path="data",
            pagination={"strategy": "offset", "page_size": 2},
        )

    assert result["rows_received"] == 3
    assert result["rows_landed"] == 3
    assert result["pages_fetched"] == 2


def test_api_pull_cursor_pagination():
    """Cursor pagination should follow cursor_path until null."""
    from src.integrations.ingest import land_api_pull

    call_count = 0

    def mock_fetch(url, headers, params=None):
        nonlocal call_count
        resp = MagicMock()
        resp.headers = {}
        if call_count == 0:
            resp.json.return_value = {
                "items": [{"id": "1"}],
                "meta": {"next_cursor": "abc123"},
            }
        elif call_count == 1:
            resp.json.return_value = {
                "items": [{"id": "2"}],
                "meta": {"next_cursor": None},
            }
        call_count += 1
        return resp

    with patch("src.integrations.ingest._fetch_page", side_effect=mock_fetch):
        result = land_api_pull(
            "https://api.example.com/items", {}, "cursor_test", TENANT,
            json_path="items",
            pagination={
                "strategy": "cursor",
                "cursor_param": "cursor",
                "cursor_path": "meta.next_cursor",
            },
        )

    assert result["rows_received"] == 2
    assert result["rows_landed"] == 2
    assert result["pages_fetched"] == 2


def test_api_pull_max_pages_cap():
    """Pagination should respect max_pages limit."""
    from src.integrations.ingest import land_api_pull

    call_count = 0

    def mock_fetch(url, headers, params=None):
        nonlocal call_count
        resp = MagicMock()
        resp.headers = {}
        # Always return full page to keep paginating
        resp.json.return_value = {"data": [{"id": str(call_count)}]}
        call_count += 1
        return resp

    with patch("src.integrations.ingest._fetch_page", side_effect=mock_fetch):
        result = land_api_pull(
            "https://api.example.com/items", {}, "cap_test", TENANT,
            json_path="data",
            pagination={"strategy": "offset", "page_size": 1, "max_pages": 3},
        )

    assert result["pages_fetched"] == 3
    assert result["rows_received"] == 3


# ── WS3: Flatten SQL generator ──────────────────────────────────────────────


def test_generate_flatten_sql_types():
    """Generated SQL should use correct DuckDB types for each field."""
    from src.agent.handlers.flatten_sql import generate_flatten_sql

    fields = [
        {"name": "id", "data_type": "string"},
        {"name": "amount", "data_type": "float"},
        {"name": "count", "data_type": "int"},
        {"name": "active", "data_type": "bool"},
        {"name": "created_at", "data_type": "timestamp"},
    ]

    sql = generate_flatten_sql("orders", fields, "id", TENANT)

    # Verify CREATE TABLE structure
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "id VARCHAR PRIMARY KEY" in sql
    assert "amount DOUBLE" in sql
    assert "count BIGINT" in sql
    assert "active BOOLEAN" in sql
    assert "created_at TIMESTAMP" in sql

    # Verify INSERT OR REPLACE with json_extract
    assert "INSERT OR REPLACE INTO" in sql
    assert "json_extract_string(payload, '$.id') AS id" in sql
    assert "CAST(json_extract(payload, '$.amount') AS DOUBLE) AS amount" in sql
    assert "CAST(json_extract(payload, '$.count') AS BIGINT) AS count" in sql
    assert "WHERE json_extract_string(payload, '$.id') IS NOT NULL" in sql


def test_detect_primary_key():
    """Primary key detection heuristics."""
    from src.agent.handlers.flatten_sql import detect_primary_key

    # Exact "id" field
    assert detect_primary_key([{"name": "id"}, {"name": "name"}]) == "id"

    # Entity-name-based detection
    assert (
        detect_primary_key(
            [{"name": "order_id"}, {"name": "name"}], entity_name="orders"
        )
        == "order_id"
    )

    # First _id field
    assert (
        detect_primary_key([{"name": "user_id"}, {"name": "email"}]) == "user_id"
    )

    # UUID suffix
    assert (
        detect_primary_key([{"name": "record_uuid"}, {"name": "data"}])
        == "record_uuid"
    )

    # No obvious PK
    assert detect_primary_key([{"name": "name"}, {"name": "value"}]) is None


# ── WS3: Smart import handler ───────────────────────────────────────────────


def test_smart_import_sample_json():
    """smart_import with sample_json should create entity, connector, ingest, and transform."""
    from src.agent.handlers.smart_import import handle

    sample = [
        {"id": "1", "name": "Widget", "price": 9.99},
        {"id": "2", "name": "Gadget", "price": 19.99},
    ]

    result_str = handle(
        "smart_import",
        {
            "name": "products",
            "source_type": "sample_json",
            "sample_data": sample,
            "description": "Product catalog",
        },
        tenant_id=TENANT,
        role="admin",
        created_by="test-user",
    )

    result = json.loads(result_str)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["entity_id"]
    assert result["connector_id"]
    assert result["rows_landed"] == 2
    assert result["transform_id"]
    assert result["transform_status"] == "draft — needs admin approval"
    assert result["silver_entity_id"]
    assert "flatten_products" in str(result.get("steps", []))


def test_smart_import_skip_transform():
    """smart_import with skip_transform=true should skip silver setup."""
    from src.agent.handlers.smart_import import handle

    result_str = handle(
        "smart_import",
        {
            "name": "raw_events",
            "source_type": "sample_json",
            "sample_data": [{"event": "click", "ts": "2024-01-01"}],
            "skip_transform": True,
        },
        tenant_id=TENANT,
        role="admin",
        created_by="test-user",
    )

    result = json.loads(result_str)
    assert "error" not in result
    assert result["rows_landed"] == 1
    assert "transform_id" not in result
    assert "silver_entity_id" not in result


def test_smart_import_viewer_denied():
    """Viewers should not be able to use smart_import."""
    from src.agent.handlers.smart_import import handle

    result_str = handle(
        "smart_import",
        {"name": "denied", "source_type": "sample_json", "sample_data": [{"a": 1}]},
        tenant_id=TENANT,
        role="viewer",
        created_by="test-user",
    )

    result = json.loads(result_str)
    assert "error" in result
    assert "Access denied" in result["error"]


def test_smart_import_api_pull():
    """smart_import with api_pull should discover, ingest with pagination, and create transform."""
    from src.agent.handlers.smart_import import handle

    mock_discover_records = [
        {"id": "a1", "value": 100},
        {"id": "a2", "value": 200},
    ]

    # Mock external calls: discover + fetch + parquet export (may fail in test env)
    with patch(
        "src.agent.handlers.smart_import._discover_sample",
        return_value=mock_discover_records,
    ), patch("src.integrations.ingest._fetch_page") as mock_fetch, patch(
        "src.storage.parquet.export_bronze", return_value=None
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": mock_discover_records
        }
        mock_resp.headers = {}
        mock_fetch.return_value = mock_resp

        result_str = handle(
            "smart_import",
            {
                "name": "api_data",
                "source_type": "api_pull",
                "url": "https://api.example.com/data",
                "json_path": "results",
                "headers": {"Authorization": "Bearer test"},
            },
            tenant_id=TENANT,
            role="admin",
            created_by="test-user",
        )

    result = json.loads(result_str)
    assert "error" not in result, f"Got error: {result.get('error')}; steps: {result.get('steps_completed', [])}"
    assert result["entity_id"]
    assert result["connector_id"]
    assert result["rows_landed"] == 2
    assert result["transform_id"]


def test_smart_import_missing_name():
    """smart_import without name should return error."""
    from src.agent.handlers.smart_import import handle

    result_str = handle(
        "smart_import",
        {"source_type": "sample_json", "sample_data": [{"a": 1}]},
        tenant_id=TENANT,
        role="admin",
        created_by="test-user",
    )

    result = json.loads(result_str)
    assert "error" in result
    assert "name" in result["error"]


def test_smart_import_primary_key_override():
    """smart_import should respect primary_key_field override."""
    from src.agent.handlers.smart_import import handle

    result_str = handle(
        "smart_import",
        {
            "name": "custom_pk",
            "source_type": "sample_json",
            "sample_data": [{"record_code": "X1", "val": 42}],
            "primary_key_field": "record_code",
        },
        tenant_id=TENANT,
        role="admin",
        created_by="test-user",
    )

    result = json.loads(result_str)
    assert "error" not in result
    assert "record_code VARCHAR PRIMARY KEY" in result.get("transform_sql", "")


# ── Resolve json_path helper ────────────────────────────────────────────────


def test_resolve_json_path():
    """_resolve_json_path should navigate nested dicts."""
    from src.integrations.ingest import _resolve_json_path

    data = {"a": {"b": {"c": [1, 2, 3]}}}
    assert _resolve_json_path(data, "a.b.c") == [1, 2, 3]
    assert _resolve_json_path(data, "a.b") == {"c": [1, 2, 3]}
    assert _resolve_json_path(data, "") == data
    assert _resolve_json_path(data, "x.y") is None
