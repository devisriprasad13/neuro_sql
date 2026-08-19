"""
Pydantic schemas for query-related API endpoints.

These define the shape of HTTP request bodies and response payloads.
Completely separate from SQLAlchemy models — these are API contracts.

Request schemas:  what the frontend sends to the API
Response schemas: what the API sends back to the frontend
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ #
# Request schemas
# ------------------------------------------------------------------ #

class QueryRequest(BaseModel):
    """
    Request body for POST /api/v1/query.

    The frontend sends this when a user submits a natural language query.
    """

    natural_language_query: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The user's natural language question.",
        examples=["Show me total revenue by customer region for Q1 2024"],
    )

    connection_id: uuid.UUID = Field(
        ...,
        description="UUID of the registered database connection to query.",
    )

    skip_dry_run: bool = Field(
        default=False,
        description="Skip Stage 3 EXPLAIN validation. Only use for testing.",
    )

    @field_validator("natural_language_query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        """Remove leading/trailing whitespace from the query."""
        return v.strip()


# ------------------------------------------------------------------ #
# Response schemas
# ------------------------------------------------------------------ #

class QueryResponse(BaseModel):
    """
    Response body for POST /api/v1/query and GET /api/v1/query/{id}.

    Contains the generated SQL, execution results, and metadata.
    """

    success: bool = Field(description="True if query produced results successfully.")

    sql: str = Field(
        default="",
        description="The final validated SQL that was generated and executed.",
    )

    columns: list[str] = Field(
        default_factory=list,
        description="Column names in the result set.",
    )

    rows: list[list] = Field(
        default_factory=list,
        description="Result rows. Each row is a list of values matching columns.",
    )

    row_count: int = Field(
        default=0,
        description="Number of rows returned (SELECT) or affected (write operations).",
    )

    affected_rows: int = Field(
        default=0,
        description="Rows modified for INSERT/UPDATE/DELETE operations.",
    )

    execution_time_ms: float = Field(
        default=0.0,
        description="Total pipeline time from query receipt to result delivery.",
    )

    was_corrected: bool = Field(
        default=False,
        description="True if self-correction was triggered during SQL generation.",
    )

    correction_attempts: int = Field(
        default=1,
        description="Number of SQL generation attempts made (1 = first try succeeded).",
    )

    intent: str = Field(
        default="READ",
        description="Classified SQL operation type: READ, INSERT, UPDATE, DELETE, DDL.",
    )

    error: str | None = Field(
        default=None,
        description="Error message if success=False. None if success=True.",
    )

    audit_log_id: str | None = Field(
        default=None,
        description="UUID of the audit log entry created for this query.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "sql": "SELECT id, email, full_name FROM users WHERE is_active = TRUE;",
                "columns": ["id", "email", "full_name"],
                "rows": [
                    ["uuid-1", "alice@example.com", "Alice Smith"],
                    ["uuid-2", "bob@example.com", "Bob Jones"],
                ],
                "row_count": 2,
                "affected_rows": 0,
                "execution_time_ms": 842.5,
                "was_corrected": False,
                "correction_attempts": 1,
                "intent": "READ",
                "error": None,
                "audit_log_id": "uuid-of-audit-log",
            }
        }


class QueryHistoryItem(BaseModel):
    """Single item in the query history list."""

    id: uuid.UUID
    natural_language_query: str
    generated_sql: str | None
    intent_classification: str | None
    status: str
    execution_time_ms: int | None
    result_row_count: int | None
    was_self_corrected: bool
    correction_attempts: int
    requested_at: datetime
    connection_name: str | None

    class Config:
        from_attributes = True


class QueryHistoryResponse(BaseModel):
    """Response for GET /api/v1/query/history."""

    items: list[QueryHistoryItem]
    total: int
    page: int
    page_size: int