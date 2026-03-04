"""Transforms API routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from src.auth.permissions import Action, Resource, require_permission
from src.transforms import service
from src.transforms.models import ApprovalAction, TransformCreate

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
    return service.create_transform(body.model_dump(), _tenant(request), created_by)


@router.delete("/{transform_id}", status_code=204)
async def delete_transform(transform_id: UUID, request: Request) -> None:
    require_permission(_user(request), Resource.TRANSFORM, Action.WRITE)
    service.delete_transform(str(transform_id), _tenant(request))


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
    return result


@router.post("/{transform_id}/execute")
async def execute_transform(transform_id: UUID, request: Request) -> dict[str, Any]:
    user = _user(request)
    require_permission(user, Resource.TRANSFORM, Action.APPROVE)
    try:
        return service.execute_transform(str(transform_id), _tenant(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
