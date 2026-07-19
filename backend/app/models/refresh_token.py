"""
RefreshToken model.

Stores hashed refresh tokens for JWT session management.

Why store refresh tokens?
    JWTs are stateless — a stolen access token works until expiry.
    Refresh tokens give us revocation capability:
       - Logout invalidates the refresh token immediately
       - Password change invalidates ALL refresh tokens for that user
       - Suspicious activity detection can revoke specific tokens
       - Users can see and manage all active sessions

Security:
    - We store token_hash (bcrypt), never the raw token
    - Raw token is returned once at login, never stored
    - Even a full DB dump yields no usable tokens

Multi-device support:
    One user can have multiple active refresh tokens —
    one per logged-in device. Each gets its own row.

Table: refresh_tokens
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RefreshToken(Base):
    """
    A hashed refresh token for one user session on one device.

    Relationships:
       user → the user this token belongs to
    """

    __tablename__ = "refresh_tokens"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
    )

    # Ownership
    user_id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       ForeignKey("users.id", ondelete="CASCADE"),
       nullable=False,
       index=True,
       comment=(
           "User this token belongs to. "
           "CASCADE: deleting a user deletes all their tokens."
       ),
    )

    # Token storage
    #
    # NEVER store the raw token.
    # Store only the bcrypt hash.
    # The raw token is returned to the client once at login.
    # On subsequent requests, we hash the incoming token and
    # compare against this stored hash.
    token_hash: Mapped[str] = mapped_column(
       String(500),
       nullable=False,
       comment=(
           "bcrypt hash of the refresh token. "
           "Compare with bcrypt.verify(incoming_token, token_hash). "
           "Never store the raw token value."
       ),
    )

    # Device information (optional)
    #
    # Allows users to see which devices are logged in
    # and selectively revoke sessions.
    device_info: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment=(
           "Human-readable device description from User-Agent header. "
           "e.g. 'Chrome on Windows', 'Safari on iPhone'. "
           "Shown in the 'Active Sessions' UI."
       ),
    )

    ip_address: Mapped[str | None] = mapped_column(
       String(45),
       nullable=True,
       comment=(
           "IP address when this token was issued. "
           "IPv4 max 15 chars, IPv6 max 45 chars. "
           "Used for suspicious activity detection."
       ),
    )

    # Token lifecycle
    is_revoked: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       index=True,
       comment=(
           "True if this token has been explicitly revoked. "
           "Revoked tokens are rejected even before expiry. "
           "We keep the row for audit purposes."
       ),
    )

    expires_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       nullable=False,
       comment=(
           "When this token expires. "
           "Default: 7 days after creation. "
           "Expired tokens are rejected regardless of is_revoked."
       ),
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
       comment="When this token was issued (user logged in).",
    )

    last_used_at: Mapped[datetime | None] = mapped_column(
       DateTime(timezone=True),
       nullable=True,
       comment=(
           "When this token was last used to get a new access token. "
           "Updated on every successful token refresh. "
           "Used to detect inactive sessions."
       ),
    )

    revoked_at: Mapped[datetime | None] = mapped_column(
       DateTime(timezone=True),
       nullable=True,
       comment="When this token was revoked. NULL if still active.",
    )

    # Relationships
    user: Mapped["User"] = relationship(
       "User",
       back_populates="refresh_tokens",
    )

    def __repr__(self) -> str:
       return (
           f"<RefreshToken "
           f"id={self.id} "
           f"user={self.user_id} "
           f"revoked={self.is_revoked} "
           f"expires={self.expires_at}>"
       )