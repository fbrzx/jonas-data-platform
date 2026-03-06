"""Memory tool handlers: save_memory, recall_memories, forget_memory."""

import json
from typing import Any

_TOOLS = {"save_memory", "recall_memories", "forget_memory"}


def handle(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tenant_id: str,
    role: str,
    created_by: str,
) -> str | None:
    if tool_name not in _TOOLS:
        return None

    if tool_name == "save_memory":
        from src.agent.memory import save_memory

        category = tool_input.get("category", "context")
        summary = tool_input.get("summary")
        content = tool_input.get("content")
        if not summary:
            return json.dumps({"error": "save_memory requires 'summary'."})
        if content is None:
            return json.dumps({"error": "save_memory requires 'content'."})
        result = save_memory(tenant_id, category, summary, content, created_by)
        return json.dumps(
            {"saved": True, "memory_id": result.get("id"), "summary": summary}
        )

    if tool_name == "recall_memories":
        from src.agent.memory import recall_memories

        query = tool_input.get("query", "")
        limit = min(int(tool_input.get("limit", 5)), 20)
        memories = recall_memories(tenant_id, query, limit=limit)
        return json.dumps(
            [
                {
                    "id": m["id"],
                    "category": m.get("category"),
                    "summary": m.get("summary"),
                    "content": m.get("content"),
                    "relevance_score": m.get("relevance_score"),
                    "use_count": m.get("use_count"),
                }
                for m in memories
            ]
        )

    if tool_name == "forget_memory":
        from src.agent.memory import forget_memory

        memory_id = tool_input.get("memory_id")
        if not memory_id:
            return json.dumps({"error": "forget_memory requires 'memory_id'."})
        deleted = forget_memory(memory_id, tenant_id)
        if not deleted:
            return json.dumps({"error": f"Memory '{memory_id}' not found."})
        return json.dumps({"deleted": True, "memory_id": memory_id})

    return None
