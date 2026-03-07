"""Dashboard handler — generates Observable Framework .md dashboard files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def handle(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tenant_id: str,
    role: str,
    created_by: str,
) -> str | None:
    if tool_name != "create_dashboard":
        return None

    slug = tool_input.get("slug", "").strip()
    title = tool_input.get("title", "Dashboard").strip()
    description = tool_input.get("description", "").strip()
    entities = tool_input.get("entities", [])

    if not slug:
        return json.dumps({"error": "slug is required"})
    if not entities:
        return json.dumps({"error": "at least one entity is required"})

    # Sanitise slug
    slug = "".join(c if c.isalnum() or c in "_-" else "_" for c in slug.lower())

    md = _render_dashboard(slug, title, description, entities)

    out_path = _write_dashboard(tenant_id, slug, md)
    if out_path is None:
        return json.dumps({"error": "Failed to write dashboard file"})

    chart_count = sum(len(e.get("charts", [])) for e in entities)
    return json.dumps(
        {
            "path": str(out_path),
            "slug": slug,
            "title": title,
            "entities": len(entities),
            "charts": chart_count,
            "note": (
                "Dashboard written. Analysts can open this .md file with Observable Framework: "
                "`npm i -g @observablehq/framework && observable preview`"
            ),
        }
    )


# ── Rendering ─────────────────────────────────────────────────────────────────


def _render_dashboard(
    slug: str,
    title: str,
    description: str,
    entities: list[dict[str, Any]],
) -> str:
    sections: list[str] = []

    # Frontmatter
    sections.append(f"---\ntitle: {title}\n---\n")

    # Heading + description
    sections.append(f"# {title}\n")
    if description:
        sections.append(f"{description}\n")

    # Shared loader block — one fetch helper wired to the Jonas API
    sections.append(_loader_block())

    # Per-entity sections
    for entity in entities:
        sections.append(_entity_section(entity))

    return "\n".join(sections)


def _loader_block() -> str:
    return '```js\nimport { jonasPreview } from "./jonas.config.js";\n```\n'


def _entity_section(entity: dict[str, Any]) -> str:
    layer = entity.get("layer", "bronze")
    name = entity.get("name", "unknown")
    charts: list[dict[str, Any]] = entity.get("charts", [])
    fields: list[dict[str, Any]] = entity.get("fields", [])

    parts: list[str] = []
    heading = name.replace("_", " ").title()
    parts.append(f"## {heading}\n")

    # Data loader for this entity
    var = _var(name)
    parts.append(
        f'```js\nconst {var} = await jonasPreview("{layer}", "{name}");\n```\n'
    )

    # Field list as a comment block so analyst knows what's available
    if fields:
        field_info = ", ".join(
            f["name"] + ("*" if f.get("is_pii") else "") for f in fields
        )
        parts.append(f"<!-- Available fields: {field_info} (* = PII masked) -->\n")

    # Charts — fall back to a table if none specified
    if not charts:
        charts = [{"type": "table", "title": f"{heading} rows"}]

    for chart in charts:
        parts.append(_chart_block(var, chart))

    return "\n".join(parts)


def _chart_block(var: str, chart: dict[str, Any]) -> str:
    chart_type = chart.get("type", "table")
    chart_title = chart.get("title", "")
    x = chart.get("x", "")
    y = chart.get("y", "")
    color = chart.get("color", "")
    sort = chart.get("sort", "desc")

    if chart_title:
        heading = f"### {chart_title}\n\n"
    else:
        heading = ""

    if chart_type == "table":
        body = f"Inputs.table({var})"

    elif chart_type == "bar":
        sort_clause = ""
        if sort in ("asc", "desc"):
            reverse = "true" if sort == "desc" else "false"
            sort_clause = f', sort: {{x: "y", reverse: {reverse}}}'
        color_opt = f', fill: "{color}"' if color else ""
        if y:
            body = (
                f"Plot.plot({{\n"
                f"  marks: [\n"
                f'    Plot.barY({var}, Plot.groupX({{y: "sum"}}, {{x: "{x}", y: "{y}"{color_opt}{sort_clause}}})),\n'  # noqa: E501
                f"    Plot.ruleY([0])\n"
                f"  ]\n"
                f"}})"
            )
        else:
            body = (
                f"Plot.plot({{\n"
                f"  marks: [\n"
                f'    Plot.barY({var}, Plot.groupX({{y: "count"}}, {{x: "{x}"{color_opt}{sort_clause}}})),\n'  # noqa: E501
                f"    Plot.ruleY([0])\n"
                f"  ]\n"
                f"}})"
            )

    elif chart_type == "line":
        color_opt = f', stroke: "{color}"' if color else ""
        body = (
            f"Plot.plot({{\n"
            f"  marks: [\n"
            f'    Plot.lineY({var}, {{x: "{x}", y: "{y}"{color_opt}}}),\n'
            f"    Plot.ruleY([0])\n"
            f"  ]\n"
            f"}})"
        )

    elif chart_type == "scatter":
        color_opt = f', fill: "{color}"' if color else ""
        body = (
            f"Plot.plot({{\n"
            f"  marks: [\n"
            f'    Plot.dot({var}, {{x: "{x}", y: "{y}"{color_opt}}})\n'
            f"  ]\n"
            f"}})"
        )

    elif chart_type == "histogram":
        body = (
            f"Plot.plot({{\n"
            f"  marks: [\n"
            f'    Plot.rectY({var}, Plot.binX({{y: "count"}}, {{x: "{x}"}})),\n'
            f"    Plot.ruleY([0])\n"
            f"  ]\n"
            f"}})"
        )

    else:
        body = f"Inputs.table({var})"

    return f"{heading}```js\n{body}\n```\n"


def _var(name: str) -> str:
    """Convert entity name to a safe JS variable name."""
    return "".join(("_" if not c.isalnum() else c) for c in name).lstrip("_") or "data"


# ── File I/O ──────────────────────────────────────────────────────────────────


def _write_dashboard(tenant_id: str, slug: str, content: str) -> Path | None:
    try:
        from src.config import settings

        root = Path(settings.dashboards_root)
        safe_tenant = "".join(c if c.isalnum() or c in "-_" else "_" for c in tenant_id)
        out_dir = root / safe_tenant
        out_dir.mkdir(parents=True, exist_ok=True)
        _ensure_config(out_dir)
        out_path = out_dir / f"{slug}.md"
        out_path.write_text(content, encoding="utf-8")
        return out_path
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to write dashboard")
        return None


_CONFIG_TEMPLATE = """\
// Jonas Data Platform — shared API configuration
// This file is auto-generated once. Edit freely — it will not be overwritten.
//
// API points to the local Jonas instance. Change if your setup differs.
const _API = "http://localhost:8000";

function _token() {
  return typeof localStorage !== "undefined"
    ? (localStorage.getItem("jonas_token") ?? "admin-token")
    : "admin-token";
}

export async function jonasPreview(layer, name, limit = 500) {
  const token = _token();
  const listRes = await fetch(
    `${_API}/api/v1/catalogue/entities?layer=${encodeURIComponent(layer)}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!listRes.ok) throw new Error(`catalogue list error: ${listRes.status}`);
  const entities = await listRes.json();
  const entity = entities.find((e) => e.name === name);
  if (!entity) throw new Error(`Entity ${layer}.${name} not found in catalogue`);

  const previewRes = await fetch(
    `${_API}/api/v1/catalogue/entities/${entity.id}/preview?limit=${limit}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  if (!previewRes.ok) throw new Error(`preview error: ${previewRes.status}`);
  const { rows } = await previewRes.json();
  return rows ?? [];
}
"""


def _ensure_config(out_dir: Path) -> None:
    """Write jonas.config.js once — never overwrites an existing file."""
    config_path = out_dir / "jonas.config.js"
    if not config_path.exists():
        config_path.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
