"""Agent (chat) API routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter  # type: ignore[attr-defined]
from slowapi.util import get_remote_address

from src.agent import service
from src.auth.permissions import Action, Resource, require_permission

logger = logging.getLogger(__name__)

router = APIRouter()
_limiter = Limiter(key_func=get_remote_address)


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
@_limiter.limit("20/minute")
async def chat(request: Request, body: ChatRequest) -> dict[str, Any]:
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
        logger.exception("Agent chat error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
