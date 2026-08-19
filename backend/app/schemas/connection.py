"""
Pydantic schemas for database connection API endpoints.

Request schemas:  what the frontend sends
Response schemas: what the API returns
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ #
# Supported database types
# ------------------------------------------------------------------ #
DBType = Literal["postgres", "mysql", "bigquery", "snowflake"]


# ------------------------------------------------------------------ #
# Request schemas
# ------------------------------------------------------------------ #

class ConnectionCreateRequest(BaseModel):
    """Request body for POST /api/v1/connections."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable label for this connection.",
        examples=["Production Sales DB", "Analytics Warehouse"],
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional description of what data this database contains.",
    )

    db_type: DBType = Field(
        ...,
        description="Database engine type.",
    )

    host: str | None = Field(
        default=None,
        max_length=500,
        description="Database server hostname or IP. Not required for BigQuery.",
    )

    port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Database server port.",
    )

    database_name: str | None = Field(
        default=None,
        max_length=255,
        description="Name of the specific database/schema to connect to.",
    )

    username: str | None = Field(
        default=None,
        max_length=255,
        description="Database username for authentication.",
    )

    password: str | None = Field(
        default=None,
        max_length=1000,
        description="Database password. Stored encrypted — never returned in responses.",
    )

    extra_config: dict = Field(
        default_factory=dict,
        description=(
            "Database-type-specific parameters. "
            "BigQuery: {project_id, dataset}. "
            "Snowflake: {account, warehouse, role}."
        ),
    )

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("db_type")
    @classmethod
    def validate_db_type(cls, v: str) -> str:
        return v.lower()


class ConnectionTestRequest(BaseModel):
    """Optional request body for POST /api/v1/connections/{id}/test."""
    pass


# ------------------------------------------------------------------ #
# Response schemas
# ------------------------------------------------------------------ #

class ConnectionResponse(BaseModel):
    """
    Single connection in API responses.
    Never includes password or encrypted_password.
    """

    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    db_type: str
    host: str | None
    port: int | None
    database_name: str | None
    username: str | None
    is_active: bool
    is_verified: bool
    crawl_status: str | None
    last_crawled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConnectionListResponse(BaseModel):
    """Response for GET /api/v1/connections."""
    connections: list[ConnectionResponse]
    total: int


class ConnectionTestResponse(BaseModel):
    """Response for POST /api/v1/connections/{id}/test."""
    connection_id: uuid.UUID
    is_reachable: bool
    message: str
    latency_ms: float | None = None


class CrawlResponse(BaseModel):
    """Response for POST /api/v1/connections/{id}/crawl."""
    connection_id: uuid.UUID
    table_count: int
    column_count: int
    embedded_count: int
    status: str
    error: str | None = None