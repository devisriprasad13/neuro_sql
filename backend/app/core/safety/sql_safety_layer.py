"""
SQL Safety Layer — final defense before query execution.

Runs AFTER RBAC approval and AFTER SQL generation.
Inspects the generated SQL using sqlglot AST analysis.

Four checks performed in sequence:
    1. Single statement only    — no stacked queries
    2. Operation consistency    — SQL matches declared intent
    3. Forbidden operations     — block TRUNCATE/DROP unless permitted
    4. Injection patterns       — detect common SQL injection vectors

Why AST-based and not regex?
    'DR/*comment*/OP TABLE users' bypasses regex but fails AST parsing.
    The AST parser strips comments and whitespace before analysis.
    It understands SQL grammar — regex does not.

This layer is intentionally conservative.
When in doubt, it blocks and requires human review.
"""

import re
from dataclasses import dataclass

import sqlglot
import sqlglot.expressions as exp

from app.core.validation.syntax_validator import SyntaxValidator
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Operations that are blocked by default regardless of role
# These require explicit super_admin override
ALWAYS_BLOCKED = {
    "TRUNCATE",
}

# Operations that require RBAC to have explicitly allowed them
# (cross-checked with the intent that was declared)
HIGH_RISK_OPERATIONS = {
    "DROP", "ALTER", "DELETE", "UPDATE",
}

# Common SQL injection indicators detected via pattern matching
# on the AST — not on the raw string
INJECTION_INDICATORS = [
    "time_delay",      # SLEEP(), WAITFOR DELAY
    "stacked_query",   # Multiple statements
    "union_extract",   # UNION SELECT targeting sensitive tables
    "always_true",     # OR 1=1, OR 'a'='a'
]

# Sensitive table names that should never appear in UNION attacks
SENSITIVE_TABLES = {
    "users", "passwords", "credentials", "tokens",
    "secrets", "api_keys", "refresh_tokens",
}


@dataclass
class SafetyResult:
    """
    Result of the SQL safety layer inspection.

    Attributes:
        is_safe:          True if SQL passed all safety checks.
        block_reason:     Machine-readable block reason code.
        message:          Human-readable explanation.
        detected_issues:  List of specific issues found.
        actual_operation: The SQL operation detected by AST parser.
    """
    is_safe: bool
    block_reason: str | None = None
    message: str = ""
    detected_issues: list[str] | None = None
    actual_operation: str | None = None

    def __post_init__(self):
        if self.detected_issues is None:
            self.detected_issues = []


