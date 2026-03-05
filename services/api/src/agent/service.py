"""Claude API integration — agentic chat with tool use.

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

import anthropic

from src.agent.inference import infer_from_csv, infer_from_json
from src.agent.pii import mask_rows
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

## Rules
- Only generate DuckDB-compatible SQL. Reference tables as `layer.entity_name`
  (e.g. `bronze.orders`).
- Never approve your own transform drafts — always tell the user it needs admin approval.
- When writing transforms, produce CREATE TABLE AS SELECT statements targeting
  the correct layer schema.
- PII fields are automatically masked in query results — you don't need to handle this yourself.
- Always confirm with the user before registering an entity or drafting a transform.
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
    client = anthropic.Anthropic(api_key=settings.claude_api_key or None)
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation = list(messages)

    while True:
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=TOOLS,  # type: ignore[arg-type]
            messages=conversation,
        )

        if response.stop_reason != "tool_use":
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            return {"role": "assistant", "content": text}

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _run_tool(
                    block.name,
                    block.input,  # type: ignore[arg-type]
                    tenant_id,
                    role,
                    user_id,
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        conversation.append({"role": "assistant", "content": response.content})  # type: ignore[arg-type]
        conversation.append({"role": "user", "content": tool_results})


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
    client = anthropic.Anthropic(api_key=settings.claude_api_key or None)
    system_prompt = _build_system_prompt(tenant_id, role)
    conversation = list(messages)

    while True:
        with client.messages.stream(
            model=settings.claude_model,
            max_tokens=max_tokens,
            system=system_prompt,
            tools=TOOLS,  # type: ignore[arg-type]
            messages=conversation,
        ) as stream:
            for event in stream:
                etype = getattr(event, "type", None)
                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block and getattr(block, "type", None) == "tool_use":
                        yield f"data: {json.dumps({'type': 'tool', 'name': block.name})}\n\n"
                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta and getattr(delta, "type", None) == "text_delta":
                        yield f"data: {json.dumps({'type': 'delta', 'text': delta.text})}\n\n"

            message = stream.get_final_message()

        if message.stop_reason != "tool_use":
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Process tool calls and loop for next model turn
        tool_results = []
        for block in message.content:
            if block.type == "tool_use":
                result = _run_tool(
                    block.name,
                    block.input,  # type: ignore[arg-type]
                    tenant_id,
                    role,
                    user_id,
                )
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        conversation.append({"role": "assistant", "content": message.content})  # type: ignore[arg-type]
        conversation.append({"role": "user", "content": tool_results})
