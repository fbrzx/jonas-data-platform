"""Tests for src/security/oauth.py — token caching, grant flows, rotation, and resolve_headers."""

import asyncio
import json
import time
from unittest.mock import MagicMock, call, patch

import pytest

# ── DB fixture (needed for rotation-persistence tests) ────────────────────────


@pytest.fixture()
def _isolated_db():
    from src.db import connection as db
    from src.db.backends.local import LocalDuckDBBackend
    from src.db.init import bootstrap

    backend = LocalDuckDBBackend(":memory:")
    asyncio.get_event_loop().run_until_complete(backend.open())
    db._backend = backend
    # seed_admin_password uses jose/cryptography which is broken in this
    # test environment (pyo3 panic).  The tables it populates are not needed
    # for OAuth tests, so we stub it out.
    with patch("src.db.init.seed_admin_password"):
        bootstrap()
    yield
    asyncio.get_event_loop().run_until_complete(backend.close())
    db._backend = None


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """Empty the module-level token cache before every test."""
    from src.security import oauth

    oauth._TOKEN_CACHE.clear()
    yield
    oauth._TOKEN_CACHE.clear()


@pytest.fixture(autouse=True)
def _no_ssrf_dns(request):
    """Bypass DNS-based SSRF checks for tests that aren't specifically testing SSRF.

    The SSRF guard calls socket.gethostbyname() which fails in environments
    without external DNS.  Tests marked 'ssrf' still run the real check_url.
    """
    if "ssrf" in request.node.name:
        yield  # run the real SSRF check
        return
    with patch("src.security.ssrf.socket.gethostbyname", return_value="93.184.216.34"):
        yield


# ── Cache helpers ─────────────────────────────────────────────────────────────


def test_cache_key_uses_integration_id_when_provided():
    from src.security.oauth import _cache_key

    cfg = {"grant_type": "refresh_token", "client_id": "x"}
    assert _cache_key(cfg, "conn-123") == "connector:conn-123"


def test_cache_key_falls_back_to_hash_without_integration_id():
    from src.security.oauth import _cache_key

    cfg = {"grant_type": "client_credentials", "client_id": "x"}
    key = _cache_key(cfg, None)
    assert key != "connector:None"
    assert len(key) == 16  # sha256 hex [:16]


def test_cached_token_returns_none_when_empty():
    from src.security.oauth import _cached_token

    assert _cached_token({"grant_type": "client_credentials"}) is None


def test_store_and_retrieve_cached_token():
    from src.security.oauth import _cached_token, _store_token

    cfg = {"grant_type": "client_credentials", "client_id": "abc"}
    _store_token(cfg, "tok-123", expires_in=3600)
    assert _cached_token(cfg) == "tok-123"


def test_cached_token_returns_none_after_expiry():
    from src.security import oauth

    cfg = {"grant_type": "client_credentials", "client_id": "expiring"}
    oauth._store_token(cfg, "old-tok", expires_in=30)
    # Manually backdate the expiry so it's stale
    key = oauth._cache_key(cfg)
    oauth._TOKEN_CACHE[key]["expires_at"] = time.time() - 1
    assert oauth._cached_token(cfg) is None


def test_cached_token_respects_expiry_buffer():
    from src.security import oauth

    cfg = {"grant_type": "client_credentials", "client_id": "soon"}
    oauth._store_token(cfg, "tok", expires_in=30)
    # Within 60-second buffer → should NOT be returned
    key = oauth._cache_key(cfg)
    oauth._TOKEN_CACHE[key]["expires_at"] = time.time() + 30  # less than EXPIRY_BUFFER
    assert oauth._cached_token(cfg) is None


# ── resolve_headers ────────────────────────────────────────────────────────────


def test_resolve_headers_passthrough_when_no_auth_config():
    from src.security.oauth import resolve_headers

    headers = {"X-Custom": "value"}
    result = resolve_headers(None, headers)
    assert result == headers


def test_resolve_headers_passthrough_when_no_grant_type():
    from src.security.oauth import resolve_headers

    result = resolve_headers({}, {"Accept": "application/json"})
    assert "Authorization" not in result


def test_resolve_headers_injects_bearer():
    from src.security.oauth import resolve_headers

    cfg = {"grant_type": "client_credentials", "token_url": "https://auth.example.com/token",
           "client_id": "id", "client_secret": "secret"}

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "injected-tok", "expires_in": 3600}
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = resolve_headers(cfg, {"Accept": "application/json"})

    assert result["Authorization"] == "Bearer injected-tok"
    assert result["Accept"] == "application/json"  # existing headers preserved


