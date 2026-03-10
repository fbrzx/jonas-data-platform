"""Strawberry GraphQL schema — silver and gold entity access via Redis cache.

All queries require authentication (handled by the existing AuthMiddleware).
RBAC mirrors the REST catalogue:
  - owner / admin / engineer / analyst → silver + gold
  - viewer                             → gold only

Rows are returned as JSON-encoded strings (one per row) so that the schema
stays static even though entity column sets vary per tenant.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import strawberry
from strawberry.types import Info

from src.cache import redis as cache
from src.catalogue.service import get_entity_fields, list_entities
from src.db.connection import get_conn
from src.db.tenant_schemas import layer_schema

logger = logging.getLogger(__name__)

# Layers each role may query via GraphQL (silver + gold only — bronze is raw)
_ROLE_LAYERS: dict[str, list[str]] = {
    "owner": ["silver", "gold"],
    "admin": ["silver", "gold"],
    "engineer": ["silver", "gold"],
    "analyst": ["silver", "gold"],
    "viewer": ["gold"],
}

_MAX_LIMIT = 500


def _user(info: Info) -> dict[str, Any]:  # type: ignore[type-arg]
    return info.context["request"].state.user or {}


def _allowed_layers(role: str | None) -> list[str]:
    return _ROLE_LAYERS.get(role or "", ["gold"])


def _has_pii_access(role: str | None) -> bool:
    return role in ("owner", "admin")


# ── Types ─────────────────────────────────────────────────────────────────────


@strawberry.type
class EntityField:
    name: str
    data_type: str
    is_pii: bool
    nullable: bool
    description: str


@strawberry.type
class CatalogueEntity:
    id: strawberry.ID
    name: str
    layer: str
    description: str
    fields: list[EntityField]


@strawberry.type
class EntityData:
    """Row data for a single entity.

    `rows` contains one JSON-encoded object per row, e.g.:
      '{"id": 1, "amount": 99.9, "customer": "Acme"}'

    `cached` is True when the result was served from Redis.
    """

    entity_name: str
    layer: str
    columns: list[str]
    rows: list[str]
    count: int
    cached: bool


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fetch_rows(
    tenant_id: str, layer: str, entity_name: str, limit: int, role: str | None
) -> dict[str, Any]:
    """Query DuckDB directly and apply PII masking if needed."""
    table_ref = f"{layer_schema(layer, tenant_id)}.{entity_name}"
    conn = get_conn()
    try:
        rows_raw = conn.execute(
            f"SELECT * FROM {table_ref} LIMIT {limit}"  # noqa: S608
        ).fetchall()
        cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        rows = [dict(zip(cols, row)) for row in rows_raw]

        if not _has_pii_access(role):
            # Find PII fields from catalogue
            from src.catalogue.service import get_entity as _get_entity

            entity = _get_entity(
                # look up by name+layer — find entity id first
                _resolve_entity_id(entity_name, layer, tenant_id) or "",
                tenant_id,
            )
            if entity:
                fields = get_entity_fields(str(entity["id"]))
                pii_names = {f["name"] for f in fields if f.get("is_pii")}
                if pii_names:
                    from src.agent.pii import mask_rows

                    rows = mask_rows(rows, pii_names, False)

        return {"columns": cols, "rows": rows}
    except Exception as exc:
        logger.warning("graphql: failed to query %s: %s", table_ref, exc)
        return {"columns": [], "rows": []}


def _resolve_entity_id(entity_name: str, layer: str, tenant_id: str) -> str | None:
    try:
        row = (
            get_conn()
            .execute(
                "SELECT id FROM catalogue.entity WHERE name = ? AND layer = ? AND tenant_id = ?",
                [entity_name, layer, tenant_id],
            )
            .fetchone()
        )
        return str(row[0]) if row else None
    except Exception:
        return None


# ── Query ─────────────────────────────────────────────────────────────────────


@strawberry.type
class Query:
    @strawberry.field(
        description="List silver and gold entities accessible to the caller."
    )
    def entities(
        self,
        info: Info,  # type: ignore[type-arg]
        layer: str | None = None,
    ) -> list[CatalogueEntity]:
        user = _user(info)
        tenant_id: str = user.get("tenant_id") or ""
        role: str | None = user.get("role")
        if not tenant_id:
            return []

        allowed = _allowed_layers(role)
        all_entities = list_entities(tenant_id)

        result: list[CatalogueEntity] = []
        for e in all_entities:
            e_layer = str(e.get("layer", ""))
            if e_layer not in allowed:
                continue
            if layer and e_layer != layer:
                continue
            raw_fields = get_entity_fields(str(e["id"]))
            gql_fields = [
                EntityField(
                    name=str(f["name"]),
                    data_type=str(f.get("data_type", "string")),
                    is_pii=bool(f.get("is_pii", False)),
                    nullable=bool(f.get("nullable", True)),
                    description=str(f.get("description", "")),
                )
                for f in raw_fields
            ]
            result.append(
                CatalogueEntity(
                    id=strawberry.ID(str(e["id"])),
                    name=str(e["name"]),
                    layer=e_layer,
                    description=str(e.get("description", "")),
                    fields=gql_fields,
                )
            )
        return result

    @strawberry.field(
        description=(
            "Fetch rows for a silver or gold entity. "
            "Results are cached in Redis for 10 minutes and invalidated when the entity is updated."
        )
    )
    def entity_data(
        self,
        info: Info,  # type: ignore[type-arg]
        name: str,
        layer: str,
        limit: int = 100,
    ) -> EntityData:
        user = _user(info)
        tenant_id: str = user.get("tenant_id") or ""
        role: str | None = user.get("role")

        if not tenant_id:
            return EntityData(
                entity_name=name,
                layer=layer,
                columns=[],
                rows=[],
                count=0,
                cached=False,
            )

        allowed = _allowed_layers(role)
        if layer not in allowed:
            return EntityData(
                entity_name=name,
                layer=layer,
                columns=[],
                rows=[],
                count=0,
                cached=False,
            )

        limit = min(max(1, limit), _MAX_LIMIT)

        # Try cache first (only for full-fetch requests up to default limit)
        cached_hit = False
        if limit <= 100:
            cached = cache.get_cached(tenant_id, layer, name)
            if cached:
                rows_json = [json.dumps(r) for r in cached["rows"][:limit]]
                return EntityData(
                    entity_name=name,
                    layer=layer,
                    columns=cached["columns"],
                    rows=rows_json,
                    count=len(rows_json),
                    cached=True,
                )

        # Cache miss → query DuckDB
        data = _fetch_rows(tenant_id, layer, name, limit, role)
        columns: list[str] = data["columns"]
        rows: list[dict[str, Any]] = data["rows"]

        # Populate cache (only for the default limit so we cache a reusable snapshot)
        if limit <= 100 and rows:
            cache.set_cached(tenant_id, layer, name, {"columns": columns, "rows": rows})

        rows_json = [json.dumps(r, default=str) for r in rows]
        return EntityData(
            entity_name=name,
            layer=layer,
            columns=columns,
            rows=rows_json,
            count=len(rows_json),
            cached=cached_hit,
        )


schema = strawberry.Schema(query=Query)
