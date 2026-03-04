"""Agent (chat) API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.agent import service
from src.auth.permissions import Action, Resource, require_permission

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = 4096


class ChatResponse(BaseModel):
    role: str
    content: str


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> dict[str, Any]:
    user = request.state.user or {}
    require_permission(user, Resource.AGENT, Action.WRITE)

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        result = service.chat(
            messages=[m.model_dump() for m in body.messages],
            tenant_id=str(tenant_id),
            role=str(user.get("role", "viewer")),
            user_id=str(user.get("user_id", "unknown")),
            max_tokens=body.max_tokens,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
