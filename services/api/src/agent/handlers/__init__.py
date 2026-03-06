"""Tool dispatch — routes tool_name to the correct handler module."""

import json
from typing import Any

from . import catalogue, connectors, memory, query, transforms as transforms_handler

_MODULES = [catalogue, query, connectors, transforms_handler, memory]


def run_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tenant_id: str,
    role: str,
    created_by: str,
) -> str:
    """Dispatch a tool call to the appropriate handler. Returns a JSON string."""
    for module in _MODULES:
        result = module.handle(
            tool_name, tool_input, tenant_id=tenant_id, role=role, created_by=created_by
        )
        if result is not None:
            return result
    return json.dumps({"error": f"Unknown tool: {tool_name}"})
