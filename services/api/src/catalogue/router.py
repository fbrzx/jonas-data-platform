"""Catalogue API routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from src.auth.permissions import Action, Resource, require_permission
from src.catalogue import service
from src.catalogue.models import EntityCreate, EntityUpdate

router = APIRouter()


def _user(request: Request) -> dict[str, Any]:
    return request.state.user or {}


def _tenant(request: Request) -> str:
    user = _user(request)
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


@router.get("/entities")
async def list_entities(request: Request) -> list[dict[str, Any]]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.READ)
    return service.list_entities(_tenant(request))


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: UUID, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.READ)
    entity = service.get_entity(str(entity_id), _tenant(request))
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity


@router.post("/entities", status_code=201)
async def create_entity(body: EntityCreate, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    return service.create_entity(body.model_dump(), _tenant(request))


@router.patch("/entities/{entity_id}")
async def update_entity(
    entity_id: UUID, body: EntityUpdate, request: Request
) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    result = service.update_entity(
        str(entity_id), body.model_dump(exclude_none=True), _tenant(request)
    )
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result


@router.get("/entities/{entity_id}/fields")
async def get_entity_fields(entity_id: UUID, request: Request) -> list[dict[str, Any]]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.READ)
    return service.get_entity_fields(str(entity_id))


@router.post("/entities/{entity_id}/fields", status_code=201)
async def create_entity_fields(
    entity_id: UUID, body: list[dict[str, Any]], request: Request
) -> list[dict[str, Any]]:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    return service.create_fields_bulk(str(entity_id), body, str(user.get("user_id", "system")))


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(entity_id: UUID, request: Request) -> None:
    user = _user(request)
    require_permission(user, Resource.CATALOGUE, Action.WRITE)
    if not service.delete_entity(str(entity_id), _tenant(request)):
        raise HTTPException(status_code=404, detail="Entity not found")
