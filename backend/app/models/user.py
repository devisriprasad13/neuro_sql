"""
User model.

Represents a NeuroSQL platform account.
One user can belong to multiple organizations with different roles
(via the organization_members table).

Table: users
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    """
    Return current UTC time with timezone info.

    We define this as a function rather than using datetime.utcnow()
    because datetime.utcnow() is deprecated in Python 3.12+.
    Using timezone-aware datetimes prevents bugs when comparing
    timestamps across different timezones.
    """
    return datetime.now(timezone.utc)


class User(Base):
    """
    Platform user account.

    A user authenticates with email + password and receives a JWT.
    Their permissions are determined by their role within each
    organization they belong to (see OrganizationMember model).

    Relationships:
       organization_members → organizations this user belongs to
       refresh_tokens       → active JWT refresh tokens
       query_history        → queries submitted by this user (via audit_logs)
    """

    __tablename__ = "users"

    # Primary key
    #
    # We use UUID instead of auto-increment integer because:
    # 1. UUIDs are globally unique — safe to merge across databases
    # 2. They don't expose sequential resource counts to attackers
    # 3. They can be generated client-side without a DB round-trip
    #
    # default=uuid.uuid4 generates it in Python if inserted without a DB.
    # We provide both so the model works in all contexts.
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
    )

    # Identity fields
    email: Mapped[str] = mapped_column(
       String(255),
       unique=True,
       nullable=False,
       index=True,  # Index speeds up login lookups by email
       comment="Primary login identifier. Must be unique across platform.",
    )

    password_hash: Mapped[str] = mapped_column(
       String(255),
       nullable=False,
       comment="bcrypt hash of the user's password. Never store plaintext.",
    )

    full_name: Mapped[str | None] = mapped_column(
       String(255),
       nullable=True,
       comment="Display name shown in the UI.",
    )

    # Account status
    is_active: Mapped[bool] = mapped_column(
       Boolean,
       default=True,
       nullable=False,
       comment="Inactive users cannot log in. Use this instead of deleting accounts.",
    )

    is_verified: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       comment="Email verification status. Reserved for future email verification flow.",
    )

    # Timestamps
    #
    # We store all timestamps in UTC with timezone info.
    # This prevents bugs when your server moves regions or
    # when users are in different timezones.
    created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this account was created.",
    )

    updated_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       onupdate=utcnow,  # Automatically updates when any field changes
       nullable=False,
       comment="When this account was last modified.",
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
       DateTime(timezone=True),
       nullable=True,
       comment="When this user last successfully authenticated.",
    )

    # Relationships
    #
    # These define how User connects to other models.
    # SQLAlchemy uses these to generate JOIN queries automatically.
    #
    # back_populates: tells SQLAlchemy about the reverse relationship
    # lazy="select": loads related objects only when accessed
    # cascade="all, delete-orphan": deleting a user deletes their tokens
 
    # A user can belong to many organizations
    organization_members: Mapped[list["OrganizationMember"]] = relationship(
       "OrganizationMember",
       back_populates="user",
       cascade="all, delete-orphan",
       lazy="select",
    )

    # A user can have multiple active refresh tokens
    # (logged in from multiple devices simultaneously)
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
       "RefreshToken",
       back_populates="user",
       cascade="all, delete-orphan",
       lazy="select",
    )

    # Python representation
    def __repr__(self) -> str:
       return f"<User id={self.id} email={self.email} active={self.is_active}>"