# ── client_credentials grant ──────────────────────────────────────────────────


def _make_httpx_mock(token: str = "access-tok", expires_in: int = 3600,
                     extra: dict | None = None):
    body = {"access_token": token, "expires_in": expires_in}
    if extra:
        body.update(extra)
    mock_resp = MagicMock()
    mock_resp.json.return_value = body
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.post.return_value = mock_resp
    return mock_client


def test_client_credentials_returns_token():
    from src.security.oauth import _fetch_client_credentials

    cfg = {"token_url": "https://auth.example.com/token",
           "client_id": "cid", "client_secret": "csec"}

    with patch("httpx.Client", return_value=_make_httpx_mock("cc-tok")):
        token = _fetch_client_credentials(cfg)

    assert token == "cc-tok"


def test_client_credentials_sends_correct_body():
    from src.security.oauth import _fetch_client_credentials

    cfg = {"token_url": "https://auth.example.com/token",
           "client_id": "cid", "client_secret": "csec", "scope": "api"}
    mock_client = _make_httpx_mock()

    with patch("httpx.Client", return_value=mock_client):
        _fetch_client_credentials(cfg)

    _, kwargs = mock_client.post.call_args
    sent = kwargs.get("data") or mock_client.post.call_args[0][1]
    assert sent["grant_type"] == "client_credentials"
    assert sent["client_id"] == "cid"
    assert sent["client_secret"] == "csec"
    assert sent["scope"] == "api"


def test_client_credentials_with_audience():
    from src.security.oauth import _fetch_client_credentials

    cfg = {"token_url": "https://ims-na1.adobelogin.com/ims/token/v3",
           "client_id": "adobe-id", "client_secret": "adobe-sec",
           "audience": "https://ims-na1.adobelogin.com/c/adobe-id"}
    mock_client = _make_httpx_mock()

    with patch("httpx.Client", return_value=mock_client):
        _fetch_client_credentials(cfg)

    _, kwargs = mock_client.post.call_args
    sent = kwargs.get("data") or mock_client.post.call_args[0][1]
    assert sent["audience"] == "https://ims-na1.adobelogin.com/c/adobe-id"


def test_client_credentials_cached_on_second_call():
    from src.security.oauth import get_token

    cfg = {"grant_type": "client_credentials",
           "token_url": "https://auth.example.com/token",
           "client_id": "cid", "client_secret": "csec"}
    mock_client = _make_httpx_mock("cached-tok", expires_in=3600)

    with patch("httpx.Client", return_value=mock_client):
        t1 = get_token(cfg)
        t2 = get_token(cfg)

    assert t1 == t2 == "cached-tok"
    assert mock_client.post.call_count == 1  # only fetched once


# ── refresh_token grant ───────────────────────────────────────────────────────


def test_refresh_token_returns_access_token():
    from src.security.oauth import _fetch_refresh_token_grant

    cfg = {"token_url": "https://login.salesforce.com/services/oauth2/token",
           "client_id": "sf-id", "client_secret": "sf-sec",
           "refresh_token": "initial-rt"}
    mock_client = _make_httpx_mock("sf-access-tok")

    with patch("httpx.Client", return_value=mock_client):
        token = _fetch_refresh_token_grant(cfg)

    assert token == "sf-access-tok"


def test_refresh_token_sends_correct_body():
    from src.security.oauth import _fetch_refresh_token_grant

    cfg = {"token_url": "https://login.salesforce.com/services/oauth2/token",
           "client_id": "sf-id", "client_secret": "sf-sec",
           "refresh_token": "rt-value", "scope": "api"}
    mock_client = _make_httpx_mock()

    with patch("httpx.Client", return_value=mock_client):
        _fetch_refresh_token_grant(cfg)

    _, kwargs = mock_client.post.call_args
    sent = kwargs.get("data") or mock_client.post.call_args[0][1]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "rt-value"
    assert sent["client_id"] == "sf-id"
    assert sent["scope"] == "api"


def test_refresh_token_no_rotation_when_same_token():
    """No DB write when the server returns the same refresh_token."""
    from src.security.oauth import _fetch_refresh_token_grant

    cfg = {"token_url": "https://login.salesforce.com/services/oauth2/token",
           "client_id": "sf-id", "client_secret": "sf-sec",
           "refresh_token": "stable-rt"}
    mock_client = _make_httpx_mock(extra={"refresh_token": "stable-rt"})

    with patch("httpx.Client", return_value=mock_client), \
         patch("src.security.oauth._persist_rotated_refresh_token") as persist_mock:
        _fetch_refresh_token_grant(cfg, integration_id="conn-1", tenant_id="t1")

    persist_mock.assert_not_called()


