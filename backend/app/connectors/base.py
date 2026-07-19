"""
Base connector interface.

Every database connector must implement this abstract base class.
The rest of the application only interacts with BaseConnector —
never with specific connector implementations directly.

This enforces a consistent interface across all database types:
    PostgreSQLConnector implements BaseConnector
    MySQLConnector      implements BaseConnector
    BigQueryConnector   implements BaseConnector
    SnowflakeConnector  implements BaseConnector

Design pattern: Abstract Base Class (ABC)
    - Defines WHAT methods must exist
    - Does not define HOW they work
    - Python raises TypeError if a subclass forgets to implement
      any abstract method
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConnectionConfig:
    """
    Normalized connection configuration.

    All connector implementations receive this dataclass
    instead of raw strings, ensuring type safety and
    consistent field naming regardless of database type.

    Fields:
        db_type:       'postgres' | 'mysql' | 'bigquery' | 'snowflake'
        host:          database server hostname
        port:          database server port
        database_name: name of the target database
        username:      authentication username
        password:      plaintext password (decrypted before passing here)
        extra_config:  database-specific extra parameters as dict
    """
    db_type: str
    host: str | None = None
    port: int | None = None
    database_name: str | None = None
    username: str | None = None
    password: str | None = None
    extra_config: dict = field(default_factory=dict)


@dataclass
class QueryResult:
    """
    Standardized query result returned by all connectors.

    Regardless of which database was queried, the result
    always has the same structure. This is what the
    federated executor merges across databases.

    Fields:
        columns:       ordered list of column names
        rows:          list of rows, each row is a list of values
        row_count:     number of rows returned or affected
        affected_rows: rows modified (for INSERT/UPDATE/DELETE)
        execution_time_ms: how long the query took
        error:         error message if query failed, None if success
    """
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    affected_rows: int = 0
    execution_time_ms: float = 0.0
    error: str | None = None

    @property
    def success(self) -> bool:
        """True if the query executed without error."""
        return self.error is None

    def to_dict(self) -> dict:
        """Serialize result to a JSON-safe dictionary."""
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "affected_rows": self.affected_rows,
            "execution_time_ms": self.execution_time_ms,
            "error": self.error,
            "success": self.success,
        }


@dataclass
class TableMetadata:
    """
    Metadata for one table discovered during schema crawl.

    Fields:
        table_name:   name of the table
        table_schema: schema/namespace (e.g. 'public' in Postgres)
        columns:      list of column metadata dicts
        row_count:    approximate row count (from statistics)
    """
    table_name: str
    table_schema: str
    columns: list[dict]
    row_count: int = 0


class BaseConnector(ABC):
    """
    Abstract base class for all database connectors.

    Every connector must implement these four methods:
        test_connection() → verify credentials work
        execute_query()   → run SQL and return results
        get_schema()      → discover all tables and columns
        close()           → release connection resources

    Usage:
        # The factory function returns the right connector:
        connector = get_connector(config)

        # Application code uses only BaseConnector methods:
        is_alive = await connector.test_connection()
        result = await connector.execute_query("SELECT * FROM orders")
        schema = await connector.get_schema()
        await connector.close()
    """

    def __init__(self, config: ConnectionConfig) -> None:
        """
        Initialize connector with connection configuration.

        Args:
            config: Normalized connection configuration.
                    Password must already be decrypted before
                    passing to this constructor.
        """
        self.config = config

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Verify the database is reachable with these credentials.

        Returns:
            True if connection succeeds, False otherwise.
            Should never raise — catch all exceptions internally
            and return False.

        Usage:
            is_alive = await connector.test_connection()
            if not is_alive:
                return error_response("Cannot connect to database")
        """
        ...

    @abstractmethod
    async def execute_query(
        self,
        sql: str,
        params: dict | None = None,
        read_only: bool = False,
    ) -> QueryResult:
        """
        Execute a SQL query and return standardized results.

        Args:
            sql:       The SQL statement to execute.
            params:    Optional bind parameters for safe parameterization.
                       Always use params instead of string formatting
                       to prevent SQL injection.
            read_only: If True, execute in a read-only transaction.
                       Used for SELECT queries to prevent accidental writes.

        Returns:
            QueryResult with columns, rows, and metadata.
            Never raises — catches exceptions and returns
            QueryResult with error field set.

        Usage:
            result = await connector.execute_query(
                "SELECT * FROM orders WHERE customer_id = :customer_id",
                params={"customer_id": customer_id},
                read_only=True,
            )
            if not result.success:
                logger.error("Query failed", error=result.error)
        """
        ...

    @abstractmethod
    async def get_schema(self) -> list[TableMetadata]:
        """
        Discover all tables and columns in the connected database.

        Reads from information_schema (or database-specific equivalent)
        to build a complete picture of the database structure.

        Returns:
            List of TableMetadata objects, one per table.
            Each TableMetadata contains a list of column dicts:
            {
                "column_name": str,
                "data_type": str,
                "is_nullable": bool,
                "is_primary_key": bool,
                "is_foreign_key": bool,
                "fk_references": str | None,
            }

        Usage:
            tables = await connector.get_schema()
            for table in tables:
                print(f"{table.table_name}: {len(table.columns)} columns")
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """
        Release all connection resources.

        Must be called when the connector is no longer needed.
        Use as an async context manager to ensure this is called:

            async with connector:
                result = await connector.execute_query(sql)
        """
        ...

    async def __aenter__(self) -> "BaseConnector":
        """Support async context manager: async with connector."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure close() is always called on exit."""
        await self.close()


def get_connector(config: ConnectionConfig) -> BaseConnector:
    """
    Factory function — returns the correct connector for a database type.

    This is the only function the rest of the application calls.
    It hides which specific connector class is being used.

    Args:
        config: Connection configuration with db_type set.

    Returns:
        The appropriate BaseConnector subclass instance.

    Raises:
        ValueError: If db_type is not supported.

    Usage:
        config = ConnectionConfig(
            db_type="postgres",
            host="localhost",
            port=5432,
            database_name="mydb",
            username="user",
            password="pass",
        )
        async with get_connector(config) as connector:
            result = await connector.execute_query("SELECT 1")
    """
    # Import here to avoid circular imports
    from app.connectors.postgres import PostgreSQLConnector
    from app.connectors.mysql import MySQLConnector

    connectors = {
        "postgres":  PostgreSQLConnector,
        "mysql":     MySQLConnector,
        # Future milestones:
        # "bigquery":  BigQueryConnector,
        # "snowflake": SnowflakeConnector,
    }

    db_type = config.db_type.lower()
    connector_class = connectors.get(db_type)

    if connector_class is None:
        supported = list(connectors.keys())
        raise ValueError(
            f"Unsupported database type: '{db_type}'. "
            f"Supported types: {supported}"
        )

    return connector_class(config)