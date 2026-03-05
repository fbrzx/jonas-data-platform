"""LLM provider integration — agentic chat with tool use.

Phase 2 additions:
- Dynamic system prompt with live catalogue context (NL-to-SQL awareness)
- infer_schema and register_entity tool handlers
- PII masking applied to run_sql and preview_entity results
- Tenant-scoped SQL safety check
"""

from __future__ import annotations

import json
import re
from collections.abc import Generator
from typing import Any

from src.agent.inference import infer_from_csv, infer_from_json
from src.agent.pii import mask_rows
from src.agent.provider import build_provider_client
from src.agent.tools import TOOLS
from src.config import settings
from src.db.connection import get_conn

# Layers each role is allowed to query
_ROLE_ALLOWED_LAYERS: dict[str, set[str]] = {
    "owner": {"bronze", "silver", "gold"},
    "admin": {"bronze", "silver", "gold"},
    "engineer": {"bronze", "silver", "gold"},
    "analyst": {"silver", "gold"},
    "viewer": {"gold"},
}

_LAYER_PATTERN = re.compile(r"\b(bronze|silver|gold)\.\w+", re.IGNORECASE)

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


def _check_sql_scope(sql: str, role: str) -> str | None:
    """Return an error message if SQL references a layer the role cannot access."""
    allowed = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
    for match in _LAYER_PATTERN.finditer(sql):
        layer = match.group(1).lower()
        if layer not in allowed:
            return (
                f"Access denied: your role ({role}) cannot query the {layer} layer. "
                f"You have access to: {', '.join(sorted(allowed))}."
            )
    return None


_BASE_SYSTEM_PROMPT = """\
You are Jonas, an AI assistant embedded in a multi-tenant data platform.
You help data engineers and analysts ingest, clean, and query their data.

## Your capabilities
- Inspect data payloads and infer schemas (infer_schema)
- Register new entities in the catalogue (register_entity)
- Browse the catalogue to understand available data (list_entities, describe_entity)
- Answer data questions with SQL (run_sql, preview_entity)
- Draft SQL transforms for the bronze→silver→gold pipeline (draft_transform)
- List and create data integrations (list_integrations, create_integration)
- Ingest data directly into the bronze layer via webhook (ingest_webhook)

## Rules
- Only generate DuckDB-compatible SQL. Reference tables as `layer.entity_name`
  (e.g. `bronze.orders`).
- Never approve your own transform drafts — always tell the user it needs admin approval.
- When writing transforms, produce CREATE TABLE AS SELECT statements targeting
  the correct layer schema.
- PII fields are automatically masked in query results — you don't need to handle this yourself.
- Always confirm with the user before registering an entity, drafting a transform,
  or creating an integration.
- Be concise. Lead with the answer or action, then explain if needed.

{catalogue_context}
"""


def _build_system_prompt(tenant_id: str, role: str) -> str:
    from src.catalogue.service import build_catalogue_context

    try:
        ctx = build_catalogue_context(tenant_id, role)
    except Exception:
        ctx = "(catalogue unavailable)"
    return _BASE_SYSTEM_PROMPT.format(catalogue_context=ctx)


def _pii_fields_for_entity(entity_id: str) -> set[str]:
    """Return the set of PII field names for an entity."""
    from src.catalogue.service import get_entity_fields

    fields = get_entity_fields(entity_id)
    return {f["name"] for f in fields if f.get("is_pii")}


def _has_pii_access(role: str) -> bool:
    """Admins and owners can see unmasked PII. Everyone else gets masked output."""
    return role in ("owner", "admin")


