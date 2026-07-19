"""
Organization model.

The multi-tenancy boundary for NeuroSQL.
Every resource — database connections, audit logs, user memberships —
belongs to exactly one organization.

A user can belong to multiple organizations with different roles.
Example: a consultant who is a DBA in org A and a viewer in org B.

Table: organizations
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Organization(Base):
    """
    A tenant organization on the NeuroSQL platform.

    Relationships:
       members             → users belonging to this organization
       database_connections → target databases registered by this org
       audit_logs          → all operations performed within this org
       pending_operations  → gated operations awaiting approval
       table_grants        → fine-grained table access rules
    """

    __tablename__ = "organizations"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Identity fields
    name: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       comment="Display name of the organization. e.g. 'Acme Corp'",
    )

    slug: Mapped[str] = mapped_column(
       String(100),
       unique=True,
       nullable=False,
       index=True,
       comment=(
           "URL-safe unique identifier. e.g. 'acme-corp'. "
           "Used in API paths and for quick lookups."
       ),
    )

    description: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment="Optional description of the organization.",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment=(
           "Inactive organizations cannot perform queries. "
           "Use this to suspend an org without deleting its data."
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
 
    # Users who belong to this organization
    members: Mapped[list["OrganizationMember"]] = relationship(
       "OrganizationMember",
       back_populates="organization",
       cascade="all, delete-orphan",
       lazy="select",
    )

    # Target databases registered under this organization
    database_connections: Mapped[list["DatabaseConnection"]] = relationship(
       "DatabaseConnection",
       back_populates="organization",
       cascade="all, delete-orphan",
       lazy="select",
    )

    # All audit log entries for this organization
    audit_logs: Mapped[list["AuditLog"]] = relationship(
       "AuditLog",
       back_populates="organization",
       lazy="select",
    )

    # Pending operations (gated writes awaiting approval)
    pending_operations: Mapped[list["PendingOperation"]] = relationship(
       "PendingOperation",
       back_populates="organization",
       cascade="all, delete-orphan",
       lazy="select",
    )

    def __repr__(self) -> str:
       return f"<Organization id={self.id} slug={self.slug}>"