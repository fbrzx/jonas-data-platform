"""LLM provider integration — agentic chat with tool use."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any

from src.agent.handlers import run_tool
from src.agent.prompt import build_system_prompt, cap_tool_result
from src.agent.provider import build_provider_client
from src.agent.tools import TOOLS
from src.config import settings

_OPENAI_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOLS
]


def _dispatch(
    tool_name: str,
    arguments: str,
    tenant_id: str,
    role: str,
    user_id: str,
) -> str:
    try:
        tool_input = json.loads(arguments or "{}")
        if not isinstance(tool_input, dict):
            raise ValueError("Tool arguments must be a JSON object.")
    except Exception as exc:
        return json.dumps({"error": f"Invalid tool arguments: {exc}"})
    return cap_tool_result(
        run_tool(
            tool_name, tool_input, tenant_id=tenant_id, role=role, created_by=user_id
        )
    )


def chat(
    messages: list[dict[str, Any]],
    tenant_id: str,
    role: str = "viewer",
    user_id: str = "unknown",
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Run an agentic conversation turn with tool use."""
    provider_client = build_provider_client()
    last_user_msg = next(
        (
            str(m.get("content", ""))
            for m in reversed(messages)
            if m.get("role") == "user"
        ),
        "",
    )
    system_prompt = build_system_prompt(tenant_id, role, last_user_msg)
    conversation: list[dict[str, Any]] = [
        {"role": str(msg.get("role", "user")), "content": str(msg.get("content", ""))}
        for msg in messages
    ]

    while True:
        response = provider_client.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt}, *conversation],
            tools=_OPENAI_TOOLS,
            tool_choice="auto",
            **provider_client.request_overrides,
        )

        if not response.choices:
            return {"role": "assistant", "content": "No response from the model."}

        assistant_message = response.choices[0].message
        tool_calls = assistant_message.tool_calls or []

        if not tool_calls:
            return {"role": "assistant", "content": assistant_message.content or ""}

        conversation.append(
            {
                "role": "assistant",
                "content": assistant_message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            }
        )

        for call in tool_calls:
            result = _dispatch(
                call.function.name, call.function.arguments, tenant_id, role, user_id
            )
            conversation.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )


def stream_chat(
    messages: list[dict[str, Any]],
    tenant_id: str,
    role: str = "viewer",
    user_id: str = "unknown",
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """Stream an agentic conversation turn as SSE-formatted events.

    Emits three event types:
    - ``{"type": "tool", "name": "<tool_name>"}`` — tool being invoked
    - ``{"type": "delta", "text": "<token>"}`` — text token from model
    - ``{"type": "done"}`` — conversation turn complete
    """
    provider_client = build_provider_client()
    last_user_msg = next(
        (
            str(m.get("content", ""))
            for m in reversed(messages)
            if m.get("role") == "user"
        ),
        "",
    )
    system_prompt = build_system_prompt(tenant_id, role, last_user_msg)
    conversation: list[dict[str, Any]] = [
        {"role": str(msg.get("role", "user")), "content": str(msg.get("content", ""))}
        for msg in messages
    ]

    while True:
        stream = provider_client.client.chat.completions.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system_prompt}, *conversation],
            tools=_OPENAI_TOOLS,
            tool_choice="auto",
            stream=True,
            **provider_client.request_overrides,
        )

        assistant_text_parts: list[str] = []
        partial_tool_calls: dict[int, dict[str, Any]] = {}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                assistant_text_parts.append(delta.content)
                yield f"data: {json.dumps({'type': 'delta', 'text': delta.content})}\n\n"

            if not delta.tool_calls:
                continue

            for tool_delta in delta.tool_calls:
                index = tool_delta.index if tool_delta.index is not None else 0
                partial = partial_tool_calls.setdefault(
                    index, {"id": "", "name": "", "arguments_parts": []}
                )
                if tool_delta.id:
                    partial["id"] = tool_delta.id
                if tool_delta.function:
                    if tool_delta.function.name:
                        partial["name"] = tool_delta.function.name
                    if tool_delta.function.arguments:
                        partial["arguments_parts"].append(tool_delta.function.arguments)

        if not partial_tool_calls:
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        ordered = [partial_tool_calls[i] for i in sorted(partial_tool_calls)]
        assistant_tool_calls: list[dict[str, Any]] = []
        for idx, partial in enumerate(ordered):
            call_id = partial["id"] or f"tool_call_{idx}"
            call_name = partial["name"] or ""
            call_args = "".join(partial["arguments_parts"]) or "{}"
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": call_name, "arguments": call_args},
                }
            )

        conversation.append(
            {
                "role": "assistant",
                "content": "".join(assistant_text_parts),
                "tool_calls": assistant_tool_calls,
            }
        )

        for call in assistant_tool_calls:
            tool_name = str(call["function"]["name"])
            yield f"data: {json.dumps({'type': 'tool', 'name': tool_name})}\n\n"
            result = _dispatch(
                tool_name, str(call["function"]["arguments"]), tenant_id, role, user_id
            )
            conversation.append(
                {"role": "tool", "tool_call_id": str(call["id"]), "content": result}
            )
