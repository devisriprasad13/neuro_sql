"""
TableGrant model.

Provides fine-grained table-level access control that overrides
role-level defaults for specific users.

Three possible states for a user+table+operation combination:
    1. No row exists       → use role default (role_permissions table)
    2. Row, is_granted=True  → explicitly allowed, overrides role default
    3. Row, is_granted=False → explicitly DENIED, overrides role default

Rule: explicit deny (is_granted=False) always wins over role-level allow.

This is the same model used by AWS IAM:
    - Identity policy (role) allows S3:GetObject
    - Resource policy (table grant) denies S3:GetObject
    - Result: DENIED

Use cases:
    - Contractor DBA can INSERT to products but not orders
    - Analyst can SELECT from sales but not from hr_salaries
    - Viewer is granted EXPORT for a specific reporting table

Table: table_grants
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TableGrant(Base):
    """
    An explicit allow or deny for a user on a specific table operation.

    Relationships:
       connection → the database containing the target table
    """

    __tablename__ = "table_grants"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Subject — who this grant applies to
    user_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       nullable=False,
       index=True,
       comment="The user this grant applies to.",
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       nullable=False,
       index=True,
       comment="Organization context for this grant.",
    )

    # Resource — what this grant applies to
    connection_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("database_connections.id", ondelete="CASCADE"),
       nullable=False,
       index=True,
       comment="The database connection containing the target table.",
    )

    table_name: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       comment=(
           "The specific table this grant applies to. "
           "Use '*' to apply to all tables in the connection."
       ),
    )

    # Operation — what action this grant covers
    operation: Mapped[str] = mapped_column(
       String(50),
       nullable=False,
       comment=(
           "The SQL operation this grant covers. "
           "One of: SELECT, INSERT, UPDATE, DELETE, EXPORT"
       ),
    )

    # Grant decision
    #
    # True  → explicitly ALLOW this operation on this table
    # False → explicitly DENY this operation on this table
    #
    # Why store explicit denies instead of just deleting the row?
    # Because "no row" means "no policy — use role default"
    # while "row with is_granted=False" means "denied even if
    # the role would normally allow it."
    # Explicit deny always overrides role-level allow.
    is_granted: Mapped[bool] = mapped_column(
       Boolean,
       nullable=False,
       comment=(
           "True = explicitly allowed. False = explicitly denied. "
           "Explicit deny overrides role-level permissions."
       ),
    )

    # Audit fields — who set this grant and when
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
       UUID(as_uuid=True),
       nullable=True,
       comment="User (org_admin or super_admin) who created this grant.",
    )

    granted_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this grant was created.",
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
       DateTime(timezone=True),
       nullable=True,
       comment=(
           "When this grant was revoked. "
           "NULL means still active. "
           "We keep the row for audit history — "
           "setting is_granted=False is the revocation."
       ),
    )

    # Relationships
    connection: Mapped["DatabaseConnection"] = relationship(
       "DatabaseConnection",
       back_populates="table_grants",
    )

    def __repr__(self) -> str:
       action = "ALLOW" if self.is_granted else "DENY"
       return (
           f"<TableGrant {action} "
           f"user={self.user_id} "
           f"{self.operation} on {self.table_name}>"
       )