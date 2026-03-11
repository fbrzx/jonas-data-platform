"""OAuth 2.0 token management for api_pull connector auth_config.

Supported grant types
---------------------
client_credentials
    Standard M2M flow.  Used by Salesforce Connected Apps and Adobe IMS.
    Required fields: token_url, client_id, client_secret
    Optional:        scope, audience (Adobe)

refresh_token
    Exchange a long-lived refresh token for a short-lived access token.
    Handles token rotation: if the server returns a new refresh_token, it is
    persisted back to the connector's auth_config in the DB automatically.
    Required fields: token_url, client_id, client_secret, refresh_token
    Optional:        scope

password
    Resource-owner password flow.
    Required fields: token_url, client_id, client_secret, username, password
    Optional:        scope

salesforce_jwt
    Salesforce JWT Bearer Token flow (no client_secret needed on the org).
    Required fields: token_url, client_id, private_key_pem, subject (SF username)
    Optional:        audience (defaults to https://login.salesforce.com)

auth_config shape stored in the connector row
----------------------------------------------
{
    "grant_type": "refresh_token",        # or "client_credentials" | "password" | "salesforce_jwt"
    "token_url":  "https://...",
    "client_id":  "...",
    "client_secret": "...",
    "refresh_token": "...",               # refresh_token grant only — rotated automatically
    "scope":      "api",                  # optional space-delimited
    "audience":   "https://...",          # Adobe IMS / Salesforce JWT audience
    "subject":    "user@org.com",         # salesforce_jwt only
    "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\\n...",  # salesforce_jwt only
    "username":   "...",                  # password grant only
    "password":   "...",                  # password grant only
    "base_url":   "https://yourorg.my.salesforce.com",  # prepended to relative next URLs
}

Token caching
-------------
Tokens are cached in-process.  For refresh_token grants the cache is keyed
by integration_id (so the key stays stable across token rotation).  For all
other grants the key is a hash of the auth_config dict.

Cache entries expire 60 s before the token's stated expiry so we never
forward a stale token to an API.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

import httpx

from src.security.ssrf import check_url

_log = logging.getLogger(__name__)

# in-process cache: cache_key → {access_token, expires_at}
_TOKEN_CACHE: dict[str, dict[str, Any]] = {}

# Seconds before expiry to treat a token as stale and refresh early
_EXPIRY_BUFFER = 60


def _cache_key(auth_config: dict[str, Any], integration_id: str | None = None) -> str:
    """Stable cache key.

    For refresh_token grants keyed by integration_id so the key stays stable
    even after the refresh token rotates.  Falls back to auth_config hash.
    """
    if integration_id:
        return f"connector:{integration_id}"
    canonical = json.dumps(auth_config, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _cached_token(auth_config: dict[str, Any], integration_id: str | None = None) -> str | None:
    """Return a cached token if still valid, else None."""
    key = _cache_key(auth_config, integration_id)
    entry = _TOKEN_CACHE.get(key)
    if entry and time.time() < entry["expires_at"] - _EXPIRY_BUFFER:
        return entry["access_token"]
    return None


def _store_token(
    auth_config: dict[str, Any],
    access_token: str,
    expires_in: int,
    integration_id: str | None = None,
) -> None:
    key = _cache_key(auth_config, integration_id)
    _TOKEN_CACHE[key] = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }


def _persist_rotated_refresh_token(
    integration_id: str,
    tenant_id: str,
    new_refresh_token: str,
) -> None:
    """Write the new refresh_token back to the connector's auth_config in the DB.

    Called only when the token server returns a new refresh_token (rotation).
    Failures are logged but never propagated — a missing write is non-fatal;
    the next pull will attempt another refresh using the old token (if still
    valid) or fail with a clear error.
    """
    try:
        from src.integrations.service import get_integration, update_integration

        existing = get_integration(integration_id, tenant_id)
        if not existing:
            _log.warning("[oauth] cannot persist rotated token: connector %s not found", integration_id)
            return
        raw_auth = existing.get("auth_config") or {}
        current: dict[str, Any] = json.loads(raw_auth) if isinstance(raw_auth, str) else dict(raw_auth)
        current["refresh_token"] = new_refresh_token
        update_integration(integration_id, {"auth_config": current}, tenant_id)
        _log.info("[oauth] persisted rotated refresh_token for connector %s", integration_id)
    except Exception as exc:
        _log.error("[oauth] failed to persist rotated refresh_token for connector %s: %s", integration_id, exc)


def _fetch_refresh_token_grant(
    auth_config: dict[str, Any],
    integration_id: str | None = None,
    tenant_id: str | None = None,
) -> str:
    """Exchange a refresh token for a new access token.

    If the server returns a new refresh_token (token rotation) and both
    integration_id and tenant_id are provided, the new token is persisted
    back to the connector row automatically.
    """
    token_url = auth_config["token_url"]
    ssrf_err = check_url(token_url)
    if ssrf_err:
        raise ValueError(f"SSRF blocked token_url: {ssrf_err}")

    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": auth_config["client_id"],
        "client_secret": auth_config["client_secret"],
        "refresh_token": auth_config["refresh_token"],
    }
    if auth_config.get("scope"):
        data["scope"] = auth_config["scope"]

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        resp = client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()

    access_token = body.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in refresh_token response: {list(body.keys())}")

    expires_in = int(body.get("expires_in", 3600))
    _store_token(auth_config, access_token, expires_in, integration_id)

    # Handle token rotation: persist the new refresh_token if the server issued one
    new_refresh = body.get("refresh_token")
    if new_refresh and new_refresh != auth_config.get("refresh_token"):
        _log.info("[oauth] refresh_token rotated for connector %s", integration_id or "unknown")
        if integration_id and tenant_id:
            _persist_rotated_refresh_token(integration_id, tenant_id, new_refresh)
        else:
            _log.warning(
                "[oauth] refresh_token rotated but integration_id/tenant_id not provided "
                "— new token cannot be persisted; next pull will use the old token"
            )

    return access_token


def _fetch_client_credentials(auth_config: dict[str, Any]) -> str:
    token_url = auth_config["token_url"]
    ssrf_err = check_url(token_url)
    if ssrf_err:
        raise ValueError(f"SSRF blocked token_url: {ssrf_err}")

    data: dict[str, str] = {
        "grant_type": "client_credentials",
        "client_id": auth_config["client_id"],
        "client_secret": auth_config["client_secret"],
    }
    if auth_config.get("scope"):
        data["scope"] = auth_config["scope"]
    if auth_config.get("audience"):
        # Adobe IMS requires audience in the body
        data["audience"] = auth_config["audience"]

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        resp = client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()

    access_token = body.get("access_token") or body.get("token")
    if not access_token:
        raise ValueError(f"No access_token in OAuth response: {list(body.keys())}")

    expires_in = int(body.get("expires_in", 3600))
    _store_token(auth_config, access_token, expires_in)
    return access_token


def _fetch_password_grant(auth_config: dict[str, Any]) -> str:
    token_url = auth_config["token_url"]
    ssrf_err = check_url(token_url)
    if ssrf_err:
        raise ValueError(f"SSRF blocked token_url: {ssrf_err}")

    data: dict[str, str] = {
        "grant_type": "password",
        "client_id": auth_config["client_id"],
        "client_secret": auth_config["client_secret"],
        "username": auth_config["username"],
        "password": auth_config["password"],
    }
    if auth_config.get("scope"):
        data["scope"] = auth_config["scope"]

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        resp = client.post(token_url, data=data)
        resp.raise_for_status()
        body = resp.json()

    access_token = body.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in OAuth response: {list(body.keys())}")

    expires_in = int(body.get("expires_in", 3600))
    _store_token(auth_config, access_token, expires_in)
    return access_token


def _fetch_salesforce_jwt(auth_config: dict[str, Any]) -> str:
    """Salesforce JWT Bearer Token flow (SF Connected App with certificate).

    Generates a signed JWT assertion and exchanges it for an access token at
    the Salesforce token endpoint.  No client_secret is required — the org
    trusts the certificate uploaded to the Connected App.
    """
    try:
        import jwt as pyjwt  # PyJWT
    except ImportError:
        raise ImportError(
            "PyJWT is required for salesforce_jwt grant. "
            "Install with: pip install PyJWT cryptography"
        )

    token_url = auth_config.get("token_url", "https://login.salesforce.com/services/oauth2/token")
    ssrf_err = check_url(token_url)
    if ssrf_err:
        raise ValueError(f"SSRF blocked token_url: {ssrf_err}")

    audience = auth_config.get("audience", "https://login.salesforce.com")
    now = int(time.time())
    claims = {
        "iss": auth_config["client_id"],
        "sub": auth_config["subject"],
        "aud": audience,
        "exp": now + 300,  # 5 minutes
    }

    private_key_pem = auth_config["private_key_pem"].replace("\\n", "\n")
    assertion = pyjwt.encode(claims, private_key_pem, algorithm="RS256")

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        resp = client.post(
            token_url,
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        )
        resp.raise_for_status()
        body = resp.json()

    access_token = body.get("access_token")
    if not access_token:
        raise ValueError(f"No access_token in Salesforce JWT response: {list(body.keys())}")

    # Salesforce JWT tokens are valid for ~1 hour
    expires_in = int(body.get("expires_in", 3600))
    _store_token(auth_config, access_token, expires_in)
    return access_token


def get_token(
    auth_config: dict[str, Any],
    integration_id: str | None = None,
    tenant_id: str | None = None,
) -> str:
    """Return a valid Bearer token for auth_config, using cache if possible."""
    cached = _cached_token(auth_config, integration_id)
    if cached:
        return cached

    grant_type = auth_config.get("grant_type", "client_credentials")
    _log.info("[oauth] fetching token via grant_type=%s", grant_type)

    if grant_type == "refresh_token":
        return _fetch_refresh_token_grant(auth_config, integration_id, tenant_id)
    if grant_type == "client_credentials":
        return _fetch_client_credentials(auth_config)
    if grant_type == "password":
        return _fetch_password_grant(auth_config)
    if grant_type == "salesforce_jwt":
        return _fetch_salesforce_jwt(auth_config)

    raise ValueError(f"Unsupported OAuth grant_type: '{grant_type}'")


def resolve_headers(
    auth_config: dict[str, Any] | None,
    existing_headers: dict[str, str],
    integration_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, str]:
    """Merge an OAuth Bearer token into existing_headers if auth_config is set.

    If auth_config is empty or has no grant_type, existing_headers are
    returned unchanged (static Bearer tokens stored in config.headers still work).

    integration_id and tenant_id are forwarded to get_token so that rotated
    refresh tokens can be persisted back to the DB.

    Raises ValueError if the token fetch fails (propagates to the caller so
    the run is recorded as 'failed' rather than silently skipping auth).
    """
    if not auth_config or not auth_config.get("grant_type"):
        return existing_headers

    token = get_token(auth_config, integration_id=integration_id, tenant_id=tenant_id)
    merged = dict(existing_headers)
    merged["Authorization"] = f"Bearer {token}"
    return merged
