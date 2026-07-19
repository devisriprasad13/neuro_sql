"""
Permission model.

Represents an atomic action that can be granted to a role.
Permissions are the building blocks of RBAC.

Every permission answers: "Can operation X be done on resource Y?"

Examples:
    operation=SELECT,   resource_type=table       → read table data
    operation=INSERT,   resource_type=table       → insert rows
    operation=DELETE,   resource_type=table       → delete rows
    operation=EXPORT,   resource_type=table       → export query results
    operation=MANAGE,   resource_type=connection  → register/delete DB connections
    operation=VIEW,     resource_type=audit_log   → read audit history

Permissions are seeded on first boot and never modified by users.

Table: permissions
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ #
# Permission constants
#
# These string constants are used throughout the codebase
# when checking permissions. Centralizing them here prevents
# typos like "SELCT" causing silent permission failures.
# ------------------------------------------------------------------ #

class OperationType:
    """SQL and platform operation types."""
    SELECT   = "SELECT"
    INSERT   = "INSERT"
    UPDATE   = "UPDATE"
    DELETE   = "DELETE"
    CREATE   = "CREATE"
    ALTER    = "ALTER"
    DROP     = "DROP"
    TRUNCATE = "TRUNCATE"
    EXPORT   = "EXPORT"
    MANAGE   = "MANAGE"   # Register/delete connections, manage org settings
    VIEW     = "VIEW"     # View audit logs, metrics


class ResourceType:
    """Resource types that permissions apply to."""
    TABLE        = "table"
    CONNECTION   = "connection"
    ORGANIZATION = "organization"
    AUDIT_LOG    = "audit_log"
    USER         = "user"


class GateType:
    """
    Types of gates for sensitive operations.

    CONFIRMATION: user must explicitly confirm before execution
                 e.g. "Type CONFIRM to delete 4,820 rows"

    APPROVAL:     a higher-privilege user must approve before execution
                 e.g. org_admin must approve a bulk DELETE by a DBA
    """
    CONFIRMATION = "confirmation"
    APPROVAL     = "approval"


class Permission(Base):
    """
    An atomic action that can be granted to a role.

    Relationships:
       role_permissions → roles that have been granted this permission
    """

    __tablename__ = "permissions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
       UUID(as_uuid=True),
       primary_key=True,
       default=uuid.uuid4,
        
    )

    # Permission definition
    operation: Mapped[str] = mapped_column(
       String(50),
       nullable=False,
       comment=(
           "The action being permitted. "
           "One of: SELECT, INSERT, UPDATE, DELETE, CREATE, "
           "ALTER, DROP, TRUNCATE, EXPORT, MANAGE, VIEW"
       ),
    )

    resource_type: Mapped[str] = mapped_column(
       String(50),
       nullable=False,
       comment=(
           "What the operation applies to. "
           "One of: table, connection, organization, audit_log, user"
       ),
    )

    description: Mapped[str | None] = mapped_column(
       Text,
       nullable=True,
       comment="Human-readable explanation of what this permission allows.",
    )

    # Gate configuration
    #
    # Some operations are permitted but require an extra step
    # before execution. This is the '⚠' in our permission matrix.
    #
    # requires_gate=False → execute immediately
    # requires_gate=True  → pause and require confirmation or approval
    requires_gate: Mapped[bool] = mapped_column(
       Boolean,
       default=False,
       nullable=False,
       comment=(
           "If True, this operation cannot execute immediately. "
           "User must confirm or an admin must approve first."
       ),
    )

    gate_type: Mapped[str | None] = mapped_column(
       String(50),
       nullable=True,
       comment=(
           "Type of gate required when requires_gate=True. "
           "One of: confirmation, approval. NULL when requires_gate=False."
       ),
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
       DateTime(timezone=True),
       default=utcnow,
       nullable=False,
    )

    # Relationships
 
    # Roles that have been granted this permission
    role_permissions: Mapped[list["RolePermission"]] = relationship(
       "RolePermission",
       back_populates="permission",
       cascade="all, delete-orphan",
       lazy="select",
    )

    def __repr__(self) -> str:
       gate = f" [{self.gate_type}]" if self.requires_gate else ""
       return (
           f"<Permission {self.operation} on {self.resource_type}{gate}>"
       )