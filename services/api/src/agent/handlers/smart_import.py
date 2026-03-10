"""smart_import handler — end-to-end data pipeline in one tool call.

Deterministically chains: discover → infer → register → connect → ingest → flatten transform.
"""

from __future__ import annotations

import json
from typing import Any

_TOOLS = {"smart_import"}


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

    from src.auth.permissions import Action, Resource, can

    if not can({"role": role}, Resource.INTEGRATION, Action.WRITE):
        return json.dumps(
            {"error": f"Access denied: role '{role}' cannot import data."}
        )

    name = tool_input.get("name", "").strip()
    if not name:
        return json.dumps({"error": "name is required (snake_case entity name)."})

    source_type = tool_input.get("source_type", "")
    if source_type not in ("api_pull", "webhook", "sample_json"):
        return json.dumps(
            {"error": "source_type must be 'api_pull', 'webhook', or 'sample_json'."}
        )

    description = tool_input.get("description", "")
    namespace = tool_input.get("namespace", "")
    collection = tool_input.get("collection")
    skip_transform = tool_input.get("skip_transform", False)
    pk_field_override = tool_input.get("primary_key_field")

    steps: list[str] = []
    result: dict[str, Any] = {"name": name}

    try:
        # ── Step 1: Obtain sample data ─────────────────────────────────────
        sample_records: list[dict] = []

        if source_type == "api_pull":
            url = tool_input.get("url", "").strip()
            if not url:
                return json.dumps(
                    {"error": "url is required for api_pull source_type."}
                )
            method = tool_input.get("method", "GET").upper()
            headers: dict[str, str] = tool_input.get("headers") or {}
            json_path: str = tool_input.get("json_path", "")
            pagination: dict[str, Any] = tool_input.get("pagination") or {}

            sample_records = _discover_sample(url, method, headers, json_path)
            if not sample_records:
                return json.dumps(
                    {"error": f"No records found at {url} (json_path='{json_path}')."}
                )
            steps.append(f"Discovered {len(sample_records)} sample records from API")

        elif source_type in ("webhook", "sample_json"):
            raw = tool_input.get("sample_data")
            if not raw:
                return json.dumps(
                    {
                        "error": "sample_data is required for webhook/sample_json source_type."
                    }
                )
            if isinstance(raw, dict):
                sample_records = [raw]
            elif isinstance(raw, list):
                sample_records = [r for r in raw if isinstance(r, dict)]
            if not sample_records:
                return json.dumps(
                    {"error": "sample_data must be a JSON object or array of objects."}
                )
            steps.append(f"Received {len(sample_records)} sample records")

        # ── Step 2: Infer schema ───────────────────────────────────────────
        from src.agent.inference import infer_from_json

        fields = infer_from_json(
            sample_records if len(sample_records) > 1 else sample_records[0]
        )
        pii_fields = [f["name"] for f in fields if f.get("is_pii")]
        steps.append(
            f"Inferred {len(fields)} fields"
            + (f" ({len(pii_fields)} PII)" if pii_fields else "")
        )

        # ── Step 3: Register bronze entity ─────────────────────────────────
        from src.catalogue.service import create_entity, create_fields_bulk

        entity_data: dict[str, Any] = {
            "name": name,
            "layer": "bronze",
            "description": description,
            "tags": [namespace] if namespace else [],
        }
        if collection:
            entity_data["collection"] = collection

        try:
            entity = create_entity(entity_data, tenant_id)
        except ValueError as exc:
            return json.dumps({"error": f"Entity registration failed: {exc}"})

        create_fields_bulk(entity["id"], fields, created_by)
        entity_id = str(entity["id"])
        result["entity_id"] = entity_id
        steps.append(f"Registered bronze entity '{name}' ({entity_id})")

        # ── Step 4: Create connector ───────────────────────────────────────
        from src.integrations.service import create_integration

        connector_data: dict[str, Any] = {
            "name": f"{name}_connector",
            "description": f"Auto-created connector for {name}",
            "connector_type": "api_pull" if source_type == "api_pull" else "webhook",
            "entity_id": entity_id,
        }
        if collection:
            connector_data["collection"] = collection

        if source_type == "api_pull":
            connector_config: dict[str, Any] = {
                "url": url,
                "headers": headers,
            }
            if json_path:
                connector_config["json_path"] = json_path
            if pagination:
                connector_config["pagination"] = pagination
            connector_data["config"] = connector_config

        connector = create_integration(connector_data, tenant_id)
        connector_id = str(connector["id"])
        result["connector_id"] = connector_id
        steps.append(
            f"Created {connector_data['connector_type']} connector ({connector_id})"
        )

        # ── Step 5: Ingest data ────────────────────────────────────────────
        from src.integrations.ingest import land_api_pull, land_webhook

        total_landed = 0
        ingest_errors: list[str] = []

        if source_type == "api_pull":
            ingest_result = land_api_pull(
                url,
                headers,
                name,
                tenant_id,
                connector_id,
                json_path=json_path,
                pagination=pagination,
            )
            total_landed = ingest_result.get("rows_landed", 0)
            ingest_errors = ingest_result.get("errors", [])
            pages = ingest_result.get("pages_fetched", 1)
            steps.append(
                f"Ingested {total_landed} rows across {pages} page(s)"
                + (f" ({len(ingest_errors)} errors)" if ingest_errors else "")
            )
        else:
            # webhook / sample_json — ingest the sample data
            data_to_ingest = tool_input.get("sample_data", sample_records)
            if isinstance(data_to_ingest, dict):
                data_to_ingest = [data_to_ingest]
            for record in data_to_ingest:
                r = land_webhook(
                    name,
                    record,
                    {},
                    tenant_id,
                    integration_id=connector_id,
                    _fire_trigger=False,
                )
                total_landed += r["rows_landed"]
                ingest_errors.extend(r.get("errors", []))
            steps.append(f"Ingested {total_landed} rows via webhook")

        result["rows_landed"] = total_landed
        if ingest_errors:
            result["ingest_errors"] = ingest_errors[:10]

        # ── Step 6: Generate bronze→silver transform ───────────────────────
        if not skip_transform and total_landed > 0:
            from src.agent.handlers.flatten_sql import (
                detect_primary_key,
                generate_flatten_sql,
            )
            from src.transforms.service import create_transform

            pk = pk_field_override or detect_primary_key(fields, name)
            if not pk:
                # Fallback: use first field
                pk = fields[0]["name"] if fields else "id"
                steps.append(f"No obvious PK detected, using '{pk}' as primary key")

            sql = generate_flatten_sql(name, fields, pk, tenant_id)

            transform_data: dict[str, Any] = {
                "name": f"flatten_{name}",
                "description": f"Auto-flatten bronze.{name} → silver.{name}",
                "source_layer": "bronze",
                "target_layer": "silver",
                "transform_sql": sql,
                "trigger_mode": "on_change",
                "watch_entities": [entity_id],
            }
            transform = create_transform(transform_data, tenant_id, created_by)
            transform_id = str(transform["id"])
            result["transform_id"] = transform_id
            result["transform_status"] = "draft — needs admin approval"
            result["transform_sql"] = sql
            steps.append(
                f"Created on_change transform 'flatten_{name}' ({transform_id})"
            )

            # Register silver entity
            silver_fields = [
                {
                    "name": f["name"],
                    "data_type": f["data_type"],
                    "nullable": f.get("nullable", True),
                    "is_pii": f.get("is_pii", False),
                }
                for f in fields
            ]
            silver_entity_data: dict[str, Any] = {
                "name": name,
                "layer": "silver",
                "description": f"Cleaned/typed version of bronze.{name}",
                "tags": [namespace] if namespace else [],
            }
            if collection:
                silver_entity_data["collection"] = collection

            try:
                silver_entity = create_entity(silver_entity_data, tenant_id)
                create_fields_bulk(silver_entity["id"], silver_fields, created_by)
                result["silver_entity_id"] = str(silver_entity["id"])
                steps.append(f"Registered silver entity '{name}'")
            except ValueError:
                steps.append("Silver entity already exists — skipped registration")

        elif skip_transform:
            steps.append("Transform creation skipped (skip_transform=true)")
        elif total_landed == 0:
            steps.append("Transform creation skipped (no data landed)")

        result["steps"] = steps
        result["next_step"] = (
            "Approve the transform via the dashboard, then it will auto-run "
            "on every new ingest."
            if result.get("transform_id")
            else "Data is in bronze. Create a transform to promote to silver."
        )
        return json.dumps(result, default=str)

    except Exception as exc:
        return json.dumps(
            {
                "error": f"smart_import failed: {str(exc)[:300]}",
                "steps_completed": steps,
            }
        )


def _discover_sample(
    url: str, method: str, headers: dict[str, str], json_path: str
) -> list[dict]:
    """Fetch a single page from the API and extract sample records."""
    import httpx

    from src.security.ssrf import check_url

    ssrf_err = check_url(url)
    if ssrf_err:
        raise ValueError(ssrf_err)

    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        if method == "POST":
            response = client.post(url, headers=headers)
        else:
            response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    from src.integrations.ingest import _resolve_json_path

    records = _resolve_json_path(data, json_path)
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        return []

    return [r for r in records[:10] if isinstance(r, dict)]
