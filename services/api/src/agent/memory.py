"""Agent memory — persistent per-tenant knowledge store.

Three operations exposed as agent tools:
  save_memory    — store a new memory item
  recall_memories — keyword search + relevance ranking
  forget_memory  — delete a specific memory

Auto-injection:
  build_memory_context(tenant_id, user_message) → section string for system prompt

Lifecycle helpers:
  decay_memories  — apply daily score decay (call from a scheduler or on bootstrap)
  prune_memories  — delete stale/irrelevant memories
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from src.db.connection import get_conn

_VALID_CATEGORIES = {"routine", "solution", "preference", "context"}
_DECAY_FACTOR = 0.95
_BOOST_FACTOR = 1.2
_MAX_SCORE = 2.0
_PRUNE_SCORE = 0.1
_PRUNE_DAYS = 90
_MAX_INJECTED = 5


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── CRUD ──────────────────────────────────────────────────────────────────────


def save_memory(
    tenant_id: str,
    category: str,
    summary: str,
    content: Any,
    created_by: str = "agent",
) -> dict[str, Any]:
    """Persist a new memory item and return it."""
    if category not in _VALID_CATEGORIES:
        category = "context"
    memory_id = str(uuid.uuid4())
    now = _now()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO audit.agent_memory
            (id, tenant_id, category, summary, content,
             relevance_score, created_by, created_at, last_used_at, use_count)
        VALUES (?, ?, ?, ?, ?, 1.0, ?, ?, ?, 0)
        """,
        [
            memory_id,
            tenant_id,
            category,
            summary,
            json.dumps(content) if not isinstance(content, str) else content,
            created_by,
            now,
            now,
        ],
    )
    return get_memory(memory_id, tenant_id) or {"id": memory_id, "summary": summary}


def get_memory(memory_id: str, tenant_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM audit.agent_memory WHERE id = ? AND tenant_id = ?",
        [memory_id, tenant_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return dict(zip(cols, row))


def forget_memory(memory_id: str, tenant_id: str) -> bool:
    existing = get_memory(memory_id, tenant_id)
    if not existing:
        return False
    get_conn().execute(
        "DELETE FROM audit.agent_memory WHERE id = ? AND tenant_id = ?",
        [memory_id, tenant_id],
    )
    return True


def list_memories(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT * FROM audit.agent_memory
        WHERE tenant_id = ?
        ORDER BY relevance_score DESC, last_used_at DESC
        LIMIT ?
        """,
        [tenant_id, limit],
    ).fetchall()
    cols = [d[0] for d in conn.description]  # type: ignore[union-attr]
    return [dict(zip(cols, row)) for row in rows]


# ── Search & relevance ────────────────────────────────────────────────────────


def _extract_keywords(text: str) -> list[str]:
    """Extract lowercase words ≥4 chars, excluding common stop words."""
    _STOP = {
        "with",
        "that",
        "this",
        "from",
        "have",
        "they",
        "will",
        "what",
        "when",
        "where",
        "which",
        "into",
        "some",
        "your",
        "data",
        "table",
    }
    words = re.findall(r"[a-z]{4,}", text.lower())
    return [w for w in words if w not in _STOP]


def _score_memory(memory: dict[str, Any], keywords: list[str]) -> float:
    """Compute a match score: relevance_score * keyword_hit_count."""
    if not keywords:
        return float(memory.get("relevance_score") or 1.0)
    text = (memory.get("summary") or "").lower()
    hits = sum(1 for kw in keywords if kw in text)
    base = float(memory.get("relevance_score") or 1.0)
    return base * (1 + hits * 0.5)


def recall_memories(
    tenant_id: str, query: str = "", limit: int = _MAX_INJECTED
) -> list[dict[str, Any]]:
    """Return the most relevant memories for `query`, boosting scores on recall."""
    all_memories = list_memories(tenant_id, limit=100)
    if not all_memories:
        return []

    keywords = _extract_keywords(query)
    scored = sorted(
        all_memories, key=lambda m: _score_memory(m, keywords), reverse=True
    )
    top = scored[:limit]

    # Boost relevance_score for recalled memories
    now = _now()
    conn = get_conn()
    for m in top:
        new_score = min(
            _MAX_SCORE, float(m.get("relevance_score") or 1.0) * _BOOST_FACTOR
        )
        new_count = int(m.get("use_count") or 0) + 1
        conn.execute(
            "UPDATE audit.agent_memory SET relevance_score = ?, last_used_at = ?, use_count = ? WHERE id = ?",
            [new_score, now, new_count, m["id"]],
        )

    return top


# ── System prompt injection ───────────────────────────────────────────────────


def build_memory_context(tenant_id: str, user_message: str) -> str:
    """Return a compact memory section for the system prompt, or empty string."""
    try:
        memories = recall_memories(tenant_id, user_message, limit=_MAX_INJECTED)
    except Exception:
        return ""
    if not memories:
        return ""

    lines = ["## What I remember about this tenant\n"]
    for m in memories:
        cat = m.get("category", "context")
        summary = m.get("summary", "")
        content_raw = m.get("content")
        try:
            content = (
                json.loads(content_raw) if isinstance(content_raw, str) else content_raw
            )
        except Exception:
            content = content_raw

        detail = ""
        if isinstance(content, dict) and content:
            detail = " — " + "; ".join(
                f"{k}: {v}" for k, v in list(content.items())[:3]
            )
        elif isinstance(content, str) and content:
            detail = f" — {content[:120]}"

        lines.append(f"- [{cat}] {summary}{detail}")

    return "\n".join(lines) + "\n"


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def decay_memories(tenant_id: str) -> int:
    """Apply daily score decay to all memories. Returns count updated."""
    conn = get_conn()
    result = conn.execute(
        """
        UPDATE audit.agent_memory
        SET relevance_score = GREATEST(0.0, relevance_score * ?)
        WHERE tenant_id = ?
        """,
        [_DECAY_FACTOR, tenant_id],
    )
    return result.rowcount if hasattr(result, "rowcount") else 0


def prune_memories(tenant_id: str) -> int:
    """Delete memories below score threshold or unused for too long. Returns deleted count."""
    cutoff = (datetime.now(UTC) - timedelta(days=_PRUNE_DAYS)).isoformat()
    conn = get_conn()
    result = conn.execute(
        """
        DELETE FROM audit.agent_memory
        WHERE tenant_id = ?
          AND (relevance_score < ? OR last_used_at < ?)
        """,
        [tenant_id, _PRUNE_SCORE, cutoff],
    )
    return result.rowcount if hasattr(result, "rowcount") else 0
