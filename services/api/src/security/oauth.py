"""OAuth 2.0 token management for api_pull connector auth_config.

Supported grant types
---------------------
client_credentials
    Standard M2M flow.  Used by Salesforce Connected Apps and Adobe IMS.
    Required fields: token_url, client_id, client_secret
    Optional:        scope, audience (Adobe)

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
    "grant_type": "client_credentials",   # or "password" | "salesforce_jwt"
    "token_url":  "https://...",
    "client_id":  "...",
    "client_secret": "...",
    "scope":      "api",                  # optional space-delimited
    "audience":   "https://...",          # Adobe IMS / Salesforce JWT audience
    "subject":    "user@org.com",         # salesforce_jwt only
    "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\\n...",  # salesforce_jwt only
    "username":   "...",                  # password grant only
    "password":   "...",                  # password grant only
    "base_url":   "https://yourorg.my.salesforce.com",  # prepended to relative next URLs
}

Tokens are cached in-process (keyed by a hash of auth_config).
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


def _cache_key(auth_config: dict[str, Any]) -> str:
    """Stable hash of the auth_config to use as cache key."""
    canonical = json.dumps(auth_config, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _cached_token(auth_config: dict[str, Any]) -> str | None:
    """Return a cached token if still valid, else None."""
    key = _cache_key(auth_config)
    entry = _TOKEN_CACHE.get(key)
    if entry and time.time() < entry["expires_at"] - _EXPIRY_BUFFER:
        return entry["access_token"]
    return None


def _store_token(auth_config: dict[str, Any], access_token: str, expires_in: int) -> None:
    key = _cache_key(auth_config)
    _TOKEN_CACHE[key] = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in,
    }


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


def get_token(auth_config: dict[str, Any]) -> str:
    """Return a valid Bearer token for auth_config, using cache if possible."""
    cached = _cached_token(auth_config)
    if cached:
        return cached

    grant_type = auth_config.get("grant_type", "client_credentials")
    _log.info("[oauth] fetching token via grant_type=%s", grant_type)

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
) -> dict[str, str]:
    """Merge an OAuth Bearer token into existing_headers if auth_config is set.

    If auth_config is empty or has no grant_type, existing_headers are
    returned unchanged (static Bearer tokens stored in config.headers still work).

    Raises ValueError if the token fetch fails (propagates to the caller so
    the run is recorded as 'failed' rather than silently skipping auth).
    """
    if not auth_config or not auth_config.get("grant_type"):
        return existing_headers

    token = get_token(auth_config)
    merged = dict(existing_headers)
    merged["Authorization"] = f"Bearer {token}"
    return merged
