"""Pydantic models for Integrations."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IntegrationCreate(BaseModel):
    name: str
    description: str = ""
    connector_type: str  # webhook | batch_csv | batch_json | ...
    config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    entity_id: str | None = None  # links to catalogue.entity; source name is derived from entity.name


class IntegrationRead(IntegrationCreate):
    id: UUID
    tenant_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class WebhookPayload(BaseModel):
    source: str
    data: dict[str, Any] | list[Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class LinkedWebhookPayload(BaseModel):
    """Payload for the per-integration webhook — source is derived from the integration."""

    data: dict[str, Any] | list[Any]
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchIngestResponse(BaseModel):
    rows_received: int
    rows_landed: int
    target_table: str
    errors: list[str] = Field(default_factory=list)
