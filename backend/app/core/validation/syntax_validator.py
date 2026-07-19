"""
Stage 1 — SQL syntax validator using sqlglot.

Validates SQL syntax without connecting to any database.
sqlglot parses the SQL into an AST and reports syntax errors.

Why sqlglot over other parsers?
    - Supports 20+ SQL dialects (Postgres, MySQL, BigQuery, Snowflake)
    - Pure Python — no external dependencies or network calls
    - Returns structured error information, not just a boolean
    - Can transpile SQL between dialects (used in federation layer)
    - Sub-millisecond parse time

What this catches:
    - Misspelled keywords (SELCT, FORME, WHRE)
    - Missing clauses (SELECT without FROM)
    - Unmatched parentheses
    - Invalid syntax for the target dialect

What this does NOT catch:
    - Hallucinated table/column names (caught in Stage 2)
    - Type mismatches (caught in Stage 3)
    - Missing table references (caught in Stage 3)
"""

import sqlglot
import sqlglot.errors

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Map our db_type strings to sqlglot dialect names
DIALECT_MAP = {
    "postgres":  "postgres",
    "mysql":     "mysql",
    "bigquery":  "bigquery",
    "snowflake": "snowflake",
    "sqlite":    "sqlite",
}


class SyntaxValidationResult:
    """Result of syntax validation."""

    def __init__(
        self,
        is_valid: bool,
        error: str | None = None,
        parsed_statements: list | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.error = error
        self.parsed_statements = parsed_statements or []

    def __repr__(self) -> str:
        if self.is_valid:
            return f"<SyntaxValidationResult valid statements={len(self.parsed_statements)}>"
        return f"<SyntaxValidationResult invalid error={self.error!r}>"


class SyntaxValidator:
    """
    Validates SQL syntax using sqlglot AST parsing.

    Usage:
        validator = SyntaxValidator()
        result = validator.validate("SELECT * FROM users WHERE id = 1", "postgres")
        if not result.is_valid:
            print(f"Syntax error: {result.error}")
    """

    def validate(
        self,
        sql: str,
        db_type: str = "postgres",
    ) -> SyntaxValidationResult:
        """
        Validate SQL syntax for the specified database dialect.

        Args:
            sql:     The SQL statement to validate.
            db_type: Target database type for dialect-aware parsing.

        Returns:
            SyntaxValidationResult with is_valid and error details.
        """
        if not sql or not sql.strip():
            return SyntaxValidationResult(
                is_valid=False,
                error="SQL statement is empty",
            )

        dialect = DIALECT_MAP.get(db_type.lower(), "postgres")

        try:
            # Parse SQL into AST
            # error_level=RAISE means raise on first error instead of collecting
            statements = sqlglot.parse(
                sql,
                dialect=dialect,
                error_level=sqlglot.errors.ErrorLevel.RAISE,
            )

            if not statements:
                return SyntaxValidationResult(
                    is_valid=False,
                    error="SQL produced no parseable statements",
                )

            # Check for None statements (can happen with empty input)
            valid_statements = [s for s in statements if s is not None]
            if not valid_statements:
                return SyntaxValidationResult(
                    is_valid=False,
                    error="SQL contains only empty statements",
                )

            logger.debug(
                "sql_syntax_valid",
                statement_count=len(valid_statements),
                dialect=dialect,
            )

            return SyntaxValidationResult(
                is_valid=True,
                parsed_statements=valid_statements,
            )

        except sqlglot.errors.ParseError as e:
            error_msg = str(e)
            logger.debug(
                "sql_syntax_invalid",
                error=error_msg,
                dialect=dialect,
            )
            return SyntaxValidationResult(
                is_valid=False,
                error=f"Syntax error: {error_msg}",
            )

        except Exception as e:
            logger.error(
                "sql_syntax_validation_unexpected_error",
                error=str(e),
            )
            return SyntaxValidationResult(
                is_valid=False,
                error=f"Validation error: {str(e)}",
            )

    def extract_table_names(self, sql: str, db_type: str = "postgres") -> list[str]:
        """
        Extract table names referenced in a SQL statement.

        Uses sqlglot AST traversal to find all table references.
        More reliable than regex — handles aliases, subqueries, CTEs.

        Args:
            sql:     SQL statement to analyze.
            db_type: Target dialect for parsing.

        Returns:
            List of table names found in the SQL.
            Empty list if parsing fails.

        Example:
            tables = validator.extract_table_names(
                "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.id"
            )
            # returns ["orders", "customers"]
        """
        dialect = DIALECT_MAP.get(db_type.lower(), "postgres")
        try:
            statements = sqlglot.parse(sql, dialect=dialect)
            table_names = []
            for statement in statements:
                if statement:
                    for table in statement.find_all(sqlglot.exp.Table):
                        if table.name:
                            table_names.append(table.name.lower())
            return list(set(table_names))
        except Exception:
            return []

    def extract_column_names(self, sql: str, db_type: str = "postgres") -> list[str]:
        """
        Extract column names referenced in a SQL statement.

        Args:
            sql:     SQL statement to analyze.
            db_type: Target dialect.

        Returns:
            List of column names found. Empty list if parsing fails.
        """
        dialect = DIALECT_MAP.get(db_type.lower(), "postgres")
        try:
            statements = sqlglot.parse(sql, dialect=dialect)
            column_names = []
            for statement in statements:
                if statement:
                    for col in statement.find_all(sqlglot.exp.Column):
                        if col.name:
                            column_names.append(col.name.lower())
            return list(set(column_names))
        except Exception:
            return []

    def get_operation_type(self, sql: str) -> str | None:
        """
        Determine the SQL operation type from the parsed AST.

        More reliable than string matching — correctly handles
        CTEs, subqueries, and comments.

        Args:
            sql: SQL statement to analyze.

        Returns:
            Operation type string: 'SELECT', 'INSERT', 'UPDATE',
            'DELETE', 'CREATE', 'ALTER', 'DROP', 'TRUNCATE'
            or None if cannot be determined.
        """
        try:
            statements = sqlglot.parse(sql)
            if not statements or statements[0] is None:
                return None

            stmt = statements[0]

            # Map sqlglot expression types to operation strings
            type_map = {
                sqlglot.exp.Select:   "SELECT",
                sqlglot.exp.Insert:   "INSERT",
                sqlglot.exp.Update:   "UPDATE",
                sqlglot.exp.Delete:   "DELETE",
                sqlglot.exp.Create:   "CREATE",
                sqlglot.exp.Alter:    "ALTER",
                sqlglot.exp.Drop:     "DROP",
                sqlglot.exp.TruncateTable: "TRUNCATE",
            }

            for exp_type, op_name in type_map.items():
                if isinstance(stmt, exp_type):
                    return op_name

            return None

        except Exception:
            return None