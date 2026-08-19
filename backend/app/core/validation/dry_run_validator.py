"""
Stage 3 — Dry-run validator using database EXPLAIN.

Runs EXPLAIN on generated SQL against the actual target database.
This is the most authoritative validation stage — if EXPLAIN passes,
the query will almost certainly execute successfully.

Why EXPLAIN?
    EXPLAIN asks the database to parse and plan the query without
    executing it. It catches semantic errors that syntax parsers miss:
        - Table does not exist
        - Column does not exist
        - Type mismatches in WHERE clauses
        - Invalid JOIN conditions
        - Ambiguous column references

    Critically: EXPLAIN never modifies data.
    EXPLAIN DELETE FROM orders WHERE id = 1
    → plans the deletion, deletes NOTHING

Performance:
    EXPLAIN is fast — typically 1-10ms for simple queries.
    The database builds a query plan but doesn't execute it.
    Much cheaper than running the actual query.

Dialect differences:
    PostgreSQL: EXPLAIN SELECT ...
    MySQL:      EXPLAIN SELECT ...  (same syntax)
    BigQuery:   Not supported via standard EXPLAIN
    Snowflake:  EXPLAIN SELECT ... (different output format)
"""

from app.connectors.base import BaseConnector, ConnectionConfig, get_connector
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Databases that support EXPLAIN
EXPLAIN_SUPPORTED = {"postgres", "mysql"}

# Databases where we skip EXPLAIN and rely on Stages 1 and 2
EXPLAIN_NOT_SUPPORTED = {"bigquery", "snowflake"}


class DryRunResult:
    """Result of dry-run EXPLAIN validation."""

    def __init__(
        self,
        is_valid: bool,
        error: str | None = None,
        explain_output: str | None = None,
        skipped: bool = False,
        skip_reason: str | None = None,
    ) -> None:
        self.is_valid = is_valid
        self.error = error
        self.explain_output = explain_output
        self.skipped = skipped
        self.skip_reason = skip_reason

    def __repr__(self) -> str:
        if self.skipped:
            return f"<DryRunResult skipped reason={self.skip_reason!r}>"
        if self.is_valid:
            return "<DryRunResult valid>"
        return f"<DryRunResult invalid error={self.error!r}>"


class DryRunValidator:
    """
    Validates SQL by running EXPLAIN against the target database.

    Usage:
        validator = DryRunValidator()
        result = await validator.validate(
            sql="SELECT id, email FROM users WHERE is_active = true",
            connection_config=config,
        )
        if not result.is_valid:
            print(f"EXPLAIN failed: {result.error}")
    """

    async def validate(
        self,
        sql: str,
        connection_config: ConnectionConfig,
    ) -> DryRunResult:
        """
        Run EXPLAIN on the SQL against the target database.

        Args:
            sql:               The SQL statement to validate.
            connection_config: Connection config for the target database.
                              Password must already be decrypted.

        Returns:
            DryRunResult with validity and EXPLAIN output.
        """
        db_type = connection_config.db_type.lower()

        # ------------------------------------------------------------ #
        # Skip EXPLAIN for unsupported databases
        # ------------------------------------------------------------ #
        if db_type in EXPLAIN_NOT_SUPPORTED:
            logger.debug(
                "dry_run_skipped",
                db_type=db_type,
                reason="EXPLAIN not supported for this database type",
            )
            return DryRunResult(
                is_valid=True,
                skipped=True,
                skip_reason=f"EXPLAIN not supported for {db_type}",
            )

        # ------------------------------------------------------------ #
        # Build EXPLAIN query
        # ------------------------------------------------------------ #
        explain_sql = self._build_explain_sql(sql, db_type)
        if not explain_sql:
            return DryRunResult(
                is_valid=True,
                skipped=True,
                skip_reason="Could not build EXPLAIN query",
            )

        # ------------------------------------------------------------ #
        # Execute EXPLAIN against the target database
        # ------------------------------------------------------------ #
        try:
            async with get_connector(connection_config) as connector:
                result = await connector.execute_query(
                    sql=explain_sql,
                    read_only=True,
                )

            if result.success:
                # Extract EXPLAIN output for logging
                explain_output = self._format_explain_output(result.rows)
                logger.debug(
                    "dry_run_passed",
                    db_type=db_type,
                    explain_rows=result.row_count,
                )
                return DryRunResult(
                    is_valid=True,
                    explain_output=explain_output,
                )
            else:
                # EXPLAIN returned an error
                error_msg = self._clean_db_error(result.error or "Unknown error")
                logger.warning(
                    "dry_run_failed",
                    db_type=db_type,
                    error=error_msg,
                )
                return DryRunResult(
                    is_valid=False,
                    error=error_msg,
                )

        except Exception as e:
            error_msg = self._clean_db_error(str(e))
            logger.error(
                "dry_run_exception",
                db_type=db_type,
                error=error_msg,
            )
            return DryRunResult(
                is_valid=False,
                error=error_msg,
            )

    def _build_explain_sql(self, sql: str, db_type: str) -> str | None:
        """
        Wrap SQL in EXPLAIN for the target database dialect.

        Args:
            sql:     The SQL to explain.
            db_type: Target database type.

        Returns:
            EXPLAIN-wrapped SQL, or None if not supported.
        """
        sql = sql.strip().rstrip(";")

        if db_type == "postgres":
            # EXPLAIN without ANALYZE — plans query, doesn't execute
            # ANALYZE would actually execute and measure performance
            return f"EXPLAIN {sql}"

        elif db_type == "mysql":
            # MySQL uses the same EXPLAIN syntax
            return f"EXPLAIN {sql}"

        return None

    def _format_explain_output(self, rows: list[list]) -> str:
        """Format EXPLAIN output rows into a readable string."""
        if not rows:
            return ""
        lines = []
        for row in rows:
            lines.append(" | ".join(str(cell) for cell in row))
        return "\n".join(lines)

    def _clean_db_error(self, error: str) -> str:
        """
        Clean database error messages before using them in prompts.

        Removes potentially sensitive information:
        - File paths (e.g. /var/lib/postgres/...)
        - Line numbers from internal errors
        - Stack traces

        Keeps:
        - The core error message
        - Column/table names that caused the error
        - Error codes

        This is important for security — cleaned error messages
        are injected into LLM prompts for self-correction.
        Leaking file paths or internal details to the LLM
        (and potentially to logs) is a security risk.

        Args:
            error: Raw database error message.

        Returns:
            Cleaned error message safe for LLM injection.
        """
        import re

        # Remove file paths
        error = re.sub(r'/[a-zA-Z0-9/_.-]+\.py:\d+', '', error)
        error = re.sub(r'/var/lib/[^\s]+', '[path]', error)

        # Remove line number references
        error = re.sub(r'LINE \d+:', '', error)

        # Truncate very long errors
        if len(error) > 300:
            error = error[:300] + "..."

        return error.strip()


async def validate_sql_dry_run(
    sql: str,
    connection_config: ConnectionConfig,
) -> DryRunResult:
    """
    Module-level convenience function for dry-run validation.

    Args:
        sql:               SQL to validate.
        connection_config: Target database connection config.

    Returns:
        DryRunResult with validity and details.
    """
    validator = DryRunValidator()
    return await validator.validate(sql, connection_config)