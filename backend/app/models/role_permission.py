"""
RolePermission model — junction table between roles and permissions.

Implements the many-to-many relationship:
    A role can have many permissions.
    A permission can be granted to many roles.

This table is seeded on first boot with the complete permission
matrix defined in our Milestone 0 specification.

Example rows:
    (dba_role_id,     select_table_permission_id)
    (dba_role_id,     insert_table_permission_id)
    (analyst_role_id, select_table_permission_id)
    (viewer_role_id,  select_table_permission_id)

Table: role_permissions
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RolePermission(Base):
    """
    Associates a permission with a role.

    Composite primary key: (role_id, permission_id)
    This enforces that the same permission cannot be granted
    to the same role twice.
    """

    __tablename__ = "role_permissions"

    # Composite primary key
    #
    # Both columns together form the primary key.
    # This means:
    #   - (dba, SELECT) can exist once
    #   - (analyst, SELECT) can also exist
    #   - (dba, SELECT) cannot be inserted twice
    role_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("roles.id", ondelete="CASCADE"),
       primary_key=True,
       comment="The role being granted this permission.",
    )

    permission_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("permissions.id", ondelete="CASCADE"),
       primary_key=True,
       comment="The permission being granted to this role.",
    )

    # Audit field
    # When was this permission granted to this role?
    granted_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this permission was granted to this role.",
    )

    # Relationships
    role: Mapped["Role"] = relationship(
       "Role",
       back_populates="role_permissions",
    )

    permission: Mapped["Permission"] = relationship(
       "Permission",
       back_populates="role_permissions",
    )

    def __repr__(self) -> str:
       return (
           f"<RolePermission role={self.role_id} "
           f"permission={self.permission_id}>"
       )