"""
Permission registry — in-memory cache of role→permission mappings.

Loads the complete RBAC permission matrix at startup.
Every permission check is an O(1) dictionary lookup.

Why in-memory instead of DB query per request?
    The permission matrix is static — it never changes at runtime.
    Loading it once at startup eliminates 4-table DB joins per request.
    At 100 req/sec, this saves ~400 unnecessary DB queries per second.

Structure:
    PERMISSION_MATRIX[role_name][operation] = PermissionRule

Where PermissionRule defines:
    - allowed: bool
    - requires_gate: bool
    - gate_type: 'confirmation' | 'approval' | None
"""

from dataclasses import dataclass
from enum import Enum


class OperationType(str, Enum):
    """All SQL and platform operation types."""
    SELECT   = "SELECT"
    INSERT   = "INSERT"
    UPDATE   = "UPDATE"
    DELETE   = "DELETE"
    CREATE   = "CREATE"
    ALTER    = "ALTER"
    DROP     = "DROP"
    TRUNCATE = "TRUNCATE"
    EXPORT   = "EXPORT"
    MANAGE   = "MANAGE"    # Register/delete connections
    VIEW     = "VIEW"      # View audit logs


class GateType(str, Enum):
    """Gate types for sensitive operations."""
    CONFIRMATION = "confirmation"   # User re-submits with token
    APPROVAL     = "approval"       # Admin must approve


class RoleName(str, Enum):
    """The 5 platform-defined roles."""
    SUPER_ADMIN = "super_admin"
    ORG_ADMIN   = "org_admin"
    DBA         = "dba"
    ANALYST     = "analyst"
    VIEWER      = "viewer"


@dataclass
class PermissionRule:
    """
    Rule for one (role, operation) combination.

    Attributes:
        allowed:       True if this role can perform this operation.
        requires_gate: True if an extra confirmation/approval step is needed.
        gate_type:     Type of gate (confirmation or approval). None if no gate.
        description:   Human-readable description for error messages.
    """
    allowed: bool
    requires_gate: bool = False
    gate_type: GateType | None = None
    description: str = ""


# ------------------------------------------------------------------ #
# The permission matrix
#
# Structure: PERMISSION_MATRIX[role][operation] = PermissionRule
#
# This encodes the full table from Milestone 0 design:
#   ✓  = allowed immediately
#   ⚠  = allowed but requires gate
#   ✗  = denied
# ------------------------------------------------------------------ #

def _allow(desc: str = "") -> PermissionRule:
    return PermissionRule(allowed=True, description=desc)

def _gate_confirm(desc: str = "") -> PermissionRule:
    return PermissionRule(
        allowed=True,
        requires_gate=True,
        gate_type=GateType.CONFIRMATION,
        description=desc,
    )

def _gate_approve(desc: str = "") -> PermissionRule:
    return PermissionRule(
        allowed=True,
        requires_gate=True,
        gate_type=GateType.APPROVAL,
        description=desc,
    )

def _deny(desc: str = "") -> PermissionRule:
    return PermissionRule(allowed=False, description=desc)


