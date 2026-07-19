"""
DatabaseConnection model.

Stores connection details for a user's target database.
This is NOT NeuroSQL's own metadata database — it represents
the databases that users want to query with natural language.

Security:
    - Passwords are AES-256-GCM encrypted before storage
    - Decryption happens only in the connector layer, never in API responses
    - Connection credentials are never returned to the frontend

Supported database types:
    postgres  → PostgreSQL (any version)
    mysql     → MySQL / MariaDB
    bigquery  → Google BigQuery
    snowflake → Snowflake Data Cloud

Table: database_connections
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DatabaseConnection(Base):
    """
    A registered target database connection.

    Belongs to one organization.
    Can be crawled to discover schema metadata.
    Can be queried via natural language.

    Relationships:
       organization   → the org that owns this connection
       schema_snapshots → cached column/table metadata from last crawl
       table_grants   → fine-grained table access rules for this connection
       audit_logs     → all queries executed against this connection
    """

    __tablename__ = "database_connections"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Ownership
    org_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       # ForeignKey references organizations table
       # SET NULL: if org is deleted, keep connection record but orphan it
       # In practice we use CASCADE at the org level
       nullable=False,
       index=True,
       comment="Organization that owns this database connection.",
    )

    # Who registered this connection
    created_by: Mapped[uuid.UUID | None] = mapped_column(
       UUID(as_uuid=True),
       nullable=True,
       comment="User who registered this connection. NULL if user was deleted.",
    )

    # Connection identity
    name: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       comment=(
           "Human-readable label for this connection. "
           "e.g. 'Production Sales DB', 'Analytics Warehouse'"
       ),
    )

    description: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment="Optional description of what data this database contains.",
    )

    # Database type
    #
    # Determines which connector class handles this connection.
    # The crawler and query executor read this field to
    # instantiate the correct driver.
    db_type: Mapped[str] = mapped_column(
       String(50),
       nullable=False,
       index=True,
       comment=(
           "Database engine type. "
           "One of: postgres, mysql, bigquery, snowflake"
       ),
    )

    # Connection parameters
    #
    # Standard fields for TCP/IP database connections.
    # BigQuery and Snowflake may leave some of these NULL
    # and use extra_config for their specific parameters.
    host: Mapped[str | None] = mapped_column(
       String(500),
       nullable=True,
       comment="Database server hostname or IP address.",
    )

    port: Mapped[int | None] = mapped_column(
       Integer,
       nullable=True,
       comment="Database server port. e.g. 5432 for Postgres, 3306 for MySQL",
    )

    database_name: Mapped[str | None] = mapped_column(
       String(255),
       nullable=True,
       comment="Name of the specific database/schema to connect to.",
    )

    username: Mapped[str | None] = mapped_column(
       String(255),
       nullable=True,
       comment="Database username for authentication.",
    )

    # Encrypted credentials
    #
    # The actual password is NEVER stored in plaintext.
    # We store AES-256-GCM ciphertext, base64-encoded.
    # The encryption key is in CREDENTIAL_ENCRYPTION_KEY env var.
    #
    # Decryption only happens in app/utils/crypto.py
    # when establishing a database connection.
    encrypted_password: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment=(
           "AES-256-GCM encrypted database password. "
           "Base64-encoded ciphertext. Never store plaintext here."
       ),
    )

    # Extra configuration (JSONB)
    #
    # Stores database-type-specific parameters that don't fit
    # into the standard host/port/username/password pattern.
    #
    # BigQuery:  {"project_id": "my-project", "dataset": "analytics"}
    # Snowflake: {"account": "xy12345", "warehouse": "COMPUTE_WH",
    #             "role": "SYSADMIN"}
    # Postgres:  {"ssl_mode": "require", "ssl_cert": "..."}
    #
    # JSONB is PostgreSQL's binary JSON type — faster than TEXT JSON,
    # supports indexing on nested keys, and validates JSON structure.
    extra_config: Mapped[dict | None] = mapped_column(
       JSONB,
       nullable=True,
       default=dict,
       comment="Database-type-specific connection parameters as JSON.",
    )

    # Connection status
    is_active: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment="Inactive connections cannot be queried.",
    )

    is_verified: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       comment=(
           "True if the connection has been successfully tested. "
           "Set to True after POST /connections/{id}/test succeeds."
       ),
    )

    # Schema crawl tracking
    last_crawled_at: Mapped[datetime | None] = mapped_column(
       DateTime(timezone=True),
       nullable=True,
       comment=(
           "When schema was last crawled and embedded into Pinecone. "
           "NULL means this connection has never been crawled."
       ),
    )

    crawl_status: Mapped[str | None] = mapped_column(
       String(50),
       nullable=True,
       comment=(
           "Current crawl state. "
           "One of: pending, crawling, completed, failed"
       ),
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       onupdate=utcnow,
       nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(
       "Organization",
       back_populates="database_connections",
    )

    schema_snapshots: Mapped[list["SchemaSnapshot"]] = relationship(
       "SchemaSnapshot",
       back_populates="connection",
       cascade="all, delete-orphan",
       lazy="select",
    )

    table_grants: Mapped[list["TableGrant"]] = relationship(
       "TableGrant",
       back_populates="connection",
       cascade="all, delete-orphan",
       lazy="select",
    )

    def __repr__(self) -> str:
       return (
           f"<DatabaseConnection "
           f"id={self.id} "
           f"name={self.name!r} "
           f"type={self.db_type} "
           f"verified={self.is_verified}>"
       )