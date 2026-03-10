"""Redis-backed cache for silver and gold entity row data.

Keys:  jonas:{tenant_id}:{layer}:{entity_name}:rows
TTL:   CACHE_TTL seconds (default 600 = 10 minutes)

All operations fail silently when Redis is unavailable — callers always
fall back to a live DuckDB query and the cache is never a hard dependency.
"""

import json
import logging
from typing import Any

import redis as redis_lib

from src.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL: int = 600  # 10 minutes

_client: redis_lib.Redis | None = None  # type: ignore[type-arg]
_client_checked: bool = False  # avoid repeated failed connections


def _get_client() -> "redis_lib.Redis | None":  # type: ignore[type-arg]
    global _client, _client_checked
    if _client is not None:
        return _client
    if _client_checked:
        return None  # already attempted and failed
    if not settings.redis_url:
        _client_checked = True
        return None
    try:
        c = redis_lib.from_url(settings.redis_url, decode_responses=True)
        c.ping()
        _client = c
        logger.info("cache: Redis connected at %s", settings.redis_url)
    except Exception as exc:
        logger.warning("cache: Redis unavailable (%s) — caching disabled", exc)
    _client_checked = True
    return _client


def close() -> None:
    global _client, _client_checked
    if _client:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _client_checked = False


def _key(tenant_id: str, layer: str, entity_name: str) -> str:
    return f"jonas:{tenant_id}:{layer}:{entity_name}:rows"


def get_cached(tenant_id: str, layer: str, entity_name: str) -> dict[str, Any] | None:
    """Return cached row data or None on miss / Redis unavailable."""
    r = _get_client()
    if not r:
        return None
    try:
        raw = r.get(_key(tenant_id, layer, entity_name))
        return json.loads(raw) if raw else None  # type: ignore[arg-type]
    except Exception as exc:
        logger.warning("cache: get error: %s", exc)
        return None


def set_cached(
    tenant_id: str, layer: str, entity_name: str, data: dict[str, Any]
) -> None:
    """Store row data with the default TTL."""
    r = _get_client()
    if not r:
        return
    try:
        r.setex(_key(tenant_id, layer, entity_name), CACHE_TTL, json.dumps(data))
    except Exception as exc:
        logger.warning("cache: set error: %s", exc)


def invalidate(tenant_id: str, layer: str, entity_name: str) -> None:
    """Delete a single entity's cached data (called after a transform writes to it)."""
    r = _get_client()
    if not r:
        return
    try:
        deleted = r.delete(_key(tenant_id, layer, entity_name))
        if deleted:
            logger.info(
                "cache: invalidated %s.%s for tenant %s", layer, entity_name, tenant_id
            )
    except Exception as exc:
        logger.warning("cache: invalidate error: %s", exc)


def invalidate_layer(tenant_id: str, layer: str) -> None:
    """Delete all cached entities for a tenant + layer (e.g. after bulk operation)."""
    r = _get_client()
    if not r:
        return
    try:
        pattern = f"jonas:{tenant_id}:{layer}:*:rows"
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
            logger.info(
                "cache: invalidated %d keys for %s.%s", len(keys), tenant_id, layer
            )
    except Exception as exc:
        logger.warning("cache: invalidate_layer error: %s", exc)