PERMISSION_MATRIX: dict[str, dict[str, PermissionRule]] = {

    # ---------------------------------------------------------------- #
    # super_admin — full platform access
    # ---------------------------------------------------------------- #
    RoleName.SUPER_ADMIN: {
        OperationType.SELECT:   _allow("Full read access"),
        OperationType.INSERT:   _allow("Full insert access"),
        OperationType.UPDATE:   _allow("Full update access"),
        OperationType.DELETE:   _allow("Full delete access"),
        OperationType.CREATE:   _allow("Full DDL access"),
        OperationType.ALTER:    _allow("Full DDL access"),
        OperationType.DROP:     _allow("Full DDL access"),
        OperationType.TRUNCATE: _allow("Full access including TRUNCATE"),
        OperationType.EXPORT:   _allow("Full export access"),
        OperationType.MANAGE:   _allow("Full platform management"),
        OperationType.VIEW:     _allow("Full audit log access"),
    },

    # ---------------------------------------------------------------- #
    # org_admin — manages one organization
    # ---------------------------------------------------------------- #
    RoleName.ORG_ADMIN: {
        OperationType.SELECT:   _allow("Full read access within org"),
        OperationType.INSERT:   _allow("Full insert access within org"),
        OperationType.UPDATE:   _allow("Full update access within org"),
        OperationType.DELETE:   _gate_confirm("Bulk delete requires confirmation"),
        OperationType.CREATE:   _allow("Can create tables"),
        OperationType.ALTER:    _allow("Can alter tables"),
        OperationType.DROP:     _gate_confirm("DROP requires confirmation"),
        OperationType.TRUNCATE: _deny("TRUNCATE reserved for super_admin"),
        OperationType.EXPORT:   _allow("Can export query results"),
        OperationType.MANAGE:   _allow("Can manage org connections and members"),
        OperationType.VIEW:     _allow("Can view org audit logs"),
    },

    # ---------------------------------------------------------------- #
    # dba — database administrator
    # ---------------------------------------------------------------- #
    RoleName.DBA: {
        OperationType.SELECT:   _allow("Full read access"),
        OperationType.INSERT:   _allow("Can insert data"),
        OperationType.UPDATE:   _gate_confirm("Bulk update requires confirmation"),
        OperationType.DELETE:   _gate_confirm("Delete requires confirmation"),
        OperationType.CREATE:   _allow("Can create tables"),
        OperationType.ALTER:    _gate_confirm("ALTER requires confirmation"),
        OperationType.DROP:     _deny("DROP not permitted for DBA — requires org_admin"),
        OperationType.TRUNCATE: _deny("TRUNCATE not permitted for DBA"),
        OperationType.EXPORT:   _allow("Can export query results"),
        OperationType.MANAGE:   _allow("Can register and manage DB connections"),
        OperationType.VIEW:     _allow("Can view audit logs"),
    },

    # ---------------------------------------------------------------- #
    # analyst — read-only + export
    # ---------------------------------------------------------------- #
    RoleName.ANALYST: {
        OperationType.SELECT:   _allow("Full read access"),
        OperationType.INSERT:   _deny("Analysts cannot insert data"),
        OperationType.UPDATE:   _deny("Analysts cannot update data"),
        OperationType.DELETE:   _deny("Analysts cannot delete data"),
        OperationType.CREATE:   _deny("Analysts cannot create tables"),
        OperationType.ALTER:    _deny("Analysts cannot alter tables"),
        OperationType.DROP:     _deny("Analysts cannot drop tables"),
        OperationType.TRUNCATE: _deny("Analysts cannot truncate tables"),
        OperationType.EXPORT:   _allow("Can export query results"),
        OperationType.MANAGE:   _deny("Analysts cannot manage connections"),
        OperationType.VIEW:     _deny("Analysts cannot view audit logs"),
    },

    # ---------------------------------------------------------------- #
    # viewer — SELECT only
    # ---------------------------------------------------------------- #
    RoleName.VIEWER: {
        OperationType.SELECT:   _allow("Read-only access"),
        OperationType.INSERT:   _deny("Viewers cannot insert data"),
        OperationType.UPDATE:   _deny("Viewers cannot update data"),
        OperationType.DELETE:   _deny("Viewers cannot delete data"),
        OperationType.CREATE:   _deny("Viewers cannot create tables"),
        OperationType.ALTER:    _deny("Viewers cannot alter tables"),
        OperationType.DROP:     _deny("Viewers cannot drop tables"),
        OperationType.TRUNCATE: _deny("Viewers cannot truncate tables"),
        OperationType.EXPORT:   _deny("Viewers cannot export — upgrade to analyst"),
        OperationType.MANAGE:   _deny("Viewers cannot manage connections"),
        OperationType.VIEW:     _deny("Viewers cannot view audit logs"),
    },
}


class PermissionRegistry:
    """
    In-memory permission registry for fast RBAC lookups.

    Wraps PERMISSION_MATRIX with a clean interface.

    Usage:
        registry = PermissionRegistry()

        rule = registry.get_rule("analyst", "SELECT")
        if rule.allowed:
            # proceed

        rule = registry.get_rule("dba", "DELETE")
        if rule.requires_gate:
            # issue confirmation token
    """

    def get_rule(
        self,
        role: str,
        operation: str,
    ) -> PermissionRule:
        """
        Get the permission rule for a role + operation combination.

        Args:
            role:      Role name string (e.g. 'analyst', 'dba')
            operation: Operation type string (e.g. 'SELECT', 'DELETE')

        Returns:
            PermissionRule with allowed, requires_gate, gate_type.
            Returns a deny rule if role or operation is unknown.
        """
        role_lower = role.lower()
        op_upper = operation.upper()

        role_permissions = PERMISSION_MATRIX.get(role_lower)
        if not role_permissions:
            return _deny(f"Unknown role: {role}")

        rule = role_permissions.get(op_upper)
        if not rule:
            return _deny(f"Unknown operation: {operation}")

        return rule

    def is_allowed(self, role: str, operation: str) -> bool:
        """Quick boolean check — is this operation allowed for this role?"""
        return self.get_rule(role, operation).allowed

    def requires_gate(self, role: str, operation: str) -> bool:
        """Does this operation require a confirmation/approval gate?"""
        rule = self.get_rule(role, operation)
        return rule.allowed and rule.requires_gate

    def get_denied_message(self, role: str, operation: str) -> str:
        """Get a user-friendly message explaining why access was denied."""
        rule = self.get_rule(role, operation)
        if rule.description:
            return rule.description
        return f"Role '{role}' does not have permission for {operation} operations."

    def list_allowed_operations(self, role: str) -> list[str]:
        """
        List all operations permitted for a role.
        Useful for building UI that shows what a user can do.
        """
        role_lower = role.lower()
        role_permissions = PERMISSION_MATRIX.get(role_lower, {})
        return [
            op for op, rule in role_permissions.items()
            if rule.allowed
        ]


# Module-level singleton — instantiated once, reused everywhere
registry = PermissionRegistry()