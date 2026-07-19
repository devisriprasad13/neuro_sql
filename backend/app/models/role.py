"""
Role model.

Defines the five platform roles for NeuroSQL RBAC.
Roles are platform-defined — users cannot create custom roles.

The five roles in order of privilege (highest to lowest):
    super_admin  → full platform access, manages all organizations
    org_admin    → manages one organization, all operations within it
    dba          → full SQL access including schema operations
    analyst      → SELECT + export, no write operations
    viewer       → SELECT only, no export

Roles are seeded into the database on first boot.
They are never created or modified by user actions.

Table: roles
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    """
    A platform-defined role.

    Relationships:
       role_permissions     → permissions granted to this role
       organization_members → users assigned this role
    """

    __tablename__ = "roles"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Role identity
    name: Mapped[str] = mapped_column(
       String(50),
       unique=True,
       nullable=False,
       index=True,
       comment=(
           "Machine-readable role identifier. "
           "One of: super_admin, org_admin, dba, analyst, viewer. "
           "Used in permission checks throughout the codebase."
       ),
    )

    display_name: Mapped[str] = mapped_column(
       String(100),
       nullable=False,
       comment="Human-readable name shown in the UI. e.g. 'Database Administrator'",
    )

    description: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment="Explains what this role can and cannot do.",
    )

    # System role flag
    #
    # System roles cannot be deleted via the API.
    # This prevents accidental deletion of built-in roles
    # which would break the permission system.
    is_system_role: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment=(
           "If True, this role cannot be deleted. "
           "All five platform roles are system roles."
       ),
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
    )

    # Relationships
 
    # Permissions granted to this role
    role_permissions: Mapped[list["RolePermission"]] = relationship(
       "RolePermission",
       back_populates="role",
       cascade="all, delete-orphan",
       lazy="select",
    )

    # Users assigned this role (within an organization)
    organization_members: Mapped[list["OrganizationMember"]] = relationship(
       "OrganizationMember",
       back_populates="role",
       lazy="select",
    )

    def __repr__(self) -> str:
       return f"<Role id={self.id} name={self.name}>"