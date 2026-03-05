"""Regression tests for agent system prompt formatting."""

from src.agent.service import _build_system_prompt


def test_build_system_prompt_allows_literal_json_examples() -> None:
    """Literal JSON examples in the template must not break str.format."""
    prompt = _build_system_prompt("tenant-acme", "viewer")

    assert '{"data": <your_payload>}' in prompt
    assert "{catalogue_context}" not in prompt
