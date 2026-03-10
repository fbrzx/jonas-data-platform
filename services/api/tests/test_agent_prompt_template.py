"""Regression tests for agent system prompt formatting."""

from src.agent.prompt import build_system_prompt


def test_build_system_prompt_allows_literal_json_examples() -> None:
    """Literal JSON examples in the template must not break str.format."""
    prompt = build_system_prompt("tenant-acme", "viewer")

    # Literal JSON examples with double-braces must survive str.format()
    assert '"strategy": "offset' in prompt or "smart_import" in prompt
    assert "{catalogue_context}" not in prompt
