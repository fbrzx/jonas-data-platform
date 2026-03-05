"""Regression tests for OpenAPI auth metadata."""

from src.main import app


def test_openapi_exposes_http_bearer_security_scheme() -> None:
    schema = app.openapi()

    security_schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "HTTPBearer" in security_schemes
    assert security_schemes["HTTPBearer"]["type"] == "http"
    assert security_schemes["HTTPBearer"]["scheme"] == "bearer"


def test_openapi_marks_agent_chat_as_bearer_protected() -> None:
    schema = app.openapi()

    operation = schema["paths"]["/api/v1/agent/chat"]["post"]
    assert {"HTTPBearer": []} in operation.get("security", [])
