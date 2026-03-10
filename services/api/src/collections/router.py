"""Collections API — list, export, and import collection tags."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from src.auth.permissions import Action, Resource, require_permission
from src.db.connection import get_conn

router = APIRouter()

_SECRET_KEYS = {"token", "key", "secret", "password", "credential", "auth", "api_key"}


def _parse_json_field(value: Any, default: Any) -> Any:
    """Return `value` as a Python object, parsing it if it's a JSON string.

    DuckDB returns JSON columns as raw strings; calling json.dumps() on them
    again during import would double-encode the data.  This normalises the
    value so the export file always contains proper JSON arrays/objects.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return default
    return value if value is not None else default


def _tenant(request: Request) -> str:
    user = request.state.user or {}
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


def _redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Replace values whose keys look like secrets with a placeholder."""
    return {
        k: ("***" if any(s in k.lower() for s in _SECRET_KEYS) else v)
        for k, v in config.items()
    }


# ── List ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_collections(request: Request) -> list[dict[str, Any]]:
    """Return all distinct collection names for the tenant with item counts."""
    user = request.state.user or {}
    require_permission(user, Resource.CATALOGUE, Action.READ)
    tenant_id = _tenant(request)
    conn = get_conn()

    rows = conn.execute(
        """
        WITH all_collections AS (
            SELECT collection, 'entity'    AS kind FROM catalogue.entity
             WHERE tenant_id = ? AND collection IS NOT NULL
            UNION ALL
            SELECT collection, 'transform' AS kind FROM transforms.transform
             WHERE tenant_id = ? AND collection IS NOT NULL
            UNION ALL
            SELECT collection, 'connector' AS kind FROM integrations.connector
             WHERE tenant_id = ? AND collection IS NOT NULL
        )
        SELECT
            collection,
            COUNT(*) FILTER (WHERE kind = 'entity')    AS entity_count,
            COUNT(*) FILTER (WHERE kind = 'transform') AS transform_count,
            COUNT(*) FILTER (WHERE kind = 'connector') AS connector_count,
            COUNT(*)                                    AS total
        FROM all_collections
        GROUP BY collection
        ORDER BY collection
        """,
        [tenant_id, tenant_id, tenant_id],
    ).fetchall()

    return [
        {
            "name": r[0],
            "entity_count": r[1],
            "transform_count": r[2],
            "connector_count": r[3],
            "total": r[4],
        }
        for r in rows
    ]


# ── Export ───────────────────────────────────────────────────────────────────


@router.get("/{name}/export")
async def export_collection(name: str, request: Request) -> Response:
    """Download a JSON snapshot of all resources in a collection."""
    user = request.state.user or {}
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    tenant_id = _tenant(request)
    conn = get_conn()

    # ── Entities + fields ────────────────────────────────────────────────────
    e_rows = conn.execute(
        "SELECT * FROM catalogue.entity WHERE tenant_id = ? AND collection = ?",
        [tenant_id, name],
    ).fetchall()
    e_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    entities = []
    for row in e_rows:
        entity = dict(zip(e_cols, row))
        f_rows = conn.execute(
            "SELECT name, data_type, nullable, is_pii, description, ordinal, sample_values"
            " FROM catalogue.entity_field WHERE entity_id = ? ORDER BY ordinal",
            [str(entity["id"])],
        ).fetchall()
        f_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        entity["fields"] = [
            {
                **dict(zip(f_cols, f)),
                "sample_values": _parse_json_field(
                    dict(zip(f_cols, f)).get("sample_values"), []
                ),
            }
            for f in f_rows
        ]
        entities.append(
            {
                "name": entity["name"],
                "description": entity.get("description", ""),
                "layer": entity.get("layer", "bronze"),
                "tags": _parse_json_field(entity.get("tags"), []),
                "metadata": _parse_json_field(entity.get("meta"), {}),
                "collection": entity.get("collection"),
                "fields": entity["fields"],
            }
        )

    # ── Transforms ───────────────────────────────────────────────────────────
    t_rows = conn.execute(
        "SELECT * FROM transforms.transform WHERE tenant_id = ? AND collection = ?",
        [tenant_id, name],
    ).fetchall()
    t_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    transforms = []
    for row in t_rows:
        from src.db.tenant_schemas import strip_tenant_schemas

        t = dict(zip(t_cols, row))
        transforms.append(
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "source_layer": t.get("source_layer", "bronze"),
                "target_layer": t.get("target_layer", "silver"),
                # Strip tenant-scoped schema prefixes so the SQL is portable:
                # inject_tenant_schemas() will re-apply the correct prefix at
                # execution time in the target tenant.
                "sql": strip_tenant_schemas(t.get("transform_sql") or ""),
                "tags": _parse_json_field(t.get("tags"), []),
                "trigger_mode": t.get("trigger_mode", "manual"),
                "watch_entities": _parse_json_field(t.get("watch_entities"), []),
                "collection": t.get("collection"),
            }
        )

    # ── Connectors (secrets redacted) ────────────────────────────────────────
    c_rows = conn.execute(
        "SELECT * FROM integrations.connector WHERE tenant_id = ? AND collection = ?",
        [tenant_id, name],
    ).fetchall()
    c_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    connectors = []
    for row in c_rows:
        c = dict(zip(c_cols, row))
        config: dict[str, Any] = {}
        if c.get("config"):
            try:
                from src.security.crypto import decrypt_config

                config = json.loads(decrypt_config(str(c["config"])))
                config = _redact_config(config)
            except Exception:
                pass
        # Resolve linked entity name for portable cross-tenant import
        entity_name: str | None = None
        eid = c.get("target_entity_id")
        if eid:
            ent_row = conn.execute(
                "SELECT name FROM catalogue.entity WHERE id = ?", [str(eid)]
            ).fetchone()
            if ent_row:
                entity_name = str(ent_row[0])
        connectors.append(
            {
                "name": c["name"],
                "description": c.get("description", ""),
                "connector_type": c.get("connector_type", "webhook"),
                "config": config,
                "tags": _parse_json_field(c.get("tags"), []),
                "collection": c.get("collection"),
                "entity_name": entity_name,
                "cron_schedule": c.get("cron_schedule"),
                "status": c.get("status", "active"),
            }
        )

    payload = {
        "collection": name,
        "exported_at": datetime.now(UTC).isoformat(),
        "entities": entities,
        "transforms": transforms,
        "connectors": connectors,
    }
    return Response(
        content=json.dumps(payload, default=str, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="collection-{name}.json"'
        },
    )


# ── Import ───────────────────────────────────────────────────────────────────


@router.post("/import")
async def import_collection(
    request: Request,
    file: UploadFile = File(...),
    overwrite: bool = False,
) -> dict[str, Any]:
    """Import a collection JSON file. Returns a summary of created/skipped items."""
    user = request.state.user or {}
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    tenant_id = _tenant(request)
    user_id = str(user.get("user_id", "import"))

    raw = await file.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    collection_name = data.get("collection")
    if not collection_name:
        raise HTTPException(
            status_code=400, detail="Missing 'collection' field in file"
        )

    from src.catalogue.service import create_entity, create_fields_bulk
    from src.integrations.service import create_integration
    from src.transforms.service import create_transform

    conn = get_conn()
    result: dict[str, Any] = {
        "collection": collection_name,
        "entities": {"created": [], "updated": [], "skipped": []},
        "transforms": {"created": [], "updated": [], "skipped": []},
        "connectors": {"created": [], "skipped": []},
        "errors": [],
    }

    # ── Entities ─────────────────────────────────────────────────────────────
    for e in data.get("entities", []):
        name = e.get("name", "")
        layer = e.get("layer", "bronze")
        try:
            existing = conn.execute(
                "SELECT id FROM catalogue.entity WHERE tenant_id = ? AND name = ? AND layer = ?",
                [tenant_id, name, layer],
            ).fetchone()
            if existing:
                if overwrite:
                    entity_id = str(existing[0])
                    conn.execute(
                        "UPDATE catalogue.entity"
                        " SET description=?, tags=?, meta=?, collection=?, updated_at=?"
                        " WHERE id=? AND tenant_id=?",
                        [
                            e.get("description", ""),
                            json.dumps(e.get("tags", [])),
                            json.dumps(e.get("metadata", {})),
                            collection_name,
                            datetime.now(UTC).isoformat(),
                            entity_id,
                            tenant_id,
                        ],
                    )
                    result["entities"]["updated"].append(name)
                else:
                    result["entities"]["skipped"].append(name)
            else:
                entity = create_entity({**e, "collection": collection_name}, tenant_id)
                if e.get("fields"):
                    create_fields_bulk(
                        str(entity["id"]), e["fields"], created_by=user_id
                    )
                result["entities"]["created"].append(name)
        except Exception as exc:
            result["errors"].append(f"entity '{name}': {exc}")

    # ── Transforms ───────────────────────────────────────────────────────────
    for t in data.get("transforms", []):
        from src.db.tenant_schemas import strip_tenant_schemas as _strip

        name = t.get("name", "")
        # Always strip tenant-scoped schema prefixes from imported SQL so that
        # inject_tenant_schemas() can correctly apply the target tenant's schemas
        # at execution time.  Handles both new exports (already stripped by the
        # export endpoint) and legacy exports that contain raw tenant prefixes.
        clean_sql = _strip(t.get("sql", ""))
        try:
            existing = conn.execute(
                "SELECT id FROM transforms.transform WHERE tenant_id = ? AND name = ?",
                [tenant_id, name],
            ).fetchone()
            if existing:
                if overwrite:
                    transform_id = str(existing[0])
                    conn.execute(
                        "UPDATE transforms.transform SET description=?, transform_sql=?, tags=?,"
                        " collection=?, status='draft', updated_at=? WHERE id=? AND tenant_id=?",
                        [
                            t.get("description", ""),
                            clean_sql,
                            json.dumps(t.get("tags", [])),
                            collection_name,
                            datetime.now(UTC).isoformat(),
                            transform_id,
                            tenant_id,
                        ],
                    )
                    result["transforms"]["updated"].append(name)
                else:
                    result["transforms"]["skipped"].append(name)
            else:
                create_transform(
                    {
                        **t,
                        "collection": collection_name,
                        "transform_sql": clean_sql,
                    },
                    tenant_id,
                    created_by=user_id,
                )
                result["transforms"]["created"].append(name)
        except Exception as exc:
            result["errors"].append(f"transform '{name}': {exc}")

    # ── Connectors ────────────────────────────────────────────────────────────
    for c in data.get("connectors", []):
        name = c.get("name", "")
        try:
            existing = conn.execute(
                "SELECT id FROM integrations.connector WHERE tenant_id = ? AND name = ?",
                [tenant_id, name],
            ).fetchone()
            if existing:
                result["connectors"]["skipped"].append(name)
            else:
                # Preserve non-secret config values (url, json_path, pagination);
                # strip redacted placeholders so they don't pollute the new config.
                imported_config = c.get("config", {})
                clean_config = {
                    k: v for k, v in imported_config.items() if v != "***"
                }
                # Resolve entity link by name (entities are imported first)
                entity_id: str | None = None
                entity_name = c.get("entity_name")
                if entity_name:
                    ent = conn.execute(
                        "SELECT id FROM catalogue.entity"
                        " WHERE tenant_id = ? AND name = ? AND layer = 'bronze'",
                        [tenant_id, entity_name],
                    ).fetchone()
                    if ent:
                        entity_id = str(ent[0])
                create_integration(
                    {
                        **c,
                        "collection": collection_name,
                        "config": clean_config,
                        "entity_id": entity_id,
                    },
                    tenant_id,
                )
                result["connectors"]["created"].append(name)
        except Exception as exc:
            result["errors"].append(f"connector '{name}': {exc}")

    return result
