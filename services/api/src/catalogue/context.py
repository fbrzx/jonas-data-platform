"""Catalogue context builder — generates the system-prompt description of the data model."""

import json
from typing import Any

from src.db.connection import get_conn
from src.db.tenant_schemas import layer_schema


def build_catalogue_context(tenant_id: str, role: str) -> str:
    """Return a compact text description of the catalogue, connectors and transforms."""
    from src.catalogue.service import get_accessible_entities

    entities = get_accessible_entities(tenant_id, role)

    lines: list[str] = []
    conn = get_conn()
    entity_map: dict[str, str] = {
        str(e["id"]): f"{e.get('layer','?')}.{e.get('name','?')}" for e in entities
    }

    # ── Entities ─────────────────────────────────────────────────────────────
    if not entities:
        lines.append("## Catalogue\nNo entities registered yet.\n")
    else:
        lines.append("## Catalogue entities\n")
        for e in entities:
            layer = e.get("layer", "?")
            name = e.get("name", "?")
            desc = e.get("description", "")
            lines.append(
                f"### {layer}.{name}  (id: {e['id']})" + (f"  — {desc}" if desc else "")
            )

            scoped_schema = layer_schema(layer, tenant_id)
            try:
                phys_rows = conn.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                    [scoped_schema, name],
                ).fetchall()
                phys_cols = [r[0] for r in phys_rows]
            except Exception:
                phys_cols = []

            if phys_cols:
                _WEBHOOK_SIG = {
                    "id",
                    "tenant_id",
                    "ingested_at",
                    "source",
                    "payload",
                    "metadata",
                }
                _CSV_SIG = {"_id", "_tenant_id", "_ingested_at"}
                phys_set = set(phys_cols)
                is_webhook = _WEBHOOK_SIG.issubset(phys_set)
                is_csv = _CSV_SIG.issubset(phys_set) and "payload" not in phys_set

                if is_webhook:
                    lines.append(
                        "  STORAGE: webhook — fields are inside `payload` JSON column. "
                        "Use json_extract_string(payload, '$.field') for strings, "
                        "CAST(json_extract(payload, '$.field') AS type) for typed values. "
                        "NEVER use bare field names as SQL columns."
                    )
                    lines.append(f"  Physical columns: {', '.join(phys_cols)}")
                    try:
                        sample_row = conn.execute(
                            f"SELECT payload FROM {scoped_schema}.{name} LIMIT 1"  # noqa: S608
                        ).fetchone()
                        if sample_row and sample_row[0]:
                            sample_payload = (
                                json.loads(sample_row[0])
                                if isinstance(sample_row[0], str)
                                else sample_row[0]
                            )
                            if isinstance(sample_payload, dict):
                                keys = list(sample_payload.keys())[:15]
                                lines.append(
                                    f"  Payload keys: {', '.join(keys)}"
                                    f"  — example: json_extract_string(payload, '$.{keys[0]}')"
                                )
                                for k, v in sample_payload.items():
                                    if (
                                        isinstance(v, list)
                                        and v
                                        and isinstance(v[0], dict)
                                    ):
                                        sub_keys = list(v[0].keys())[:8]
                                        lines.append(
                                            f"  Array field '{k}': unnest with "
                                            f"CROSS JOIN UNNEST(json_extract(payload, '$.{k}')::JSON[]) AS t(elem)"  # noqa: E501
                                            f" — sub-keys: {', '.join(sub_keys)}"
                                        )
                            elif (
                                isinstance(sample_payload, list)
                                and sample_payload
                                and isinstance(sample_payload[0], dict)
                            ):
                                keys = list(sample_payload[0].keys())[:15]
                                lines.append(
                                    f"  Payload keys (array/first element): {', '.join(keys)}"
                                )
                    except Exception:
                        pass
                elif is_csv:
                    lines.append(
                        f"  STORAGE: csv — use these columns directly (all VARCHAR, CAST as needed): "  # noqa: E501
                        f"{', '.join(phys_cols)}"
                    )
                else:
                    lines.append(
                        f"  STORAGE: flat — typed structured table (created by transform). "
                        f"Use these columns directly with their native types: {', '.join(phys_cols)}"  # noqa: E501
                    )
            else:
                lines.append("  (table not yet created in DuckDB — no data ingested)")

            fields: list[dict[str, Any]] = e.get("fields", [])
            if fields:
                field_names = ", ".join(f["name"] for f in fields)
                pii_fields = [f["name"] for f in fields if f.get("is_pii")]
                lines.append(f"  Catalogue fields: {field_names}")
                if pii_fields:
                    lines.append(f"  PII fields: {', '.join(pii_fields)}")
            lines.append("")

    # ── Connectors ───────────────────────────────────────────────────────────
    try:
        int_rows = conn.execute(
            "SELECT id, name, connector_type, status, target_entity_id FROM integrations.connector WHERE tenant_id = ?",  # noqa: E501
            [tenant_id],
        ).fetchall()
        int_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        integrations = [dict(zip(int_cols, r)) for r in int_rows]
    except Exception:
        integrations = []

    if integrations:
        lines.append("## Connectors (data sources)\n")
        for i in integrations:
            eid = str(i.get("target_entity_id") or "")
            linked = f" → {entity_map.get(eid, eid)}" if eid else " (no entity linked)"
            trigger = (
                f"  trigger: POST /api/v1/connectors/{i['id']}/trigger"
                if i.get("connector_type") == "api_pull"
                else ""
            )
            lines.append(
                f"- {i['name']} (id: {i['id']}, type: {i.get('connector_type')}, "
                f"status: {i.get('status')}){linked}"
            )
            if trigger:
                lines.append(f"  {trigger}")
        lines.append("")

    # ── Transforms ───────────────────────────────────────────────────────────
    try:
        t_rows = conn.execute(
            "SELECT id, name, description, source_layer, target_layer, status, transform_sql, trigger_mode "  # noqa: E501
            "FROM transforms.transform WHERE tenant_id = ?",  # noqa: E501
            [tenant_id],
        ).fetchall()
        t_cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
        transforms = [dict(zip(t_cols, r)) for r in t_rows]
    except Exception:
        transforms = []

    if transforms:
        lines.append("## Transforms\n")
        for t in transforms:
            sql_preview = (t.get("transform_sql") or "")[:80].replace("\n", " ")
            desc = t.get("description", "")
            trigger_info = (
                f", trigger: {t.get('trigger_mode','manual')}"
                if t.get("trigger_mode") and t.get("trigger_mode") != "manual"
                else ""
            )
            lines.append(
                f"- {t['name']} (id: {t['id']}, {t.get('source_layer')}→{t.get('target_layer')}, "
                f"status: {t.get('status')}{trigger_info})"
                + (f"  — {desc}" if desc else "")
            )
            if sql_preview:
                lines.append(f"  sql: {sql_preview}…")
        lines.append("")

    return "\n".join(lines)


