"""
MySQL connector implementation.

Uses aiomysql for fully async, non-blocking MySQL operations.
Supports MySQL 5.7+ and MariaDB 10.3+.

Key differences from PostgreSQL connector:
    - Placeholders: %s (positional) instead of $1, $2
    - Schema = Database in MySQL (no separate schema namespace)
    - Uses cursor-based API instead of asyncpg's direct connection API
    - rowcount attribute instead of parsing command tag string

Schema discovery:
    Reads from information_schema.COLUMNS, TABLE_CONSTRAINTS,
    and KEY_COLUMN_USAGE — MySQL's equivalents of Postgres's
    information_schema views.
"""

import time
from typing import Any

import aiomysql

from app.connectors.base import (
    BaseConnector,
    ConnectionConfig,
    QueryResult,
    TableMetadata,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MySQLConnector(BaseConnector):
    """
    Async MySQL connector using aiomysql.

    Manages a single aiomysql connection per connector instance.
    """

    def __init__(self, config: ConnectionConfig) -> None:
        super().__init__(config)
        self._connection: aiomysql.Connection | None = None

    async def _get_connection(self) -> aiomysql.Connection:
        """
        Get or create the aiomysql connection.

        Returns:
            Active aiomysql connection.

        Raises:
            aiomysql.Error: If connection fails.
        """
        if self._connection is None or self._connection.closed:
            self._connection = await aiomysql.connect(
                host=self.config.host,
                port=self.config.port or 3306,
                db=self.config.database_name,
                user=self.config.username,
                password=self.config.password or "",
                # Return rows as dicts instead of tuples
                cursorclass=aiomysql.DictCursor,
                # Connection timeout
                connect_timeout=10,
                # Auto-commit off — we control transactions
                autocommit=False,
                # SSL from extra_config if provided
                ssl=self.config.extra_config.get("ssl"),
            )
            logger.debug(
                "mysql_connected",
                host=self.config.host,
                database=self.config.database_name,
            )
        return self._connection

    async def test_connection(self) -> bool:
        """
        Test if the MySQL database is reachable.

        Returns:
            True if connection and query succeed, False otherwise.
        """
        try:
            conn = await self._get_connection()
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                await cursor.fetchone()
            logger.info(
                "mysql_connection_test_passed",
                host=self.config.host,
                database=self.config.database_name,
            )
            return True
        except Exception as e:
            logger.warning(
                "mysql_connection_test_failed",
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
        Execute a SQL query against MySQL.

        Args:
            sql:       SQL statement. Use %s for positional placeholders.
            params:    Dict of parameters. Values are extracted in order.
            read_only: If True, rollback after execution (prevents writes).

        Returns:
            QueryResult with data or error information.
        """
        start_time = time.monotonic()

        try:
            conn = await self._get_connection()

            # Extract parameter values in order for %s placeholders
            param_values = tuple(params.values()) if params else ()

            async with conn.cursor() as cursor:
                await cursor.execute(sql, param_values)

                sql_upper = sql.strip().upper()
                is_select = (
                    sql_upper.startswith("SELECT") or
                    sql_upper.startswith("WITH") or
                    sql_upper.startswith("EXPLAIN")
                )

                if is_select:
                    # Fetch all rows as dicts (DictCursor)
                    records = await cursor.fetchall()
                    if records:
                        columns = list(records[0].keys())
                        rows = [list(r.values()) for r in records]
                    else:
                        # Get column names even for empty results
                        columns = [
                            desc[0] for desc in cursor.description
                        ] if cursor.description else []
                        rows = []

                    if read_only:
                        await conn.rollback()
                    else:
                        await conn.commit()

                    execution_time = (time.monotonic() - start_time) * 1000

                    return QueryResult(
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        execution_time_ms=round(execution_time, 2),
                    )

                else:
                    # Write operation — get affected row count
                    affected = cursor.rowcount

                    if read_only:
                        # Rollback write in read-only mode
                        await conn.rollback()
                        return QueryResult(
                            columns=[],
                            rows=[],
                            row_count=0,
                            affected_rows=0,
                            execution_time_ms=0,
                            error="Write operation blocked: read_only=True",
                        )

                    await conn.commit()
                    execution_time = (time.monotonic() - start_time) * 1000

                    logger.info(
                        "mysql_write_executed",
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

        except aiomysql.Error as e:
            execution_time = (time.monotonic() - start_time) * 1000
            logger.error(
                "mysql_query_failed",
                error=str(e),
                sql=sql[:200],
            )
            # Rollback on error
            try:
                if self._connection:
                    await self._connection.rollback()
            except Exception:
                pass

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
                "mysql_unexpected_error",
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
        Discover all tables and columns in the MySQL database.

        MySQL's information_schema uses uppercase table names
        for system tables (COLUMNS, TABLE_CONSTRAINTS, etc.)
        unlike PostgreSQL's lowercase names.

        Returns:
            List of TableMetadata with complete column information.
        """
        try:
            conn = await self._get_connection()

            async with conn.cursor() as cursor:

                # ---------------------------------------------------- #
                # Query 1: Get all columns
                # TABLE_SCHEMA in MySQL = database name
                # ---------------------------------------------------- #
                await cursor.execute("""
                    SELECT
                        TABLE_SCHEMA   AS table_schema,
                        TABLE_NAME     AS table_name,
                        COLUMN_NAME    AS column_name,
                        DATA_TYPE      AS data_type,
                        IS_NULLABLE    AS is_nullable,
                        COLUMN_KEY     AS column_key
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """, (self.config.database_name,))

                column_records = await cursor.fetchall()

                # ---------------------------------------------------- #
                # Query 2: Get foreign key relationships
                # ---------------------------------------------------- #
                await cursor.execute("""
                    SELECT
                        kcu.TABLE_NAME     AS table_name,
                        kcu.COLUMN_NAME    AS column_name,
                        kcu.REFERENCED_TABLE_NAME  AS ref_table,
                        kcu.REFERENCED_COLUMN_NAME AS ref_column
                    FROM information_schema.KEY_COLUMN_USAGE kcu
                    WHERE kcu.TABLE_SCHEMA = %s
                        AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                """, (self.config.database_name,))

                fk_records = await cursor.fetchall()

            # Build FK lookup
            fk_dict: dict[tuple, str] = {}
            for r in fk_records:
                key = (r["table_name"], r["column_name"])
                fk_dict[key] = f"{r['ref_table']}.{r['ref_column']}"

            # Build TableMetadata objects
            tables: dict[str, TableMetadata] = {}

            for record in column_records:
                table = record["table_name"]
                column = record["column_name"]

                if table not in tables:
                    tables[table] = TableMetadata(
                        table_name=table,
                        table_schema=record["table_schema"],
                        columns=[],
                    )

                # MySQL COLUMN_KEY: 'PRI' = primary key
                is_pk = record["column_key"] == "PRI"
                fk_key = (table, column)

                tables[table].columns.append({
                    "column_name": column,
                    "data_type": record["data_type"],
                    "is_nullable": record["is_nullable"] == "YES",
                    "is_primary_key": is_pk,
                    "is_foreign_key": fk_key in fk_dict,
                    "fk_references": fk_dict.get(fk_key),
                })

            result = list(tables.values())

            logger.info(
                "mysql_schema_crawled",
                table_count=len(result),
                database=self.config.database_name,
            )

            return result

        except Exception as e:
            logger.error("mysql_schema_crawl_failed", error=str(e))
            return []

    async def close(self) -> None:
        """Close the aiomysql connection."""
        if self._connection and not self._connection.closed:
            self._connection.close()
            self._connection = None
            logger.debug(
                "mysql_connection_closed",
                host=self.config.host,
                database=self.config.database_name,
            )