def _run_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tenant_id: str,
    role: str,
    created_by: str,
) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    conn = get_conn()

    # ── list_entities ────────────────────────────────────────────────────────
    if tool_name == "list_entities":
        from src.catalogue.service import get_accessible_entities

        entities = get_accessible_entities(tenant_id, role)
        layer = tool_input.get("layer")
        if layer:
            entities = [e for e in entities if e.get("layer") == layer]
        # Trim fields list to just names to keep response compact
        summary = [
            {
                "id": e["id"],
                "name": e["name"],
                "layer": e.get("layer"),
                "description": e.get("description", ""),
                "field_count": len(e.get("fields", [])),
            }
            for e in entities
        ]
        return json.dumps(summary)

    # ── describe_entity ──────────────────────────────────────────────────────
    if tool_name == "describe_entity":
        from src.catalogue.service import get_entity, get_entity_fields

        entity = get_entity(tool_input["entity_id"], tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})
        entity["fields"] = get_entity_fields(entity["id"])
        return json.dumps(entity, default=str)

    # ── infer_schema ─────────────────────────────────────────────────────────
    if tool_name == "infer_schema":
        sample = tool_input.get("sample")
        fmt = tool_input.get("format", "json")
        try:
            if fmt == "csv" and isinstance(sample, list):
                headers = list(sample[0].keys()) if sample else []
                fields = infer_from_csv(headers, sample)
            else:
                fields = infer_from_json(sample)  # type: ignore[arg-type]
            return json.dumps(
                {
                    "field_count": len(fields),
                    "fields": fields,
                    "pii_fields": [f["name"] for f in fields if f.get("is_pii")],
                }
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── register_entity ──────────────────────────────────────────────────────
    if tool_name == "register_entity":
        from src.catalogue.service import create_entity, create_fields_bulk

        entity_data = {
            "name": tool_input["name"],
            "layer": tool_input["layer"],
            "description": tool_input.get("description", ""),
            "tags": [tool_input["namespace"]] if tool_input.get("namespace") else [],
        }
        entity = create_entity(entity_data, tenant_id)
        fields = create_fields_bulk(
            entity["id"], tool_input.get("fields", []), created_by
        )
        entity["fields"] = fields
        return json.dumps(entity, default=str)

    # ── run_sql ──────────────────────────────────────────────────────────────
    if tool_name == "run_sql":
        sql = tool_input.get("sql", "").strip()
        limit = min(int(tool_input.get("limit", 100)), 1000)

        if not sql.upper().startswith("SELECT"):
            return json.dumps({"error": "Only SELECT statements are permitted."})

        scope_error = _check_sql_scope(sql, role)
        if scope_error:
            return json.dumps({"error": scope_error})

        try:
            rows_raw = conn.execute(f"{sql} LIMIT {limit}").fetchall()
            cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
            rows = [dict(zip(cols, row)) for row in rows_raw]

            # Mask PII if user lacks access
            if not _has_pii_access(role):
                # Detect PII columns by name heuristic (conservative)
                from src.agent.inference import _is_pii  # type: ignore[attr-defined]
                from src.agent.pii import mask_rows as _mask

                pii_cols = {c for c in cols if _is_pii(c)}
                rows = _mask(rows, pii_cols, False)

            return json.dumps({"rows": rows, "count": len(rows)}, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── preview_entity ───────────────────────────────────────────────────────
    if tool_name == "preview_entity":
        from src.catalogue.service import get_entity, get_entity_fields

        entity_id = tool_input["entity_id"]
        limit = min(int(tool_input.get("limit", 10)), 100)
        entity = get_entity(entity_id, tenant_id)
        if not entity:
            return json.dumps({"error": "Entity not found"})

        allowed_layers = _ROLE_ALLOWED_LAYERS.get(role, {"gold"})
        if entity.get("layer") not in allowed_layers:
            return json.dumps(
                {
                    "error": (
                        f"Access denied: your role ({role}) cannot access the "
                        f"{entity['layer']} layer."
                    )
                }
            )

        table_ref = f"{entity['layer']}.{entity['name']}"
        try:
            rows_raw = conn.execute(
                f"SELECT * FROM {table_ref} LIMIT {limit}"  # noqa: S608
            ).fetchall()
            cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
            rows = [dict(zip(cols, row)) for row in rows_raw]

            pii_field_names = _pii_fields_for_entity(entity_id)
            rows = mask_rows(rows, pii_field_names, _has_pii_access(role))

            return json.dumps(
                {"entity": table_ref, "rows": rows, "count": len(rows)}, default=str
            )
        except Exception as exc:
            return json.dumps({"error": str(exc), "entity": table_ref})

    # ── ingest_webhook ───────────────────────────────────────────────────────
    if tool_name == "ingest_webhook":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.ingest import land_webhook
        from src.integrations.service import get_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot ingest data."}
            )

        # Resolve source: prefer integration_id → entity.name (if linked) → integration.name
        integration_id = tool_input.get("integration_id")
        if integration_id:
            integration = get_integration(integration_id, tenant_id)
            if not integration:
                return json.dumps({"error": f"Integration '{integration_id}' not found."})
            if integration.get("connector_type") != "webhook":
                return json.dumps(
                    {
                        "error": (
                            f"Integration '{integration['name']}' has connector_type "
                            f"'{integration['connector_type']}', not 'webhook'."
                        )
                    }
                )
            entity_id = integration.get("target_entity_id")
            if entity_id:
                from src.catalogue.service import get_entity

                entity = get_entity(str(entity_id), tenant_id)
                if not entity:
                    return json.dumps(
                        {"error": f"Linked catalogue entity '{entity_id}' not found."}
                    )
                source = str(entity["name"])
            else:
                source = str(integration["name"])
        else:
            source = tool_input.get("source", "")

        if not source:
            return json.dumps(
                {"error": "Provide either integration_id or source to identify the target table."}
            )

        data = tool_input.get("data", {})
        metadata = tool_input.get("metadata", {})
        result = land_webhook(source, data, metadata, tenant_id)
        return json.dumps(result)

    # ── list_integrations ────────────────────────────────────────────────────
    if tool_name == "list_integrations":
        from src.integrations.service import list_integrations

        integrations = list_integrations(tenant_id)
        summary = [
            {
                "id": i["id"],
                "name": i["name"],
                "connector_type": i.get("connector_type"),
                "status": i.get("status"),
                "description": i.get("description", ""),
            }
            for i in integrations
        ]
        return json.dumps(summary)

    # ── create_integration ───────────────────────────────────────────────────
    if tool_name == "create_integration":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.service import create_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot create integrations."}
            )
        result = create_integration(tool_input, tenant_id)
        return json.dumps(result, default=str)

    # ── draft_transform ──────────────────────────────────────────────────────
    if tool_name == "draft_transform":
        from src.transforms.service import create_transform

        result = create_transform(tool_input, tenant_id, created_by=created_by)
        return json.dumps(result, default=str)

    return json.dumps({"error": f"Unknown tool: {tool_name}"})


