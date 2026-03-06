"""Event-driven transform dispatch.

Fires approved transforms whose trigger_mode='on_change' when watched entities change.
Designed for fire-and-forget use — callers spawn this in a daemon thread.

Protections:
- Debounce: skip if the transform ran within the last DEBOUNCE_SECONDS.
- Cascade depth limit: refuse to trigger beyond MAX_CASCADE_DEPTH to prevent loops.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS: int = 30
MAX_CASCADE_DEPTH: int = 5

# In-memory set of (transform_id, tenant_id) currently being triggered — cycle guard.
_in_flight: set[tuple[str, str]] = set()
_in_flight_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(UTC)


def _resolve_entity_id(entity_name: str, layer: str, tenant_id: str) -> str | None:
    """Look up entity_id by name + layer + tenant_id in the catalogue."""
    from src.db.connection import get_conn

    try:
        row = (
            get_conn()
            .execute(
                "SELECT id FROM catalogue.entity WHERE name = ? AND layer = ? AND tenant_id = ?",
                [entity_name, layer, tenant_id],
            )
            .fetchone()
        )
        return str(row[0]) if row else None
    except Exception:
        return None


def _find_watching_transforms(entity_id: str, tenant_id: str) -> list[dict[str, Any]]:
    """Return approved transforms that are watching this entity_id."""
    from src.db.connection import get_conn

    try:
        rows = (
            get_conn()
            .execute(
                """
            SELECT id, name, transform_sql, last_run_at
            FROM transforms.transform
            WHERE tenant_id = ?
              AND trigger_mode = 'on_change'
              AND status = 'approved'
            """,
                [tenant_id],
            )
            .fetchall()
        )
        cols = ["id", "name", "transform_sql", "last_run_at"]
        transforms = [dict(zip(cols, r)) for r in rows]

        # Filter to those watching this entity_id
        watching = []
        for t in transforms:
            raw = t.get("watch_entities") or "[]"
            try:
                watched: list[str] = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                watched = []
            if entity_id in watched:
                watching.append(t)
        return watching
    except Exception as exc:
        logger.warning("triggers: could not query watching transforms: %s", exc)
        return []


def _is_debounced(last_run_at: str | None) -> bool:
    """Return True if the transform ran within the debounce window."""
    if not last_run_at:
        return False
    try:
        last = datetime.fromisoformat(str(last_run_at).replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        return (_now() - last) < timedelta(seconds=DEBOUNCE_SECONDS)
    except Exception:
        return False


def on_data_changed(
    entity_name: str,
    layer: str,
    tenant_id: str,
    _depth: int = 0,
) -> None:
    """Dispatch on_change transforms for the given entity.

    Intended to be called in a background thread after data lands or a transform completes.
    """
    if _depth >= MAX_CASCADE_DEPTH:
        logger.warning(
            "triggers: max cascade depth %d reached for %s.%s — stopping",
            MAX_CASCADE_DEPTH,
            layer,
            entity_name,
        )
        return

    entity_id = _resolve_entity_id(entity_name, layer, tenant_id)
    if not entity_id:
        return  # Entity not yet in catalogue — nothing to trigger

    watching = _find_watching_transforms(entity_id, tenant_id)
    if not watching:
        return

    for transform in watching:
        transform_id: str = str(transform["id"])
        key = (transform_id, tenant_id)

        with _in_flight_lock:
            if key in _in_flight:
                logger.debug(
                    "triggers: %s already in flight, skipping (cycle guard)",
                    transform["name"],
                )
                continue
            _in_flight.add(key)

        try:
            if _is_debounced(transform.get("last_run_at")):
                logger.debug(
                    "triggers: %s debounced (ran within %ds)",
                    transform["name"],
                    DEBOUNCE_SECONDS,
                )
                continue

            logger.info(
                "triggers: depth=%d firing '%s' (watched entity: %s.%s)",
                _depth,
                transform["name"],
                layer,
                entity_name,
            )

            # Lazy import to avoid circular dependency at module load time
            from src.transforms.service import execute_transform

            result = execute_transform(transform_id, tenant_id)

            if not result.get("errors"):
                # Cascade: notify watchers of the transform's target entity
                import re

                sql = str(transform.get("transform_sql", ""))
                target_match = re.search(
                    r"(?i)\b(?:CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+)"
                    r"(?:[a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)",
                    sql,
                )
                if target_match:
                    target_name = target_match.group(1)
                    # Determine target layer from transform record
                    from src.db.connection import get_conn

                    row = (
                        get_conn()
                        .execute(
                            "SELECT target_layer FROM transforms.transform WHERE id = ?",
                            [transform_id],
                        )
                        .fetchone()
                    )
                    target_layer = str(row[0]) if row else "silver"
                    on_data_changed(target_name, target_layer, tenant_id, _depth + 1)
        except Exception as exc:
            logger.error(
                "triggers: error executing '%s': %s", transform.get("name"), exc
            )
        finally:
            with _in_flight_lock:
                _in_flight.discard(key)


def fire_on_data_changed(entity_name: str, layer: str, tenant_id: str) -> None:
    """Non-blocking wrapper: spawns on_data_changed in a daemon thread."""
    t = threading.Thread(
        target=on_data_changed,
        args=(entity_name, layer, tenant_id),
        daemon=True,
    )
    t.start()
