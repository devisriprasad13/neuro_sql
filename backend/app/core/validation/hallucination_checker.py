"""
Stage 2 — Hallucination checker.

Detects when the LLM generates column or table names that don't
exist in the retrieved schema context.

Why this matters:
    sqlglot (Stage 1) validates SQL syntax but cannot know whether
    'username' is a real column — it only checks grammar.
    The hallucination checker compares SQL references against
    the schema we retrieved from Pinecone.

What counts as a hallucination:
    - Column name referenced in SQL but not in schema context
    - Table name referenced in SQL but not in schema context

What does NOT count as a hallucination:
    - SQL functions (COUNT, SUM, NOW, COALESCE, etc.)
    - SQL keywords used as expressions
    - Aliases (AS revenue, AS r)
    - Wildcard SELECT * (valid even if we don't list all columns)
    - Subquery-derived column names

False positive risk:
    The schema retriever returns top-k columns, not ALL columns.
    If a query references a valid column that wasn't in the top-k
    results, we'd incorrectly flag it as a hallucination.

    Mitigation: use a WARNING severity (not blocking) for table/column
    checks, and only BLOCK on obviously wrong references.
    Stage 3 (EXPLAIN) is the authoritative check.
"""

from app.core.validation.syntax_validator import SyntaxValidator
from app.utils.logger import get_logger

logger = get_logger(__name__)

# SQL built-in functions and keywords that are not column names
# Expanding this list reduces false positives
SQL_FUNCTIONS = {
    "count", "sum", "avg", "min", "max", "coalesce", "nullif",
    "now", "current_timestamp", "current_date", "current_time",
    "date", "time", "timestamp", "year", "month", "day",
    "extract", "date_trunc", "date_part", "age",
    "upper", "lower", "trim", "ltrim", "rtrim", "substring",
    "concat", "length", "char_length", "position", "replace",
    "cast", "convert", "round", "floor", "ceil", "ceiling", "abs",
    "row_number", "rank", "dense_rank", "lag", "lead",
    "first_value", "last_value", "ntile", "percent_rank",
    "array_agg", "string_agg", "json_agg", "jsonb_agg",
    "bool_and", "bool_or", "every",
    "generate_series", "unnest",
    "true", "false", "null",
    "distinct", "all", "any", "some",
}


class HallucinationResult:
    """Result of hallucination check."""

    def __init__(
        self,
        is_valid: bool,
        hallucinated_tables: list[str] | None = None,
        hallucinated_columns: list[str] | None = None,
        warning: str | None = None,
        error: str | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.hallucinated_tables = hallucinated_tables or []
        self.hallucinated_columns = hallucinated_columns or []
        self.warning = warning
        self.error = error

    def __repr__(self) -> str:
        if self.is_valid:
            return "<HallucinationResult valid>"
        return (
            f"<HallucinationResult invalid "
            f"tables={self.hallucinated_tables} "
            f"columns={self.hallucinated_columns}>"
        )


class HallucinationChecker:
    """
    Checks generated SQL against the retrieved schema context.

    Compares table and column names in the SQL against what
    was actually retrieved from Pinecone to detect LLM hallucinations.

    Usage:
        checker = HallucinationChecker()
        result = checker.check(
            sql="SELECT id, username FROM users",
            schema_matches=[
                {"table_name": "users", "column_name": "id"},
                {"table_name": "users", "column_name": "email"},
            ]
        )
        # result.is_valid == False
        # result.hallucinated_columns == ["username"]
    """

    def __init__(self) -> None:
        self.syntax_validator = SyntaxValidator()

    def check(
        self,
        sql: str,
        schema_matches: list[dict],
        db_type: str = "postgres",
        strict_mode: bool = False,
    ) -> HallucinationResult:
        """
        Check SQL for hallucinated table and column references.

        Args:
            sql:            Generated SQL to check.
            schema_matches: List of schema match dicts from Pinecone.
                           Each must have 'table_name' and 'column_name'.
            db_type:        Target database dialect.
            strict_mode:    If True, block on any unknown column.
                           If False (default), warn but don't block —
                           because schema retriever may not have returned
                           all valid columns.

        Returns:
            HallucinationResult with validity and details.
        """
        if not schema_matches:
            # No schema context — cannot check, skip with warning
            logger.warning("hallucination_check_no_schema_context")
            return HallucinationResult(
                is_valid=True,
                warning="No schema context available — hallucination check skipped",
            )

        # Build sets of known tables and columns from schema matches
        known_tables = {
            match["table_name"].lower()
            for match in schema_matches
            if match.get("table_name")
        }

        known_columns = {
            match["column_name"].lower()
            for match in schema_matches
            if match.get("column_name")
        }

        # Extract what the SQL actually references
        sql_tables = set(
            self.syntax_validator.extract_table_names(sql, db_type)
        )
        sql_columns = set(
            self.syntax_validator.extract_column_names(sql, db_type)
        )

        # Remove SQL functions and keywords from column check
        # These are valid references even if not in schema
        sql_columns_filtered = {
            col for col in sql_columns
            if col not in SQL_FUNCTIONS
        }

        # ------------------------------------------------------------ #
        # Check for hallucinated TABLE names
        # ------------------------------------------------------------ #
        hallucinated_tables = sql_tables - known_tables

        # ------------------------------------------------------------ #
        # Check for hallucinated COLUMN names
        #
        # Note: SELECT * doesn't produce column references in the AST
        # so it won't trigger false positives for wildcard selects.
        # ------------------------------------------------------------ #
        hallucinated_columns = sql_columns_filtered - known_columns

        # ------------------------------------------------------------ #
        # Determine result
        # ------------------------------------------------------------ #
        if hallucinated_tables:
            # Unknown table names are always a blocking error
            # We cannot execute SQL against tables we don't know about
            error_msg = (
                f"SQL references tables not in schema context: "
                f"{sorted(hallucinated_tables)}. "
                f"Known tables: {sorted(known_tables)}"
            )
            logger.warning(
                "hallucination_detected_tables",
                hallucinated=sorted(hallucinated_tables),
                known=sorted(known_tables),
            )
            return HallucinationResult(
                is_valid=False,
                hallucinated_tables=sorted(hallucinated_tables),
                error=error_msg,
            )

        if hallucinated_columns and strict_mode:
            # In strict mode, unknown columns are also blocking
            error_msg = (
                f"SQL references columns not in schema context: "
                f"{sorted(hallucinated_columns)}. "
                f"Known columns: {sorted(known_columns)}"
            )
            logger.warning(
                "hallucination_detected_columns_strict",
                hallucinated=sorted(hallucinated_columns),
                known=sorted(known_columns),
            )
            return HallucinationResult(
                is_valid=False,
                hallucinated_columns=sorted(hallucinated_columns),
                error=error_msg,
            )

        if hallucinated_columns:
            # In non-strict mode, unknown columns are a warning
            # Stage 3 (EXPLAIN) will catch actual errors
            warning_msg = (
                f"SQL references columns not in retrieved schema: "
                f"{sorted(hallucinated_columns)}. "
                f"These may be valid columns not in top-k results."
            )
            logger.debug(
                "hallucination_warning_columns",
                possibly_hallucinated=sorted(hallucinated_columns),
            )
            return HallucinationResult(
                is_valid=True,
                hallucinated_columns=sorted(hallucinated_columns),
                warning=warning_msg,
            )

        logger.debug(
            "hallucination_check_passed",
            sql_tables=sorted(sql_tables),
            sql_columns=sorted(sql_columns_filtered),
        )

        return HallucinationResult(is_valid=True)