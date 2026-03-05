"""Pydantic models for Transforms."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TransformCreate(BaseModel):
    name: str
    description: str = ""
    source_layer: str = "bronze"
    target_layer: str = "silver"
    sql: str
    tags: list[str] = Field(default_factory=list)


class TransformRead(TransformCreate):
    id: UUID
    tenant_id: str
    status: str  # draft | pending_approval | approved | rejected
    created_by: str | None = None
    approved_by: str | None = None
    created_at: datetime
    updated_at: datetime


class TransformExecuteResponse(BaseModel):
    transform_id: UUID
    rows_affected: int
    duration_ms: float
    target_table: str
    executed_at: datetime
    errors: list[str] = Field(default_factory=list)


class TransformUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sql: str | None = None           # only respected when status=draft
    source_layer: str | None = None  # only respected when status=draft
    target_layer: str | None = None  # only respected when status=draft
    tags: list[str] | None = None


class ApprovalAction(BaseModel):
    action: str  # approve | reject
    comment: str = ""
    reviewer_id: str | None = None
