"""Integrations API routes — CRUD + ingest endpoints."""

from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from src.audit.log import write_audit
from src.auth.permissions import Action, Resource, require_permission
from src.integrations import ingest, service
from src.integrations.models import (
    BatchIngestResponse,
    IntegrationCreate,
    IntegrationUpdate,
    LinkedWebhookPayload,
    WebhookPayload,
)
from src.limiter import limiter  # noqa: F401

MAX_RUNS = 50

router = APIRouter()

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _user(request: Request) -> dict[str, Any]:
    return request.state.user or {}


def _tenant(request: Request) -> str:
    user = _user(request)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


def _resolve_source(integration_id: str, tenant_id: str, expected_type: str) -> str:
    """Look up an integration and return the bronze source name.

    Prefers the linked catalogue entity's name when target_entity_id is set,
    otherwise falls back to the integration's own name.
    Raises HTTPException on not-found or wrong connector_type.
    """
    integration = service.get_integration(integration_id, tenant_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.get("connector_type") != expected_type:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Integration connector_type is '{integration['connector_type']}', "
                f"not '{expected_type}'"
            ),
        )
    entity_id = integration.get("target_entity_id")
    if entity_id:
        from src.catalogue.service import get_entity

        entity = get_entity(str(entity_id), tenant_id)
        if not entity:
            raise HTTPException(
                status_code=404,
                detail=f"Linked catalogue entity '{entity_id}' not found",
            )
        return str(entity["name"])
    return str(integration["name"])


@router.get("")
async def list_integrations(request: Request) -> list[dict[str, Any]]:
    require_permission(_user(request), Resource.INTEGRATION, Action.READ)
    return service.list_integrations(_tenant(request))


@router.post("", status_code=201)
async def create_integration(
    body: IntegrationCreate, request: Request
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    result = service.create_integration(body.model_dump(), _tenant(request))
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action="create",
        resource_type="connector",
        resource_id=result.get("id"),
        detail={"name": result.get("name"), "type": result.get("connector_type")},
    )
    return result


@router.patch("/{integration_id}")
async def update_integration(
    integration_id: str, body: IntegrationUpdate, request: Request
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)
    result = service.update_integration(
        integration_id, body.model_dump(exclude_none=True), tenant_id
    )
    if not result:
        raise HTTPException(status_code=404, detail="Integration not found")
    # Sync cron schedule with the scheduler when explicitly provided
    if body.cron_schedule is not None or "cron_schedule" in body.model_fields_set:
        from src.scheduler import scheduler as job_scheduler

        job_scheduler.reload_connector(
            integration_id, result.get("cron_schedule"), tenant_id
        )
    write_audit(
        tenant_id=tenant_id,
        user_id=user.get("user_id"),
        action="update",
        resource_type="connector",
        resource_id=integration_id,
    )
    return result


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(integration_id: str, request: Request) -> None:
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    service.delete_integration(integration_id, _tenant(request))
    write_audit(
        tenant_id=_tenant(request),
        user_id=user.get("user_id"),
        action="delete",
        resource_type="connector",
        resource_id=integration_id,
    )


@router.get("/{integration_id}/runs")
async def list_runs(integration_id: str, request: Request) -> list[dict[str, Any]]:
    require_permission(_user(request), Resource.INTEGRATION, Action.READ)
    return service.list_runs(integration_id, _tenant(request), limit=MAX_RUNS)


