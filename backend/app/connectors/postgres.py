"""
PostgreSQL connector implementation.

Uses asyncpg for fully async, non-blocking database operations.
asyncpg is the fastest Python PostgreSQL driver — it uses the
binary protocol directly instead of text serialization.

Why asyncpg over psycopg2?
    psycopg2 blocks the thread while waiting for query results.
    In FastAPI's async event loop, this prevents other requests
    from being processed during database waits.
    asyncpg yields control to the event loop while waiting,
    allowing true concurrent database operations.

Schema discovery:
    Reads from information_schema.columns, table_constraints,
    and key_column_usage to build complete column metadata
    including primary key and foreign key relationships.
"""

import time
from typing import Any

import asyncpg

from app.connectors.base import (
    BaseConnector,
    ConnectionConfig,
    QueryResult,
    TableMetadata,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PostgreSQLConnector(BaseConnector):
    """
    Async PostgreSQL connector using asyncpg.

    Manages a single asyncpg connection per connector instance.
    For production use, consider using asyncpg.create_pool()
    for connection pooling — implemented in Milestone 10.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        # Connection is established lazily on first use
        self._connection: asyncpg.Connection | None = None

    async def _get_connection(self) -> asyncpg.Connection:
        """
        Get or create the asyncpg connection.

        Lazy initialization — we only connect when first needed.
        This avoids holding connections open unnecessarily.

        Returns:
            Active asyncpg connection.

        Raises:
            asyncpg.PostgresError: If connection fails.
        """
        if self._connection is None or self._connection.is_closed():
            self._connection = await asyncpg.connect(
                host=self.config.host,
                port=self.config.port or 5432,
                database=self.config.database_name,
                user=self.config.username,
                password=self.config.password,
                # Connection timeout — fail fast if DB unreachable
                timeout=10.0,
                # SSL mode from extra_config if provided
                ssl=self.config.extra_config.get("ssl_mode"),
            )
            logger.debug(
                "postgres_connected",
                host=self.config.host,
                database=self.config.database_name,
            )
        return self._connection

    async def test_connection(self) -> bool:
        """
        Test if the database is reachable with these credentials.

        Executes 'SELECT 1' — the lightest possible query.
        Returns False (never raises) so callers can check the
        boolean result without try/except.

        Returns:
            True if connection and query succeed, False otherwise.
        """
        try:
            conn = await self._get_connection()
            await conn.fetchval("SELECT 1")
            logger.info(
                "postgres_connection_test_passed",
                host=self.config.host,
                database=self.config.database_name,
            )
            return True
        except Exception as e:
            logger.warning(
                "postgres_connection_test_failed",
                host=self.config.host,
                database=self.config.database_name,
                error=str(e),
            )
            return False

    async def execute_query(
        self,
        sql: str,
        params: dict | None = None,
        read_only: bool = False,
    ) -> QueryResult:
        """
        Execute a SQL query and return standardized results.

        Handles both read (SELECT) and write (INSERT/UPDATE/DELETE) queries.
        For write queries, returns affected_rows count.
        For read queries, returns columns and rows.

        Args:
            sql:       SQL statement. Use $1, $2 placeholders for asyncpg.
            params:    Positional parameters matching $1, $2 placeholders.
                       asyncpg uses positional ($1) not named (:name) params.
            read_only: Wrap in read-only transaction for SELECT queries.

        Returns:
            QueryResult with data or error information.
        """
        start_time = time.monotonic()

        try:
            conn = await self._get_connection()

            # Convert dict params to positional list for asyncpg
            # asyncpg uses $1, $2... placeholders with positional args
            param_values = list(params.values()) if params else []

            if read_only:
                # Execute in read-only transaction
                # Prevents accidental writes even if SQL contains mutations
                async with conn.transaction(readonly=True):
                    records = await conn.fetch(sql, *param_values)
            else:
                # Check if this is a SELECT or a write operation
                sql_upper = sql.strip().upper()
                is_select = sql_upper.startswith("SELECT") or \
                            sql_upper.startswith("WITH") or \
                            sql_upper.startswith("EXPLAIN")

                if is_select:
                    records = await conn.fetch(sql, *param_values)
                else:
                    # For INSERT/UPDATE/DELETE, use execute() which
                    # returns the command tag (e.g. "DELETE 42")
                    result = await conn.execute(sql, *param_values)
                    # Parse affected rows from command tag
                    # asyncpg returns "INSERT 0 1", "UPDATE 5", "DELETE 3"
                    affected = self._parse_affected_rows(result)
                    execution_time = (time.monotonic() - start_time) * 1000

                    logger.info(
                        "postgres_write_executed",
                        affected_rows=affected,
                        execution_time_ms=round(execution_time, 2),
                    )

                    return QueryResult(
                        columns=[],
                        rows=[],
                        row_count=0,
                        affected_rows=affected,
                        execution_time_ms=round(execution_time, 2),
                    )

            # Convert asyncpg Records to plain lists
            if records:
                columns = list(records[0].keys())
                rows = [list(record.values()) for record in records]
            else:
                columns = []
                rows = []

            execution_time = (time.monotonic() - start_time) * 1000

            logger.debug(
                "postgres_query_executed",
                row_count=len(rows),
                execution_time_ms=round(execution_time, 2),
            )

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=round(execution_time, 2),
            )

        except asyncpg.PostgresError as e:
            execution_time = (time.monotonic() - start_time) * 1000
            logger.error(
                "postgres_query_failed",
                error=str(e),
                sql=sql[:200],  # Log first 200 chars only
            )
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=round(execution_time, 2),
                error=str(e),
            )

        except Exception as e:
            execution_time = (time.monotonic() - start_time) * 1000
            logger.error(
                "postgres_unexpected_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return QueryResult(
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=round(execution_time, 2),
                error=f"Unexpected error: {str(e)}",
            )

    async def get_schema(self) -> list[TableMetadata]:
        """
        Discover all tables and columns in the connected database.

        Queries three information_schema views:
            columns           → column names, types, nullability
            table_constraints → which columns are primary keys
            key_column_usage  → foreign key references

        Returns:
            List of TableMetadata, one per table, with full column info.
        """
        try:
            conn = await self._get_connection()

            # -------------------------------------------------------- #
            # Query 1: Get all columns from non-system schemas
            # We exclude 'information_schema' and 'pg_catalog'
            # which are Postgres system schemas, not user data.
            # -------------------------------------------------------- #
            columns_query = """
                SELECT
                    c.table_schema,
                    c.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default
                FROM information_schema.columns c
                JOIN information_schema.tables t
                    ON c.table_name = t.table_name
                    AND c.table_schema = t.table_schema
                WHERE c.table_schema NOT IN ('information_schema', 'pg_catalog')
                    AND t.table_type = 'BASE TABLE'
                ORDER BY c.table_schema, c.table_name, c.ordinal_position
            """
            column_records = await conn.fetch(columns_query)

            # -------------------------------------------------------- #
            # Query 2: Get primary key columns
            # -------------------------------------------------------- #
            pk_query = """
                SELECT
                    kcu.table_schema,
                    kcu.table_name,
                    kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema NOT IN ('information_schema', 'pg_catalog')
            """
            pk_records = await conn.fetch(pk_query)

            # Build a set of (schema, table, column) primary key tuples
            # for O(1) lookup when building column metadata
            pk_set = {
                (r["table_schema"], r["table_name"], r["column_name"])
                for r in pk_records
            }

            # -------------------------------------------------------- #
            # Query 3: Get foreign key relationships
            # -------------------------------------------------------- #
            fk_query = """
                SELECT
                    kcu.table_schema,
                    kcu.table_name,
                    kcu.column_name,
                    ccu.table_name  AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema NOT IN ('information_schema', 'pg_catalog')
            """
            fk_records = await conn.fetch(fk_query)

            # Build FK lookup dict: (schema, table, column) → "ref_table.ref_col"
            fk_dict: dict[tuple, str] = {}
            for r in fk_records:
                key = (r["table_schema"], r["table_name"], r["column_name"])
                fk_dict[key] = f"{r['foreign_table_name']}.{r['foreign_column_name']}"

            # -------------------------------------------------------- #
            # Build TableMetadata objects
            # Group column records by (schema, table)
            # -------------------------------------------------------- #
            tables: dict[tuple, TableMetadata] = {}

            for record in column_records:
                schema = record["table_schema"]
                table = record["table_name"]
                column = record["column_name"]
                key = (schema, table)

                if key not in tables:
                    tables[key] = TableMetadata(
                        table_name=table,
                        table_schema=schema,
                        columns=[],
                    )

                col_key = (schema, table, column)
                tables[key].columns.append({
                    "column_name": column,
                    "data_type": record["data_type"],
                    "is_nullable": record["is_nullable"] == "YES",
                    "is_primary_key": col_key in pk_set,
                    "is_foreign_key": col_key in fk_dict,
                    "fk_references": fk_dict.get(col_key),
                })

            result = list(tables.values())

            logger.info(
                "postgres_schema_crawled",
                table_count=len(result),
                database=self.config.database_name,
            )

            return result

        except Exception as e:
            logger.error("postgres_schema_crawl_failed", error=str(e))
            return []

    async def close(self) -> None:
        """Close the asyncpg connection and release resources."""
        if self._connection and not self._connection.is_closed():
            await self._connection.close()
            self._connection = None
            logger.debug(
                "postgres_connection_closed",
                host=self.config.host,
                database=self.config.database_name,
            )

    @staticmethod
    def _parse_affected_rows(command_tag: str) -> int:
        """
        Parse affected row count from asyncpg command tag.

        asyncpg returns command tags like:
            "INSERT 0 1"  → 1 row inserted
            "UPDATE 5"    → 5 rows updated
            "DELETE 3"    → 3 rows deleted

        Args:
            command_tag: The command tag string from asyncpg.execute()

        Returns:
            Number of affected rows, or 0 if parsing fails.
        """
        try:
            parts = command_tag.split()
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0