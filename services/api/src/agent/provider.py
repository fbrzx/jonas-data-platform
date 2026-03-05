"""Provider client helpers for model backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.config import settings


@dataclass(frozen=True)
class ProviderClient:
    client: OpenAI
    request_overrides: dict[str, Any]


def _require(value: str, env_name: str, provider: str) -> None:
    if not value:
        raise ValueError(
            f"{env_name} must be set when LLM_PROVIDER is '{provider}'."
        )


def build_provider_client() -> ProviderClient:
    provider = settings.llm_provider.strip().lower()

    if provider == "openai":
        _require(settings.openai_api_key, "OPENAI_API_KEY", provider)
        return ProviderClient(
            client=OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
            ),
            request_overrides={},
        )

    if provider == "google":
        _require(settings.google_api_key, "GOOGLE_API_KEY", provider)
        return ProviderClient(
            client=OpenAI(
                api_key=settings.google_api_key,
                base_url=settings.google_base_url or None,
            ),
            request_overrides={},
        )

    if provider == "ollama":
        return ProviderClient(
            client=OpenAI(
                api_key=settings.ollama_api_key or "ollama",
                base_url=settings.ollama_base_url,
            ),
            request_overrides={},
        )

    raise ValueError(
        "Unsupported LLM_PROVIDER "
        f"'{settings.llm_provider}'. Use one of: openai, google, ollama."
    )
