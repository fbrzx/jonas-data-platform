"""Dashboards router — CRUD for Observable Framework .md files."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.dashboards import service

router = APIRouter()


def _tenant(request: Request) -> str:
    user = request.state.user or {}
    tid = user.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(tid)


class SaveBody(BaseModel):
    content: str


@router.get("")
def list_dashboards(request: Request) -> list[dict[str, Any]]:
    return service.list_dashboards(_tenant(request))


@router.get("/{slug}")
def get_dashboard(slug: str, request: Request) -> dict[str, Any]:
    result = service.get_dashboard(_tenant(request), slug)
    if not result:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return result


@router.put("/{slug}")
def save_dashboard(slug: str, body: SaveBody, request: Request) -> dict[str, Any]:
    try:
        return service.save_dashboard(_tenant(request), slug, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{slug}")
def delete_dashboard(slug: str, request: Request) -> dict[str, str]:
    deleted = service.delete_dashboard(_tenant(request), slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return {"status": "deleted"}


@router.get("/_config")
def get_config(request: Request) -> dict[str, Any]:
    content = service.get_config(_tenant(request))
    return {"content": content or ""}


@router.put("/_config")
def save_config(body: SaveBody, request: Request) -> dict[str, str]:
    service.save_config(_tenant(request), body.content)
    return {"status": "saved"}
