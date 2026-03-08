"""Pydantic models for the Data Catalogue."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class FieldDefinition(BaseModel):
    name: str
    data_type: str
    nullable: bool = True
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    sample_values: list[Any] = Field(default_factory=list)


class EntityCreate(BaseModel):
    name: str
    description: str = ""
    layer: str = "bronze"  # bronze | silver | gold
    source_integration_id: UUID | None = None
    fields: list[FieldDefinition] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    collection: str | None = None


class EntityRead(EntityCreate):
    id: UUID
    tenant_id: str
    created_at: datetime
    updated_at: datetime


class EntityUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    layer: str | None = None
    fields: list[FieldDefinition] | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    collection: str | None = None
