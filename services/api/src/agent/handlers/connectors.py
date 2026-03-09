"""Connector tool handlers: list_connectors, get_connector_runs, discover_api, ingest_webhook, create_connector."""  # noqa: E501

import json
from typing import Any

_TOOLS = {
    "list_connectors",
    "get_connector_runs",
    "discover_api",
    "ingest_webhook",
    "create_connector",
    "trigger_connector",
}


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

    # ── list_connectors ──────────────────────────────────────────────────────
    if tool_name == "list_connectors":
        from src.integrations.service import list_integrations

        connectors = list_integrations(tenant_id)
        return json.dumps(
            [
                {
                    "id": i["id"],
                    "name": i["name"],
                    "connector_type": i.get("connector_type"),
                    "status": i.get("status"),
                    "description": i.get("description", ""),
                    "entity_id": i.get("target_entity_id"),
                    "webhook_endpoint": f"/api/v1/connectors/{i['id']}/webhook"
                    if i.get("connector_type") == "webhook"
                    else None,
                    "batch_endpoint": f"/api/v1/connectors/{i['id']}/batch"
                    if i.get("connector_type") in ("batch_csv", "batch_json")
                    else None,
                    "trigger_endpoint": f"/api/v1/connectors/{i['id']}/trigger"
                    if i.get("connector_type") == "api_pull"
                    else None,
                }
                for i in connectors
            ]
        )

    # ── get_connector_runs ───────────────────────────────────────────────────
    if tool_name == "get_connector_runs":
        from src.integrations.service import list_runs

        connector_id = tool_input.get("connector_id", "")
        if not connector_id:
            return json.dumps({"error": "connector_id is required."})
        runs = list_runs(connector_id, tenant_id, limit=20)
        return json.dumps(runs, default=str)

    # ── discover_api ─────────────────────────────────────────────────────────
    if tool_name == "discover_api":
        import httpx

        from src.security.ssrf import check_url

        url = tool_input.get("url", "").strip()
        if not url:
            return json.dumps({"error": "url is required"})

        ssrf_err = check_url(url)
        if ssrf_err:
            return json.dumps({"error": ssrf_err})

        method = tool_input.get("method", "GET").upper()
        headers: dict[str, str] = tool_input.get("headers") or {}
        body = tool_input.get("body")
        json_path: str = tool_input.get("json_path") or ""

        try:
            # follow_redirects=False prevents SSRF bypass via open redirects
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                if method == "GET":
                    response = client.get(url, headers=headers)
                elif method == "POST":
                    response = client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    response = client.put(url, headers=headers, json=body)
                else:
                    return json.dumps({"error": f"Unsupported method: {method}"})
                response.raise_for_status()
                data = response.json()

            records: object = data
            if json_path:
                for part in json_path.lstrip("$.").split("."):
                    if isinstance(records, dict):
                        records = records.get(part, records)
            if isinstance(records, dict):
                records = [records]

            total = len(records) if isinstance(records, list) else 0
            sample = records[:5] if isinstance(records, list) else records
            return json.dumps(
                {
                    "status_code": response.status_code,
                    "total_records": total,
                    "sample_records": sample,
                },
                default=str,
            )
        except httpx.HTTPStatusError as exc:
            return json.dumps(
                {"error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"}
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── ingest_webhook ───────────────────────────────────────────────────────
    if tool_name == "ingest_webhook":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.ingest import land_webhook
        from src.integrations.service import get_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot ingest data."}
            )

        integration_id = tool_input.get("connector_id") or tool_input.get(
            "integration_id"
        )
        if integration_id:
            integration = get_integration(integration_id, tenant_id)
            if not integration:
                return json.dumps({"error": f"Connector '{integration_id}' not found."})
            if integration.get("connector_type") != "webhook":
                return json.dumps(
                    {
                        "error": f"Connector '{integration['name']}' has connector_type '{integration['connector_type']}', not 'webhook'."  # noqa: E501
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
                {
                    "error": "Provide either connector_id or source to identify the target table."
                }
            )

        result = land_webhook(
            source,
            tool_input.get("data", {}),
            tool_input.get("metadata", {}),
            tenant_id,
        )
        return json.dumps(result)

    # ── create_connector ─────────────────────────────────────────────────────
    if tool_name == "create_connector":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.service import create_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot create connectors."}
            )
        name = tool_input.get("name")
        connector_type = tool_input.get("connector_type")
        if not name:
            return json.dumps({"error": "name is required for create_connector."})
        if not connector_type:
            return json.dumps(
                {
                    "error": "connector_type is required "
                    "(webhook, batch_csv, batch_json, or api_pull)."
                }
            )
        try:
            result = create_integration(tool_input, tenant_id)
        except Exception as exc:
            err_msg = str(exc)
            if "Duplicate key" in err_msg or "unique constraint" in err_msg.lower():
                return json.dumps(
                    {
                        "error": f"A connector named '{name}' already exists."
                        " Use a different name or call list_connectors"
                        " to find the existing one."
                    }
                )
            return json.dumps({"error": f"Failed to create connector: {err_msg[:200]}"})
        return json.dumps(result, default=str)

    # ── trigger_connector ─────────────────────────────────────────────────────
    if tool_name == "trigger_connector":
        from src.auth.permissions import Action, Resource, can
        from src.integrations.ingest import land_api_pull
        from src.integrations.service import get_integration

        if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
            return json.dumps(
                {"error": f"Access denied: role '{role}' cannot trigger connectors."}
            )

        connector_id = tool_input.get("connector_id", "")
        if not connector_id:
            return json.dumps({"error": "connector_id is required."})

        integration = get_integration(connector_id, tenant_id)
        if not integration:
            return json.dumps({"error": f"Connector '{connector_id}' not found."})
        if integration.get("connector_type") != "api_pull":
            ct = integration.get("connector_type")
            return json.dumps(
                {
                    "error": (
                        f"Connector '{integration['name']}' has type '{ct}', not 'api_pull'. "
                        "Only api_pull connectors can be triggered. "
                        "For webhook connectors, use ingest_webhook."
                    )
                }
            )

        config = integration.get("config") or {}
        if isinstance(config, str):
            import json as _json

            try:
                config = _json.loads(config)
            except Exception:
                config = {}
        url = config.get("url", "")
        if not url:
            return json.dumps(
                {"error": "Connector has no url in config — cannot trigger."}
            )
        headers: dict[str, str] = config.get("headers") or {}

        entity_id = integration.get("target_entity_id")
        if entity_id:
            from src.catalogue.service import get_entity

            entity = get_entity(str(entity_id), tenant_id)
            source = str(entity["name"]) if entity else str(integration["name"])
        else:
            source = str(integration["name"])

        result = land_api_pull(url, headers, source, tenant_id, connector_id)
        return json.dumps(result, default=str)

    return None
