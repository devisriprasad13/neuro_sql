"""
OrganizationMember model.

Associates a user with an organization and assigns them a role.
This is the core of the RBAC system — it answers:
"What can this user do in this organization?"

Key constraints:
    - A user can only have ONE role per organization
     (UniqueConstraint on user_id + org_id)
    - Deleting a user cascades to delete their memberships
    - Deleting an org cascades to delete all memberships

Example:
    Alice is a DBA in Acme Corp and a Viewer in Beta Inc.
    Two rows exist:
       (alice_id, acme_id,  dba_role_id,    is_active=True)
       (alice_id, beta_id,  viewer_role_id, is_active=True)

Table: organization_members
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationMember(Base):
    """
    Membership of a user in an organization with a specific role.

    Relationships:
       user         → the platform user
       organization → the organization they belong to
       role         → their role within this organization
    """

    __tablename__ = "organization_members"

    # Table-level constraints
    #
    # UniqueConstraint ensures one user can only have one role
    # per organization. Without this, Alice could accidentally
    # be inserted as both DBA and Viewer in the same org.
    __table_args__ = (
       UniqueConstraint(
           "user_id",
           "org_id",
           name="uq_org_member_user_org",
       ),
    )

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("users.id", ondelete="CASCADE"),
       nullable=False,
       index=True,
       comment="The user who is a member of this organization.",
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("organizations.id", ondelete="CASCADE"),
       nullable=False,
       index=True,
       comment="The organization this user belongs to.",
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("roles.id", ondelete="RESTRICT"),
       nullable=False,
       comment=(
           "The role assigned to this user within this organization. "
           "RESTRICT prevents deleting a role that is in use."
       ),
    )

    # Membership status
    is_active: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment=(
           "Inactive members cannot perform operations in this org. "
           "Use this to suspend access without removing membership history."
       ),
    )

    # Timestamps
    joined_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this user was added to the organization.",
    )

    updated_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       onupdate=utcnow,
       nullable=False,
       comment="When this membership was last modified (e.g. role changed).",
    )

    # Relationships
    user: Mapped["User"] = relationship(
       "User",
       back_populates="organization_members",
    )

    organization: Mapped["Organization"] = relationship(
       "Organization",
       back_populates="members",
    )

    role: Mapped["Role"] = relationship(
       "Role",
       back_populates="organization_members",
    )

    def __repr__(self) -> str:
       return (
           f"<OrganizationMember "
           f"user={self.user_id} "
           f"org={self.org_id} "
           f"role={self.role_id} "
           f"active={self.is_active}>"
       )