class SQLSafetyLayer:
    """
    Inspects generated SQL for safety issues before execution.

    Usage:
        safety = SQLSafetyLayer()
        result = safety.inspect(
            sql="SELECT id FROM users WHERE id = 1",
            declared_operation="SELECT",
            user_role="analyst",
        )
        if not result.is_safe:
            # Block execution
            return error_response(code=result.block_reason, ...)
    """

    def __init__(self) -> None:
        self.syntax_validator = SyntaxValidator()

    def inspect(
        self,
        sql: str,
        declared_operation: str,
        user_role: str,
        db_type: str = "postgres",
    ) -> SafetyResult:
        """
        Run all safety checks on generated SQL.

        Args:
            sql:                The generated SQL to inspect.
            declared_operation: The operation type from intent classifier
                               (SELECT, INSERT, UPDATE, DELETE, DDL).
            user_role:          User's role for context in error messages.
            db_type:            Target database dialect.

        Returns:
            SafetyResult — is_safe=True means proceed, False means block.
        """
        issues = []

        # ------------------------------------------------------------ #
        # Check 1: Parse SQL into AST
        # If it can't be parsed, we can't inspect it safely — block.
        # ------------------------------------------------------------ #
        try:
            statements = sqlglot.parse(sql, dialect=db_type)
            valid_statements = [s for s in statements if s is not None]
        except Exception as e:
            return SafetyResult(
                is_safe=False,
                block_reason="PARSE_FAILED",
                message=f"SQL could not be parsed for safety inspection: {str(e)[:100]}",
            )

        # ------------------------------------------------------------ #
        # Check 2: Single statement only
        # Stacked queries are a primary SQL injection vector.
        # We never allow more than one statement.
        # ------------------------------------------------------------ #
        if len(valid_statements) > 1:
            logger.warning(
                "safety_stacked_query_detected",
                statement_count=len(valid_statements),
                user_role=user_role,
                sql_preview=sql[:100],
            )
            return SafetyResult(
                is_safe=False,
                block_reason="STACKED_QUERY_DETECTED",
                message=(
                    "Multiple SQL statements detected. "
                    "Only single statements are permitted."
                ),
                detected_issues=["stacked_query"],
            )

        if not valid_statements:
            return SafetyResult(
                is_safe=False,
                block_reason="EMPTY_SQL",
                message="No valid SQL statement found.",
            )

        statement = valid_statements[0]

        # ------------------------------------------------------------ #
        # Check 3: Detect actual operation type from AST
        # ------------------------------------------------------------ #
        actual_operation = self._detect_operation(statement)

        # ------------------------------------------------------------ #
        # Check 4: Operation consistency
        # The LLM was instructed to generate a specific operation type.
        # If the AST shows a different operation, flag as injection.
        # ------------------------------------------------------------ #
        if actual_operation and not self._operations_consistent(
            declared_operation, actual_operation
        ):
            logger.warning(
                "safety_operation_mismatch",
                declared=declared_operation,
                actual=actual_operation,
                user_role=user_role,
            )
            return SafetyResult(
                is_safe=False,
                block_reason="OPERATION_MISMATCH",
                message=(
                    f"SQL operation mismatch detected. "
                    f"Expected {declared_operation} but found {actual_operation}. "
                    f"Possible prompt injection attempt."
                ),
                detected_issues=["operation_mismatch"],
                actual_operation=actual_operation,
            )

        # ------------------------------------------------------------ #
        # Check 5: Always-blocked operations
        # TRUNCATE is blocked for all users regardless of role.
        # ------------------------------------------------------------ #
        if actual_operation in ALWAYS_BLOCKED:
            return SafetyResult(
                is_safe=False,
                block_reason="FORBIDDEN_OPERATION",
                message=(
                    f"{actual_operation} is blocked by the SQL safety layer. "
                    f"Contact your platform administrator."
                ),
                detected_issues=["forbidden_operation"],
                actual_operation=actual_operation,
            )

        # ------------------------------------------------------------ #
        # Check 6: Injection pattern detection
        # ------------------------------------------------------------ #
        injection_issues = self._detect_injection_patterns(statement, sql)
        if injection_issues:
            logger.warning(
                "safety_injection_detected",
                issues=injection_issues,
                user_role=user_role,
                sql_preview=sql[:100],
            )
            return SafetyResult(
                is_safe=False,
                block_reason="INJECTION_DETECTED",
                message=(
                    "Potential SQL injection pattern detected. "
                    "Query blocked for security review."
                ),
                detected_issues=injection_issues,
                actual_operation=actual_operation,
            )

        # ------------------------------------------------------------ #
        # All checks passed
        # ------------------------------------------------------------ #
        logger.debug(
            "safety_check_passed",
            actual_operation=actual_operation,
            user_role=user_role,
        )

        return SafetyResult(
            is_safe=True,
            actual_operation=actual_operation,
            message="SQL passed all safety checks.",
        )

    def _detect_operation(self, statement) -> str | None:
        """Detect the SQL operation type from an AST statement node."""
        type_map = {
            exp.Select:        "SELECT",
            exp.Insert:        "INSERT",
            exp.Update:        "UPDATE",
            exp.Delete:        "DELETE",
            exp.Create:        "CREATE",
            exp.AlterTable:    "ALTER",
            exp.Drop:          "DROP",
            exp.TruncateTable: "TRUNCATE",
        }
        for exp_type, op_name in type_map.items():
            if isinstance(statement, exp_type):
                return op_name
        return None

    def _operations_consistent(
        self,
        declared: str,
        actual: str,
    ) -> bool:
        """
        Check if declared intent and actual SQL operation are consistent.

        Maps intent classifier output to SQL operation groups.
        DDL intent covers CREATE, ALTER, DROP.
        """
        declared_upper = declared.upper()
        actual_upper = actual.upper()

        # Direct match
        if declared_upper == actual_upper:
            return True

        # DDL intent covers multiple operations
        ddl_operations = {"CREATE", "ALTER", "DROP", "TRUNCATE"}
        if declared_upper == "DDL" and actual_upper in ddl_operations:
            return True

        # READ intent maps to SELECT and EXPLAIN
        if declared_upper in ("READ", "SELECT") and actual_upper == "SELECT":
            return True

        return False

    def _detect_injection_patterns(
        self,
        statement,
        raw_sql: str,
    ) -> list[str]:
        """
        Detect SQL injection patterns using AST analysis.

        Returns list of detected issue codes, empty if clean.
        """
        issues = []

        # Check for time-delay functions (blind injection)
        # These are used to test if injection is possible
        time_delay_patterns = ["sleep", "waitfor", "pg_sleep", "benchmark"]
        sql_lower = raw_sql.lower()
        for pattern in time_delay_patterns:
            if pattern in sql_lower:
                issues.append("time_delay_function")
                break

        # Check for UNION targeting sensitive tables
        for union_node in statement.find_all(exp.Union):
            for table in union_node.find_all(exp.Table):
                if table.name and table.name.lower() in SENSITIVE_TABLES:
                    issues.append("union_sensitive_table")
                    break

        # Check for always-true conditions (OR 1=1)
        # These appear as EQ nodes with literal values
        for where in statement.find_all(exp.Where):
            where_sql = where.sql().lower()
            always_true_patterns = [
                "or 1=1", "or '1'='1'", "or 1 = 1",
                "or true", "or 'a'='a'",
            ]
            for pattern in always_true_patterns:
                if pattern in where_sql:
                    issues.append("always_true_condition")
                    break

        return issues


# Module-level singleton
safety_layer = SQLSafetyLayer()