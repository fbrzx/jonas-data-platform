"""Integrations API routes — CRUD + ingest endpoints."""

from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from src.auth.permissions import Action, Resource, require_permission
from src.integrations import ingest, service
from src.integrations.models import (
    BatchIngestResponse,
    IntegrationCreate,
    WebhookPayload,
)

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
async def list_integrations(request: Request) -> list[dict[str, Any]]:
    require_permission(_user(request), Resource.INTEGRATION, Action.READ)
    return service.list_integrations(_tenant(request))


@router.post("", status_code=201)
async def create_integration(
    body: IntegrationCreate, request: Request
) -> dict[str, Any]:
    require_permission(_user(request), Resource.INTEGRATION, Action.WRITE)
    return service.create_integration(body.model_dump(), _tenant(request))


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(integration_id: str, request: Request) -> None:
    require_permission(_user(request), Resource.INTEGRATION, Action.WRITE)
    service.delete_integration(integration_id, _tenant(request))


@router.post("/ingest/webhook")
async def ingest_webhook(payload: WebhookPayload, request: Request) -> dict[str, Any]:
    require_permission(_user(request), Resource.INTEGRATION, Action.WRITE)
    return ingest.land_webhook(
        payload.source, payload.data, payload.metadata, _tenant(request)
    )


@router.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch(
    request: Request,
    source: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    require_permission(_user(request), Resource.INTEGRATION, Action.WRITE)
    content = await file.read()
    filename = file.filename or ""

    if filename.endswith(".csv"):
        result = ingest.land_batch_csv(source, content, _tenant(request))
    else:
        result = ingest.land_batch_json(source, content, _tenant(request))

    return result
