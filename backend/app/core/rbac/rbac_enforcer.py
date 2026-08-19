"""
RBAC enforcer — applies permission rules to incoming requests.

Sits between Gate 1 (authentication) and the LLM pipeline.
Called BEFORE the LLM generates any SQL.

Why check before the LLM?
    1. Cost: avoid spending Groq API tokens on blocked operations
    2. Security: LLM never sees a prompt for an unauthorized operation
    3. Speed: permission check is microseconds vs LLM call is ~400ms

Flow:
    User submits NL query
        ↓
    IntentClassifier.classify() → SQLOperationType
        ↓
    RBACEnforcer.check() → EnforcementResult
        ↓ allowed
    SQL generation proceeds
        ↓ denied
    Return 403 immediately

"""

from dataclasses import dataclass

from app.core.nlp.intent_classifier import SQLOperationType
from app.core.rbac.permission_registry import GateType, PermissionRegistry, registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EnforcementResult:
    """
    Result of an RBAC enforcement check.

    Attributes:
        allowed:       True if the operation is permitted.
        requires_gate: True if a confirmation/approval step is needed.
        gate_type:     Type of gate if requires_gate is True.
        message:       Human-readable message for the user.
        error_code:    Machine-readable code for the frontend.
    """
    allowed: bool
    requires_gate: bool = False
    gate_type: GateType | None = None
    message: str = ""
    error_code: str = ""


# Maps SQLOperationType enum values to RBAC operation strings
INTENT_TO_OPERATION: dict[SQLOperationType, str] = {
    SQLOperationType.READ:   "SELECT",
    SQLOperationType.INSERT: "INSERT",
    SQLOperationType.UPDATE: "UPDATE",
    SQLOperationType.DELETE: "DELETE",
    SQLOperationType.DDL:    "CREATE",   # DDL defaults to CREATE check
}


class RBACEnforcer:
    """
    Enforces role-based permissions on SQL operations.

    Usage:
        enforcer = RBACEnforcer()

        result = enforcer.check_intent(
            role="analyst",
            intent=SQLOperationType.DELETE,
        )

        if not result.allowed:
            return error_response(code=result.error_code, message=result.message)

        if result.requires_gate:
            # Issue confirmation token, return 202 Pending
    """

    def __init__(self, permission_registry: PermissionRegistry | None = None):
        self._registry = permission_registry or registry

    def check_intent(
        self,
        role: str,
        intent: SQLOperationType,
    ) -> EnforcementResult:
        """
        Check if a role is permitted to perform the classified intent.

        Args:
            role:   The user's role name (e.g. 'analyst', 'dba').
            intent: The classified SQL operation type from IntentClassifier.

        Returns:
            EnforcementResult with allowed/denied decision and details.

        Example:
            result = enforcer.check_intent("analyst", SQLOperationType.DELETE)
            # result.allowed == False
            # result.error_code == "RBAC_PERMISSION_DENIED"
            # result.message == "Analysts cannot delete data"
        """
        operation = INTENT_TO_OPERATION.get(intent)
        if not operation:
            logger.error(
                "rbac_unknown_intent",
                intent=str(intent),
                role=role,
            )
            return EnforcementResult(
                allowed=False,
                message=f"Unknown operation type: {intent}",
                error_code="RBAC_UNKNOWN_OPERATION",
            )

        return self.check_operation(role, operation)

    def check_operation(
        self,
        role: str,
        operation: str,
    ) -> EnforcementResult:
        """
        Check if a role is permitted for a specific SQL operation.

        Args:
            role:      Role name string.
            operation: SQL operation string (SELECT, INSERT, etc.)

        Returns:
            EnforcementResult with decision details.
        """
        rule = self._registry.get_rule(role, operation)

        if not rule.allowed:
            message = rule.description or (
                f"Your role ({role}) does not permit {operation} operations."
            )
            logger.warning(
                "rbac_denied",
                role=role,
                operation=operation,
                message=message,
            )
            return EnforcementResult(
                allowed=False,
                message=message,
                error_code="RBAC_PERMISSION_DENIED",
            )

        if rule.requires_gate:
            message = rule.description or (
                f"Operation {operation} requires additional confirmation."
            )
            logger.info(
                "rbac_gate_required",
                role=role,
                operation=operation,
                gate_type=rule.gate_type.value if rule.gate_type else None,
            )
            return EnforcementResult(
                allowed=True,
                requires_gate=True,
                gate_type=rule.gate_type,
                message=message,
                error_code="OPERATION_REQUIRES_GATE",
            )

        logger.debug(
            "rbac_allowed",
            role=role,
            operation=operation,
        )
        return EnforcementResult(
            allowed=True,
            message=f"Operation {operation} permitted for role {role}.",
        )

    def check_ddl_operation(
        self,
        role: str,
        ddl_type: str,
    ) -> EnforcementResult:
        """
        Check DDL operations with finer granularity.

        DDL covers CREATE, ALTER, DROP, TRUNCATE — each has different
        permissions. This method checks the specific DDL type rather
        than defaulting to CREATE.

        Args:
            role:     Role name string.
            ddl_type: Specific DDL operation: CREATE, ALTER, DROP, TRUNCATE.

        Returns:
            EnforcementResult with decision details.
        """
        return self.check_operation(role, ddl_type.upper())

    def get_upgrade_path(self, role: str, operation: str) -> str:
        """
        Suggest what role upgrade would grant the needed permission.

        Used in error messages to tell users what to ask their admin for.

        Args:
            role:      Current role name.
            operation: Blocked operation.

        Returns:
            Human-readable upgrade suggestion.
        """
        role_hierarchy = [
            "viewer", "analyst", "dba", "org_admin", "super_admin"
        ]

        current_idx = role_hierarchy.index(role.lower()) \
            if role.lower() in role_hierarchy else 0

        for higher_role in role_hierarchy[current_idx + 1:]:
            rule = self._registry.get_rule(higher_role, operation)
            if rule.allowed:
                return (
                    f"Contact your organization admin to request "
                    f"the '{higher_role}' role for {operation} access."
                )

        return "This operation is restricted. Contact your platform administrator."


# Module-level singleton
enforcer = RBACEnforcer()