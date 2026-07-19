"""
SchemaSnapshot model.

Stores cached schema metadata discovered during a database crawl.
One row represents one column in one table of one connected database.

Why store this?
    The RAG pipeline needs schema context to generate accurate SQL.
    Rather than querying the target database on every NL request
    (slow, adds load, fails if DB is down), we cache schema here
    after each crawl and embed it into Pinecone.

Lifecycle:
    1. User registers a database connection
    2. User triggers POST /connections/{id}/crawl
    3. Schema crawler reads information_schema from target DB
    4. One SchemaSnapshot row is created per column
    5. Each row is embedded and stored in Pinecone
    6. pinecone_vector_id is saved back to this row
    7. NL queries retrieve relevant snapshots via Pinecone similarity search

Table: schema_snapshots
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchemaSnapshot(Base):
    """
    Cached metadata for one column in a connected database.

    Relationships:
       connection → the database this column belongs to
    """

    __tablename__ = "schema_snapshots"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Ownership
    connection_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("database_connections.id", ondelete="CASCADE"),
       nullable=False,
       index=True,
       comment="The database connection this schema belongs to.",
    )

    # Schema metadata
    #
    # One row = one column in one table.
    table_name: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       index=True,
       comment="Name of the table this column belongs to.",
    )

    table_schema: Mapped[str | None] = mapped_column(
       String(255),
       nullable=True,
       comment=(
           "Database schema/namespace. "
           "e.g. 'public' in Postgres, 'dbo' in SQL Server. "
           "NULL for databases without schemas."
       ),
    )

    column_name: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       comment="Name of the column.",
    )

    data_type: Mapped[str | None] = mapped_column(
       String(100),
       nullable=True,
       comment=(
           "Column data type as reported by the source database. "
           "e.g. 'integer', 'character varying', 'timestamp with time zone'"
       ),
    )

    # Column constraints
    is_nullable: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment="True if this column allows NULL values.",
    )

    is_primary_key: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       comment=(
           "True if this column is part of the primary key. "
           "Helps the SQL generator write correct JOIN conditions."
       ),
    )

    is_foreign_key: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       comment="True if this column references another table.",
    )

    fk_references: Mapped[str | None] = mapped_column(
       String(500),
       nullable=True,
       comment=(
           "What this foreign key references. "
           "Format: 'referenced_table.referenced_column' "
           "e.g. 'customers.id'. "
           "NULL if is_foreign_key=False."
       ),
    )

    # Embedding reference
    #
    # After this row is embedded into Pinecone, we store the
    # Pinecone vector ID here. This allows us to:
    # 1. Update the vector when schema changes
    # 2. Delete the vector when the connection is removed
    # 3. Link search results back to this database row
    pinecone_vector_id: Mapped[str | None] = mapped_column(
       String(500),
       nullable=True,
       comment=(
           "ID of this column's vector in Pinecone. "
           "Set after embedding during schema crawl. "
           "NULL means this column has not been embedded yet."
       ),
    )

    # The text that was embedded
    #
    # Storing the embedded text lets us detect when the schema
    # has changed (column renamed, type changed) without re-crawling.
    # If this text differs from what we would generate now,
    # we know a re-embed is needed.
    embedded_text: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment=(
           "The text string that was sent to the embedding model. "
           "e.g. 'orders table, customer_id column, integer, "
           "foreign key to customers.id'"
       ),
    )

    # Timestamps
    crawled_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this schema metadata was discovered.",
    )

    # Relationships
    connection: Mapped["DatabaseConnection"] = relationship(
       "DatabaseConnection",
       back_populates="schema_snapshots",
    )

    def __repr__(self) -> str:
       return (
           f"<SchemaSnapshot "
           f"table={self.table_name} "
           f"column={self.column_name} "
           f"type={self.data_type}>"
       )