@router.post("/{integration_id}/trigger", response_model=BatchIngestResponse)
async def trigger_api_pull(integration_id: str, request: Request) -> dict[str, Any]:
    """Manually trigger an api_pull integration to fetch its configured URL."""
    require_permission(_user(request), Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)

    integration = service.get_integration(integration_id, tenant_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.get("connector_type") != "api_pull":
        ct = integration.get("connector_type", "")
        raise HTTPException(
            status_code=422,
            detail=f"Integration connector_type is '{ct}', not 'api_pull'",
        )

    import json as _json

    raw_config = integration.get("config") or {}
    config: dict = (
        _json.loads(raw_config) if isinstance(raw_config, str) else raw_config
    )
    # Support legacy keys written by earlier agent versions (source_url / auth_header)
    url: str = (config.get("url") or config.get("source_url") or "").strip()
    if not url:
        raise HTTPException(status_code=422, detail="Integration config.url is not set")

    headers: dict[str, str] = config.get("headers") or {}
    if not headers and config.get("auth_header"):
        headers = {"Authorization": str(config["auth_header"])}
    entity_id = integration.get("target_entity_id")
    if entity_id:
        from src.catalogue.service import get_entity

        entity = get_entity(str(entity_id), tenant_id)
        source = str(entity["name"]) if entity else str(integration["name"])
    else:
        source = str(integration["name"])

    result = ingest.land_api_pull(url, headers, source, tenant_id, integration_id)
    write_audit(
        tenant_id=tenant_id,
        user_id=_user(request).get("user_id"),
        action="trigger",
        resource_type="connector",
        resource_id=integration_id,
        detail={"rows_landed": result.get("rows_landed")},
    )
    return result


@router.post("/ingest/webhook", response_model=BatchIngestResponse)
@limiter.limit("120/minute")
async def ingest_webhook(payload: WebhookPayload, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)
    result = ingest.land_webhook(
        payload.source, payload.data, payload.metadata, tenant_id
    )
    write_audit(
        tenant_id=tenant_id,
        user_id=user.get("user_id"),
        action="ingest_webhook",
        resource_type="connector",
        detail={"source": payload.source, "rows": result.get("rows_landed")},
    )
    return result


@router.post("/{integration_id}/webhook", response_model=BatchIngestResponse)
@limiter.limit("120/minute")
async def ingest_via_integration(
    integration_id: str, payload: LinkedWebhookPayload, request: Request
) -> dict[str, Any]:
    """Send data through a specific integration's webhook."""
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)
    source = _resolve_source(integration_id, tenant_id, "webhook")
    result = ingest.land_webhook(
        source, payload.data, payload.metadata, tenant_id, integration_id
    )
    write_audit(
        tenant_id=tenant_id,
        user_id=user.get("user_id"),
        action="ingest_webhook",
        resource_type="connector",
        resource_id=integration_id,
        detail={"source": source, "rows": result.get("rows_landed")},
    )
    return result


@router.post("/ingest/batch", response_model=BatchIngestResponse)
@limiter.limit("20/minute")
async def ingest_batch(
    request: Request,
    source: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    filename = file.filename or ""
    if filename.endswith(".csv"):
        result = ingest.land_batch_csv(source, content, tenant_id)
    else:
        result = ingest.land_batch_json(source, content, tenant_id)
    write_audit(
        tenant_id=tenant_id,
        user_id=user.get("user_id"),
        action="ingest_batch",
        resource_type="connector",
        detail={"source": source, "rows": result.get("rows_landed"), "file": filename},
    )
    return result


@router.post("/{integration_id}/batch", response_model=BatchIngestResponse)
@limiter.limit("20/minute")
async def ingest_batch_via_integration(
    integration_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a CSV or JSON file through a specific batch integration."""
    user = _user(request)
    require_permission(user, Resource.INTEGRATION, Action.WRITE)
    tenant_id = _tenant(request)
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    filename = file.filename or ""
    connector_type = "batch_csv" if filename.endswith(".csv") else "batch_json"
    source = _resolve_source(integration_id, tenant_id, connector_type)
    if connector_type == "batch_csv":
        result = ingest.land_batch_csv(source, content, tenant_id, integration_id)
    else:
        result = ingest.land_batch_json(source, content, tenant_id, integration_id)
    write_audit(
        tenant_id=tenant_id,
        user_id=user.get("user_id"),
        action="ingest_batch",
        resource_type="connector",
        resource_id=integration_id,
        detail={"source": source, "rows": result.get("rows_landed"), "file": filename},
    )
    return result
