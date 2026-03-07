"""Agent (chat) API routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
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


@router.post("/chat/stream")
@_limiter.limit("20/minute")
async def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    """Stream agent responses as Server-Sent Events.

    Each event is a JSON object with a ``type`` field:
    - ``tool``  — a tool is being invoked (includes ``name``)
    - ``delta`` — incremental text token (includes ``text``)
    - ``done``  — turn is complete
    """
    user = request.state.user or {}
    require_permission(user, Resource.AGENT, Action.WRITE)

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    messages = [m.model_dump() for m in body.messages]
    role = str(user.get("role", "viewer"))
    user_id = str(user.get("user_id", "unknown"))
    max_tokens = body.max_tokens

    def generate():
        import json

        try:
            yield from service.stream_chat(
                messages=messages,
                tenant_id=str(tenant_id),
                role=role,
                user_id=user_id,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            err_str = str(exc)
            # Extract a user-friendly message for known error categories
            if (
                "429" in err_str
                or "rate limit" in err_str.lower()
                or "usage limit" in err_str.lower()
            ):
                user_msg = (
                    "LLM rate limit reached — please wait or check your API quota."
                )
            elif (
                "401" in err_str
                or "authentication" in err_str.lower()
                or "api key" in err_str.lower()
            ):
                user_msg = "LLM authentication failed — check your API key in settings."
            elif "503" in err_str or "overloaded" in err_str.lower():
                user_msg = "LLM service unavailable — try again in a moment."
            else:
                user_msg = f"Agent error: {err_str[:200]}"
            logger.error("Agent stream error: %s", err_str)
            yield f"data: {json.dumps({'type': 'error', 'message': user_msg})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