def test_refresh_token_rotation_calls_persist(_isolated_db):
    """When the server returns a new refresh_token, persist is called."""
    from src.integrations.service import create_integration
    from src.security.oauth import _fetch_refresh_token_grant

    # Create a real connector so _persist_rotated_refresh_token can update it
    integration = create_integration(
        {"name": "sf_test", "connector_type": "api_pull",
         "config": {"url": "https://sf.example.com/data"},
         "auth_config": {"grant_type": "refresh_token",
                         "token_url": "https://login.salesforce.com/services/oauth2/token",
                         "client_id": "cid", "client_secret": "csec",
                         "refresh_token": "old-rt"}},
        tenant_id="tenant-a",
    )
    conn_id = str(integration["id"])

    cfg = {"grant_type": "refresh_token",
           "token_url": "https://login.salesforce.com/services/oauth2/token",
           "client_id": "cid", "client_secret": "csec", "refresh_token": "old-rt"}
    mock_client = _make_httpx_mock("new-access", extra={"refresh_token": "new-rt"})

    with patch("httpx.Client", return_value=mock_client):
        token = _fetch_refresh_token_grant(cfg, integration_id=conn_id, tenant_id="tenant-a")

    assert token == "new-access"

    # Verify the new refresh_token was persisted to the DB
    from src.integrations.service import get_integration

    updated = get_integration(conn_id, "tenant-a")
    raw_auth = updated["auth_config"]
    auth = json.loads(raw_auth) if isinstance(raw_auth, str) else raw_auth
    assert auth["refresh_token"] == "new-rt"


def test_refresh_token_rotation_logs_warning_without_ids():
    """Rotation without integration_id/tenant_id logs a warning but doesn't crash."""
    from src.security.oauth import _fetch_refresh_token_grant

    cfg = {"token_url": "https://login.salesforce.com/services/oauth2/token",
           "client_id": "cid", "client_secret": "csec", "refresh_token": "old-rt"}
    mock_client = _make_httpx_mock("access", extra={"refresh_token": "rotated-rt"})

    with patch("httpx.Client", return_value=mock_client), \
         patch("src.security.oauth._log") as mock_log:
        token = _fetch_refresh_token_grant(cfg)  # no integration_id or tenant_id

    assert token == "access"
    # A warning should have been emitted
    warning_calls = [c for c in mock_log.warning.call_args_list if "persist" in str(c).lower()]
    assert warning_calls, "expected a warning about unable to persist rotated token"


def test_refresh_token_cached_by_integration_id():
    """Cache is keyed by integration_id, so rotation doesn't bust the cache."""
    from src.security.oauth import get_token

    cfg = {"grant_type": "refresh_token",
           "token_url": "https://auth.example.com/token",
           "client_id": "cid", "client_secret": "csec", "refresh_token": "rt"}
    mock_client = _make_httpx_mock("tok-v1", expires_in=3600)

    with patch("httpx.Client", return_value=mock_client):
        t1 = get_token(cfg, integration_id="conn-42", tenant_id="t1")

    # Second call with a different cfg (simulating rotated token already in DB)
    # but same integration_id → still returns cached token
    cfg2 = {**cfg, "refresh_token": "rotated-rt"}
    with patch("httpx.Client", return_value=mock_client):
        t2 = get_token(cfg2, integration_id="conn-42", tenant_id="t1")

    assert t1 == t2 == "tok-v1"
    assert mock_client.post.call_count == 1  # only one fetch


# ── password grant ────────────────────────────────────────────────────────────


def test_password_grant_returns_token():
    from src.security.oauth import _fetch_password_grant

    cfg = {"token_url": "https://auth.example.com/token",
           "client_id": "cid", "client_secret": "csec",
           "username": "user@org.com", "password": "hunter2"}
    mock_client = _make_httpx_mock("pw-tok")

    with patch("httpx.Client", return_value=mock_client):
        token = _fetch_password_grant(cfg)

    assert token == "pw-tok"
    _, kwargs = mock_client.post.call_args
    sent = kwargs.get("data") or mock_client.post.call_args[0][1]
    assert sent["grant_type"] == "password"
    assert sent["username"] == "user@org.com"
    assert sent["password"] == "hunter2"


# ── SSRF guard ────────────────────────────────────────────────────────────────


