"""
Models package.

Importing this package registers all SQLAlchemy models
with Base.metadata, making them visible to Alembic
for migration generation.

Import order matters — models with no foreign keys first,
then models that depend on them.
"""

from app.models.user import User
from app.models.organization import Organization
from app.models.role import Role
from app.models.permission import Permission
from app.models.role_permission import RolePermission
from app.models.organization_member import OrganizationMember
from app.models.database_connection import DatabaseConnection
from app.models.schema_snapshot import SchemaSnapshot
from app.models.table_grant import TableGrant
from app.models.pending_operation import PendingOperation
from app.models.audit_log import AuditLog
from app.models.refresh_token import RefreshToken

__all__ = [
    "User",
    "Organization",
    "Role",
    "Permission",
    "RolePermission",
    "OrganizationMember",
    "DatabaseConnection",
    "SchemaSnapshot",
    "TableGrant",
    "PendingOperation",
    "AuditLog",
    "RefreshToken",
]