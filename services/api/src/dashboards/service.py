"""Dashboard file service — list, read, write, delete .md files on disk."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _root(tenant_id: str) -> Path:
    from src.config import settings

    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", tenant_id)
    return Path(settings.dashboards_root) / safe


def _slug_safe(slug: str) -> str:
    """Validate slug — must be snake_case alphanum + underscore/hyphen only."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", slug):
        raise ValueError(
            f"Invalid slug '{slug}': use lowercase letters, digits, _ and - only"
        )
    return slug


def list_dashboards(tenant_id: str) -> list[dict[str, Any]]:
    root = _root(tenant_id)
    if not root.exists():
        return []
    result = []
    for p in sorted(root.glob("*.md")):
        stat = p.stat()
        title = _extract_title(p.read_text(encoding="utf-8", errors="replace"))
        result.append(
            {
                "slug": p.stem,
                "title": title or p.stem.replace("_", " ").title(),
                "size_bytes": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return result


def get_dashboard(tenant_id: str, slug: str) -> dict[str, Any] | None:
    slug = _slug_safe(slug)
    path = _root(tenant_id) / f"{slug}.md"
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    title = _extract_title(content)
    return {
        "slug": slug,
        "title": title or slug.replace("_", " ").title(),
        "content": content,
    }


def save_dashboard(tenant_id: str, slug: str, content: str) -> dict[str, Any]:
    slug = _slug_safe(slug)
    root = _root(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    title = _extract_title(content)
    return {
        "slug": slug,
        "title": title or slug.replace("_", " ").title(),
        "size_bytes": path.stat().st_size,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def delete_dashboard(tenant_id: str, slug: str) -> bool:
    slug = _slug_safe(slug)
    path = _root(tenant_id) / f"{slug}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


_CONFIG_FILENAME = "jonas.config.js"


def get_config(tenant_id: str) -> str | None:
    path = _root(tenant_id) / _CONFIG_FILENAME
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def save_config(tenant_id: str, content: str) -> None:
    root = _root(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    (root / _CONFIG_FILENAME).write_text(content, encoding="utf-8")


def _extract_title(content: str) -> str:
    """Pull title from frontmatter or first H1."""
    for line in content.splitlines():
        m = re.match(r"^title:\s*(.+)$", line.strip())
        if m:
            return m.group(1).strip()
    for line in content.splitlines():
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip()
    return ""