def build_catalogue_context_compact(tenant_id: str, role: str) -> str:
    """Return a minimal catalogue summary for small LLMs.

    One line per entity, one line per connector — no SQL examples, no payload
    introspection, no transform SQL previews.  Keeps the prompt short so the
    model focuses on tool-use instead of regurgitating instructions.
    """
    from src.catalogue.service import get_accessible_entities

    entities = get_accessible_entities(tenant_id, role)
    conn = get_conn()
    lines: list[str] = []

    # Entities — one line each
    if not entities:
        lines.append("## Data: (none yet)")
    else:
        lines.append("## Data")
        for e in entities:
            layer = e.get("layer", "?")
            name = e.get("name", "?")
            eid = e["id"]
            desc = e.get("description", "")
            suffix = f" — {desc}" if desc else ""
            lines.append(f"- {layer}.{name} (id: {eid}){suffix}")

    # Connectors — one line each
    try:
        rows = conn.execute(
            "SELECT id, name, connector_type, status "
            "FROM integrations.connector WHERE tenant_id = ?",
            [tenant_id],
        ).fetchall()
    except Exception:
        rows = []

    if rows:
        lines.append("\n## Connectors")
        for r in rows:
            lines.append(f"- {r[1]} (id: {r[0]}, type: {r[2]}, status: {r[3]})")

    # Transforms — one line each
    try:
        rows = conn.execute(
            "SELECT id, name, source_layer, target_layer, status "
            "FROM transforms.transform WHERE tenant_id = ?",
            [tenant_id],
        ).fetchall()
    except Exception:
        rows = []

    if rows:
        lines.append("\n## Transforms")
        for r in rows:
            lines.append(f"- {r[1]} (id: {r[0]}, {r[2]}->{r[3]}, status: {r[4]})")

    return "\n".join(lines)