def chat(
    messages: list[dict[str, Any]],
    tenant_id: str,
    role: str = "viewer",
    user_id: str = "unknown",
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Run an agentic conversation turn with tool use.

    Builds a live system prompt from the catalogue, then loops until
    the model stops calling tools.
    """
    provider_client = build_provider_client()
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation: list[dict[str, Any]] = [
        {
            "role": str(msg.get("role", "user")),
            "content": str(msg.get("content", "")),
        }
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

        assistant_turn: dict[str, Any] = {
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
        conversation.append(assistant_turn)

        for call in tool_calls:
            try:
                tool_input = json.loads(call.function.arguments or "{}")
                if not isinstance(tool_input, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except Exception as exc:
                result = json.dumps({"error": f"Invalid tool arguments: {exc}"})
            else:
                result = _run_tool(
                    call.function.name,
                    tool_input,
                    tenant_id,
                    role,
                    user_id,
                )

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
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
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation: list[dict[str, Any]] = [
        {
            "role": str(msg.get("role", "user")),
            "content": str(msg.get("content", "")),
        }
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
                    index,
                    {"id": "", "name": "", "arguments_parts": []},
                )

                if tool_delta.id:
                    partial["id"] = tool_delta.id

                if tool_delta.function:
                    if tool_delta.function.name:
                        partial["name"] = tool_delta.function.name
                    if tool_delta.function.arguments:
                        partial["arguments_parts"].append(
                            tool_delta.function.arguments
                        )

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
                    "function": {
                        "name": call_name,
                        "arguments": call_args,
                    },
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

            try:
                tool_input = json.loads(str(call["function"]["arguments"]) or "{}")
                if not isinstance(tool_input, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
            except Exception as exc:
                result = json.dumps({"error": f"Invalid tool arguments: {exc}"})
            else:
                result = _run_tool(
                    tool_name,
                    tool_input,
                    tenant_id,
                    role,
                    user_id,
                )

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": str(call["id"]),
                    "content": result,
                }
            )
