"""Tenant isolation tests.

Proves that data belonging to tenant-A is never visible to tenant-B,
even when both share the same DuckDB instance.  Tests exercise the
service layer directly (no HTTP) so they run fast without a full server.
"""

import duckdb
import pytest

from src.db import connection as db
from src.db.init import bootstrap


@pytest.fixture(autouse=True)
def _isolated_db() -> None:
    """Fresh in-memory DuckDB + full bootstrap for each test."""
    db._conn = duckdb.connect(":memory:")
    bootstrap()
    yield
    db._conn.close()
    db._conn = None


# ── Catalogue isolation ────────────────────────────────────────────────────────


def test_list_entities_scoped_to_tenant() -> None:
    from src.catalogue.service import create_entity, list_entities

    create_entity({"name": "orders", "layer": "bronze"}, tenant_id="tenant-a")
    create_entity({"name": "products", "layer": "bronze"}, tenant_id="tenant-b")

    a_entities = list_entities("tenant-a")
    b_entities = list_entities("tenant-b")

    a_names = {e["name"] for e in a_entities}
    b_names = {e["name"] for e in b_entities}

    assert "orders" in a_names
    assert "products" not in a_names  # tenant-b's entity must not leak

    assert "products" in b_names
    assert "orders" not in b_names  # tenant-a's entity must not leak


def test_get_entity_cross_tenant_returns_none() -> None:
    from src.catalogue.service import create_entity, get_entity

    entity = create_entity({"name": "secret_table", "layer": "gold"}, tenant_id="tenant-a")
    entity_id = entity["id"]

    # tenant-b must not be able to fetch tenant-a's entity by ID
    result = get_entity(entity_id, tenant_id="tenant-b")
    assert result is None


def test_update_entity_cross_tenant_returns_none() -> None:
    from src.catalogue.service import create_entity, get_entity, update_entity

    entity = create_entity({"name": "private_data", "layer": "silver"}, tenant_id="tenant-a")
    entity_id = entity["id"]

    # tenant-b attempts to overwrite the name — must be a no-op
    result = update_entity(entity_id, {"name": "hacked"}, tenant_id="tenant-b")
    assert result is None

    # Original record for tenant-a must be unchanged
    original = get_entity(entity_id, tenant_id="tenant-a")
    assert original is not None
    assert original["name"] == "private_data"


# ── Transform isolation ────────────────────────────────────────────────────────


def test_list_transforms_scoped_to_tenant() -> None:
    from src.transforms.service import create_transform, list_transforms

    create_transform(
        {
            "name": "a_transform",
            "source_layer": "bronze",
            "target_layer": "silver",
            "sql": "CREATE OR REPLACE TABLE silver.a AS SELECT 1 AS x",
        },
        tenant_id="tenant-a",
        created_by="user-a",
    )
    create_transform(
        {
            "name": "b_transform",
            "source_layer": "bronze",
            "target_layer": "silver",
            "sql": "CREATE OR REPLACE TABLE silver.b AS SELECT 2 AS x",
        },
        tenant_id="tenant-b",
        created_by="user-b",
    )

    a_transforms = list_transforms("tenant-a")
    b_transforms = list_transforms("tenant-b")

    a_names = {t["name"] for t in a_transforms}
    b_names = {t["name"] for t in b_transforms}

    assert "a_transform" in a_names
    assert "b_transform" not in a_names

    assert "b_transform" in b_names
    assert "a_transform" not in b_names


def test_get_transform_cross_tenant_returns_none() -> None:
    from src.transforms.service import create_transform, get_transform

    transform = create_transform(
        {
            "name": "secret_pipeline",
            "source_layer": "bronze",
            "target_layer": "silver",
            "sql": "CREATE OR REPLACE TABLE silver.secret AS SELECT 1 AS x",
        },
        tenant_id="tenant-a",
        created_by="user-a",
    )
    transform_id = transform["id"]

    result = get_transform(transform_id, tenant_id="tenant-b")
    assert result is None


# ── Connector isolation ────────────────────────────────────────────────────────


def test_list_connectors_scoped_to_tenant() -> None:
    from src.integrations.service import create_integration, list_integrations

    create_integration(
        {"name": "a_webhook", "connector_type": "webhook"},
        tenant_id="tenant-a",
    )
    create_integration(
        {"name": "b_webhook", "connector_type": "webhook"},
        tenant_id="tenant-b",
    )

    a_connectors = list_integrations("tenant-a")
    b_connectors = list_integrations("tenant-b")

    a_names = {c["name"] for c in a_connectors}
    b_names = {c["name"] for c in b_connectors}

    assert "a_webhook" in a_names
    assert "b_webhook" not in a_names

    assert "b_webhook" in b_names
    assert "a_webhook" not in b_names


def test_get_connector_cross_tenant_returns_none() -> None:
    from src.integrations.service import create_integration, get_integration

    connector = create_integration(
        {"name": "private_feed", "connector_type": "webhook"},
        tenant_id="tenant-a",
    )
    connector_id = connector["id"]

    result = get_integration(connector_id, tenant_id="tenant-b")
    assert result is None


# ── RBAC role coverage ─────────────────────────────────────────────────────────


def test_all_five_roles_defined() -> None:
    from src.auth.permissions import ROLE_DEFAULTS

    expected_roles = {"owner", "admin", "engineer", "analyst", "viewer"}
    assert set(ROLE_DEFAULTS.keys()) == expected_roles


def test_owner_has_approve_on_users() -> None:
    from src.auth.permissions import Action, Resource, can

    assert can({"role": "owner"}, Resource.USER, Action.APPROVE)
    # Admin does NOT have approve on users (only owner does)
    assert not can({"role": "admin"}, Resource.USER, Action.APPROVE)


def test_engineer_can_approve_transforms_but_not_manage_users() -> None:
    from src.auth.permissions import Action, Resource, can

    assert can({"role": "engineer"}, Resource.TRANSFORM, Action.APPROVE)
    assert can({"role": "engineer"}, Resource.CATALOGUE, Action.APPROVE)
    assert not can({"role": "engineer"}, Resource.USER, Action.WRITE)
    assert not can({"role": "engineer"}, Resource.USER, Action.ADMIN)


def test_analyst_cannot_approve_anything() -> None:
    from src.auth.permissions import Action, Resource, can

    assert not can({"role": "analyst"}, Resource.TRANSFORM, Action.APPROVE)
    assert not can({"role": "analyst"}, Resource.CATALOGUE, Action.APPROVE)
    assert not can({"role": "analyst"}, Resource.INTEGRATION, Action.APPROVE)


def test_viewer_is_read_only() -> None:
    from src.auth.permissions import Action, Resource, can

    for resource in Resource:
        assert can({"role": "viewer"}, resource, Action.READ) or resource == Resource.USER
        assert not can({"role": "viewer"}, resource, Action.WRITE)
        assert not can({"role": "viewer"}, resource, Action.APPROVE)
        assert not can({"role": "viewer"}, resource, Action.ADMIN)


def test_unknown_role_defaults_to_viewer_permissions() -> None:
    from src.auth.permissions import Action, Resource, can

    # Unknown role → ROLE_DEFAULTS.get() returns {} → no permissions
    assert not can({"role": "superuser"}, Resource.CATALOGUE, Action.WRITE)
    assert not can({"role": "superuser"}, Resource.AGENT, Action.READ)