def test_ssrf_blocks_private_token_url():
    from src.security.oauth import _fetch_client_credentials

    cfg = {"token_url": "http://192.168.1.1/token",
           "client_id": "id", "client_secret": "sec"}

    with pytest.raises(ValueError, match="SSRF"):
        _fetch_client_credentials(cfg)


def test_ssrf_blocks_loopback_token_url():
    from src.security.oauth import _fetch_refresh_token_grant

    cfg = {"token_url": "http://127.0.0.1:8080/token",
           "client_id": "id", "client_secret": "sec", "refresh_token": "rt"}

    with pytest.raises(ValueError, match="SSRF"):
        _fetch_refresh_token_grant(cfg)


# ── get_token dispatch ────────────────────────────────────────────────────────


def test_get_token_unsupported_grant_raises():
    from src.security.oauth import get_token

    with pytest.raises(ValueError, match="Unsupported OAuth grant_type"):
        get_token({"grant_type": "magic_beans",
                   "token_url": "https://auth.example.com/token"})


def test_get_token_dispatches_refresh_token():
    from src.security import oauth

    cfg = {"grant_type": "refresh_token",
           "token_url": "https://auth.example.com/token",
           "client_id": "id", "client_secret": "sec", "refresh_token": "rt"}

    with patch.object(oauth, "_fetch_refresh_token_grant", return_value="rt-dispatched") as m:
        result = oauth.get_token(cfg)

    assert result == "rt-dispatched"
    m.assert_called_once()


def test_get_token_dispatches_client_credentials():
    from src.security import oauth

    cfg = {"grant_type": "client_credentials",
           "token_url": "https://auth.example.com/token",
           "client_id": "id", "client_secret": "sec"}

    with patch.object(oauth, "_fetch_client_credentials", return_value="cc-dispatched") as m:
        result = oauth.get_token(cfg)

    assert result == "cc-dispatched"
    m.assert_called_once()


# ── land_api_pull integration ─────────────────────────────────────────────────


def test_land_api_pull_injects_oauth_bearer(_isolated_db):
    """land_api_pull calls resolve_oauth_headers and the resulting token is
    sent to the remote endpoint."""
    from src.integrations.ingest import land_api_pull

    auth_cfg = {"grant_type": "client_credentials",
                "token_url": "https://auth.example.com/token",
                "client_id": "cid", "client_secret": "csec"}

    token_resp = MagicMock()
    token_resp.json.return_value = {"access_token": "injected", "expires_in": 3600}
    token_resp.raise_for_status = MagicMock()

    data_resp = MagicMock()
    data_resp.json.return_value = [{"id": 1, "name": "Alice"}]
    data_resp.raise_for_status = MagicMock()
    data_resp.status_code = 200

    captured_headers: dict = {}

    def fake_get(url, headers=None, params=None, timeout=None, follow_redirects=None):
        captured_headers.update(headers or {})
        return data_resp

    with patch("httpx.get", side_effect=fake_get), \
         patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = token_resp
        mock_client_cls.return_value = mock_client

        result = land_api_pull(
            url="https://api.example.com/data",
            headers={},
            source="test_source",
            tenant_id="tenant-a",
            auth_config=auth_cfg,
        )

    assert result["errors"] == []
    assert result["rows_landed"] == 1
    assert captured_headers.get("Authorization") == "Bearer injected"


def test_land_api_pull_oauth_failure_records_failed_run(_isolated_db):
    """If the OAuth token fetch raises, the run is recorded as 'failed'."""
    from src.integrations.ingest import land_api_pull
    from src.integrations.service import create_integration, list_runs

    integration = create_integration(
        {"name": "bad_oauth", "connector_type": "api_pull",
         "config": {"url": "https://api.example.com/data"}},
        tenant_id="tenant-a",
    )
    conn_id = str(integration["id"])

    auth_cfg = {"grant_type": "client_credentials",
                "token_url": "http://192.168.1.1/token",  # SSRF-blocked
                "client_id": "id", "client_secret": "sec"}

    result = land_api_pull(
        url="https://api.example.com/data",
        headers={},
        source="bad_oauth",
        tenant_id="tenant-a",
        integration_id=conn_id,
        auth_config=auth_cfg,
    )

    assert result["rows_landed"] == 0
    assert any("OAuth token fetch failed" in e for e in result["errors"])

    runs = list_runs(conn_id, "tenant-a")
    assert runs, "expected a run record to be written"
    assert runs[0]["status"] == "failed"
