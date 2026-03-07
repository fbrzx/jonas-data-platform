"""Transforms API routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from src.audit.log import write_audit
from src.auth.permissions import Action, Resource, require_permission
from src.transforms import service
from src.transforms.models import ApprovalAction, TransformCreate, TransformUpdate

router = APIRouter()


def _user(request: Request) -> dict[str, Any]:
    return request.state.user or {}


def _tenant(request: Request) -> str:
    user = _user(request)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


@router.get("")
async def list_transforms(request: Request) -> list[dict[str, Any]]:
    require_permission(_user(request), Resource.TRANSFORM, Action.READ)
    return service.list_transforms(_tenant(request))


@router.get("/{transform_id}")
async def get_transform(transform_id: UUID, request: Request) -> dict[str, Any]:
    require_permission(_user(request), Resource.TRANSFORM, Action.READ)
    t = service.get_transform(str(transform_id), _tenant(request))
    if not t:
        raise HTTPException(status_code=404, detail="Transform not found")
    return t


@router.post("", status_code=201)
async def create_transform(body: TransformCreate, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.WRITE)
    created_by = user.get("user_id", "unknown")
    result = service.create_transform(body.model_dump(), _tenant(request), created_by)
    write_audit(
        tenant_id=_tenant(request),
        user_id=created_by,
        action="create",
        resource_type="transform",
        resource_id=result.get("id"),
        detail={"name": result.get("name")},
    )
    return result


@router.patch("/{transform_id}")
async def update_transform(
    transform_id: UUID, body: TransformUpdate, request: Request
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.WRITE)
    try:
        result = service.update_transform(
            str(transform_id), body.model_dump(exclude_none=True), _tenant(request)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Transform not found")
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action="update",
        resource_type="transform",
        resource_id=str(transform_id),
        detail={"fields": list(body.model_dump(exclude_none=True).keys())},
    )
    return result


@router.delete("/{transform_id}", status_code=204)
async def delete_transform(transform_id: UUID, request: Request) -> None:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.WRITE)
    service.delete_transform(str(transform_id), _tenant(request))
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action="delete",
        resource_type="transform",
        resource_id=str(transform_id),
    )


@router.post("/{transform_id}/approval")
async def approve_transform(
    transform_id: UUID, body: ApprovalAction, request: Request
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.APPROVE)
    reviewer = body.reviewer_id or user.get("user_id", "unknown")
    result = service.approve_transform(
        str(transform_id), body.action, str(reviewer), _tenant(request)
    )
    if not result:
        raise HTTPException(status_code=404, detail="Transform not found")
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action=body.action,
        resource_type="transform",
        resource_id=str(transform_id),
        detail={"name": result.get("name")},
    )
    return result


@router.post("/{transform_id}/execute")
async def execute_transform(transform_id: UUID, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.APPROVE)
    try:
        result = service.execute_transform(str(transform_id), _tenant(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action="execute",
        resource_type="transform",
        resource_id=str(transform_id),
        detail={
            "rows": result.get("rows_affected"),
            "errors": result.get("errors", []),
        },
    )
    return result


@router.get("/lineage/graph")
async def lineage_graph(request: Request) -> dict[str, Any]:
    """Return entities (nodes) and transforms (edges) for lineage visualisation."""
    import re

    from src.catalogue.service import list_entities

    require_permission(_user(request), Resource.TRANSFORM, Action.READ)
    tenant_id = _tenant(request)
    entities = list_entities(tenant_id)
    transforms = service.list_transforms(tenant_id)

    nodes = [
        {
            "id": e["id"],
            "name": e["name"],
            "layer": e.get("layer", "bronze"),
            "description": e.get("description", ""),
            "tags": e.get("tags", "[]"),
        }
        for e in entities
    ]

    # Build lookup: (layer, name) → entity id for resolving transform edges
    entity_by_layer_name: dict[tuple[str, str], str] = {
        (e.get("layer", "bronze"), e["name"]): e["id"] for e in entities
    }

    def _resolve_target(transform: dict[str, Any]) -> str | None:
        eid = transform.get("target_entity_id")
        if eid:
            return str(eid)
        layer = transform.get("target_layer", "silver")
        sql = str(transform.get("transform_sql", ""))
        m = re.search(
            r"(?i)\b(?:CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)"
            r"(?:\w+\.)?(\w+)",
            sql,
        )
        if m:
            tbl = m.group(1)
            for try_layer in [layer] + [
                l for l in ("bronze", "silver", "gold") if l != layer
            ]:
                key = (try_layer, tbl)
                if key in entity_by_layer_name:
                    return entity_by_layer_name[key]
        layer_entities = [e for e in entities if e.get("layer") == layer]
        if len(layer_entities) == 1:
            return str(layer_entities[0]["id"])
        return None

    def _resolve_sources(transform: dict[str, Any]) -> list[str]:
        eid = transform.get("source_entity_id")
        if eid:
            return [str(eid)]
        source_layer = transform.get("source_layer", "bronze")
        target_layer = transform.get("target_layer", "silver")
        sql = str(transform.get("transform_sql", ""))
        # Collect table names from SQL
        tables: list[str] = []
        for m in re.finditer(r"(?i)\bFROM\s+(?:\w+\.)?(\w+)", sql):
            if m.group(1) not in tables:
                tables.append(m.group(1))
        for m in re.finditer(r"(?i)\bJOIN\s+(?:\w+\.)?(\w+)", sql):
            if m.group(1) not in tables:
                tables.append(m.group(1))
        # For medallion pattern: prefer layer just below the target (e.g. silver for gold transforms)
        layer_order = ("bronze", "silver", "gold")
        src_idx = layer_order.index(source_layer) if source_layer in layer_order else 0
        tgt_idx = (
            layer_order.index(target_layer)
            if target_layer in layer_order
            else len(layer_order)
        )
        intermediates = list(reversed(layer_order[src_idx:tgt_idx]))
        seen: set[str] = set()
        all_layers: list[str] = []
        for l in [
            *intermediates,
            source_layer,
            *[x for x in layer_order if x != target_layer],
        ]:
            if l not in seen:
                all_layers.append(l)
                seen.add(l)
        ids: list[str] = []
        for tbl in tables:
            for layer in all_layers:
                key = (layer, tbl)
                if key in entity_by_layer_name and entity_by_layer_name[key] not in ids:
                    ids.append(entity_by_layer_name[key])
                    break
        if not ids:
            layer_entities = [e for e in entities if e.get("layer") == source_layer]
            if len(layer_entities) == 1:
                ids.append(str(layer_entities[0]["id"]))
        return ids

    # Build edges — one per (source_entity, target_entity) pair
    edges: list[dict[str, Any]] = []
    for t in transforms:
        target_id = _resolve_target(t)
        source_ids = _resolve_sources(t)
        base = {
            "name": t["name"],
            "source_layer": t.get("source_layer", "bronze"),
            "target_layer": t.get("target_layer", "silver"),
            "status": t.get("status", "draft"),
            "sql": t.get("transform_sql", ""),
        }
        if source_ids and target_id:
            for src_id in source_ids:
                edges.append(
                    {
                        **base,
                        "id": f"{t['id']}_{src_id}",
                        "source_entity_id": src_id,
                        "target_entity_id": target_id,
                    }
                )
        else:
            edges.append(
                {
                    **base,
                    "id": t["id"],
                    "source_entity_id": source_ids[0] if source_ids else None,
                    "target_entity_id": target_id,
                }
            )
    return {"nodes": nodes, "edges": edges}
