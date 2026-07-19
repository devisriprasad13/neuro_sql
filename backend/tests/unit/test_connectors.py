"""
Unit tests for database connectors.

Run with:
    docker compose exec api pytest tests/unit/test_connectors.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.connectors.base import (
    BaseConnector,
    ConnectionConfig,
    QueryResult,
    TableMetadata,
    get_connector,
)
from app.connectors.postgres import PostgreSQLConnector


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture
def postgres_config() -> ConnectionConfig:
    return ConnectionConfig(
        db_type="postgres",
        host="localhost",
        port=5432,
        database_name="test_db",
        username="test_user",
        password="test_password",
    )


@pytest.fixture
def mysql_config() -> ConnectionConfig:
    return ConnectionConfig(
        db_type="mysql",
        host="localhost",
        port=3306,
        database_name="test_db",
        username="test_user",
        password="test_password",
    )


@pytest.fixture
def sample_query_result() -> QueryResult:
    return QueryResult(
        columns=["id", "name", "email"],
        rows=[
            [1, "Alice", "alice@example.com"],
            [2, "Bob", "bob@example.com"],
        ],
        row_count=2,
        execution_time_ms=12.5,
    )


# ------------------------------------------------------------------ #
# ConnectionConfig tests
# ------------------------------------------------------------------ #

class TestConnectionConfig:

    def test_basic_construction(self, postgres_config: ConnectionConfig):
        assert postgres_config.db_type == "postgres"
        assert postgres_config.host == "localhost"
        assert postgres_config.port == 5432
        assert postgres_config.database_name == "test_db"
        assert postgres_config.username == "test_user"
        assert postgres_config.password == "test_password"

    def test_default_extra_config(self, postgres_config: ConnectionConfig):
        assert postgres_config.extra_config == {}

    def test_optional_fields_default_to_none(self):
        config = ConnectionConfig(db_type="postgres")
        assert config.host is None
        assert config.port is None
        assert config.database_name is None
        assert config.username is None
        assert config.password is None

    def test_extra_config_stores_values(self):
        config = ConnectionConfig(
            db_type="bigquery",
            extra_config={"project_id": "my-project", "dataset": "analytics"},
        )
        assert config.extra_config["project_id"] == "my-project"
        assert config.extra_config["dataset"] == "analytics"


# ------------------------------------------------------------------ #
# QueryResult tests
# ------------------------------------------------------------------ #

class TestQueryResult:

    def test_success_property_true_when_no_error(
        self, sample_query_result: QueryResult
    ):
        assert sample_query_result.success is True

    def test_success_property_false_when_error(self):
        result = QueryResult(
            columns=[],
            rows=[],
            row_count=0,
            error="Connection refused",
        )
        assert result.success is False

    def test_to_dict_contains_all_fields(
        self, sample_query_result: QueryResult
    ):
        d = sample_query_result.to_dict()
        assert "columns" in d
        assert "rows" in d
        assert "row_count" in d
        assert "affected_rows" in d
        assert "execution_time_ms" in d
        assert "error" in d
        assert "success" in d

    def test_to_dict_values_correct(self, sample_query_result: QueryResult):
        d = sample_query_result.to_dict()
        assert d["columns"] == ["id", "name", "email"]
        assert d["row_count"] == 2
        assert d["success"] is True
        assert d["error"] is None

    def test_default_affected_rows_is_zero(self):
        result = QueryResult(columns=[], rows=[], row_count=0)
        assert result.affected_rows == 0


# ------------------------------------------------------------------ #
# get_connector() factory tests
# ------------------------------------------------------------------ #

class TestGetConnector:

    def test_returns_postgres_connector(
        self, postgres_config: ConnectionConfig
    ):
        connector = get_connector(postgres_config)
        assert isinstance(connector, PostgreSQLConnector)

    def test_raises_for_unsupported_type(self):
        config = ConnectionConfig(db_type="oracle")
        with pytest.raises(ValueError) as exc_info:
            get_connector(config)
        assert "oracle" in str(exc_info.value).lower()
        assert "Unsupported" in str(exc_info.value)

    def test_case_insensitive_db_type(self, postgres_config: ConnectionConfig):
        postgres_config.db_type = "POSTGRES"
        connector = get_connector(postgres_config)
        assert isinstance(connector, PostgreSQLConnector)

    def test_connector_receives_config(
        self, postgres_config: ConnectionConfig
    ):
        connector = get_connector(postgres_config)
        assert connector.config == postgres_config


# ------------------------------------------------------------------ #
# PostgreSQLConnector tests
# ------------------------------------------------------------------ #

class TestPostgreSQLConnector:

    @pytest.mark.asyncio
    async def test_connection_success(
        self, postgres_config: ConnectionConfig
    ):
        connector = PostgreSQLConnector(postgres_config)
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.fetchval = AsyncMock(return_value=1)

        with patch("asyncpg.connect", return_value=mock_conn):
            result = await connector.test_connection()

        assert result is True
        mock_conn.fetchval.assert_called_once_with("SELECT 1")

    @pytest.mark.asyncio
    async def test_connection_failure(
        self, postgres_config: ConnectionConfig
    ):
        connector = PostgreSQLConnector(postgres_config)
        with patch(
            "asyncpg.connect",
            side_effect=Exception("Connection refused")
        ):
            result = await connector.test_connection()
        assert result is False

    @pytest.mark.asyncio
    async def test_execute_select_query(
        self, postgres_config: ConnectionConfig
    ):
        connector = PostgreSQLConnector(postgres_config)

        mock_record_1 = MagicMock()
        mock_record_1.keys.return_value = ["id", "name"]
        mock_record_1.values.return_value = [1, "Alice"]

        mock_record_2 = MagicMock()
        mock_record_2.keys.return_value = ["id", "name"]
        mock_record_2.values.return_value = [2, "Bob"]

        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.fetch = AsyncMock(
            return_value=[mock_record_1, mock_record_2]
        )

        with patch("asyncpg.connect", return_value=mock_conn):
            result = await connector.execute_query(
                "SELECT id, name FROM users",
                read_only=False,
            )

        assert result.success is True
        assert result.row_count == 2
        assert result.columns == ["id", "name"]
        assert result.rows[0] == [1, "Alice"]
        assert result.rows[1] == [2, "Bob"]

    @pytest.mark.asyncio
    async def test_execute_query_returns_error_on_failure(
        self, postgres_config: ConnectionConfig
    ):
        connector = PostgreSQLConnector(postgres_config)
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.fetch = AsyncMock(
            side_effect=Exception("relation does not exist")
        )

        with patch("asyncpg.connect", return_value=mock_conn):
            result = await connector.execute_query("SELECT * FROM nonexistent")

        assert result.success is False
        assert result.error is not None
        assert "does not exist" in result.error
        assert result.row_count == 0

    def test_parse_affected_rows_insert(self):
        assert PostgreSQLConnector._parse_affected_rows("INSERT 0 1") == 1
        assert PostgreSQLConnector._parse_affected_rows("INSERT 0 50") == 50

    def test_parse_affected_rows_update(self):
        assert PostgreSQLConnector._parse_affected_rows("UPDATE 5") == 5
        assert PostgreSQLConnector._parse_affected_rows("UPDATE 0") == 0

    def test_parse_affected_rows_delete(self):
        assert PostgreSQLConnector._parse_affected_rows("DELETE 3") == 3

    def test_parse_affected_rows_invalid(self):
        assert PostgreSQLConnector._parse_affected_rows("") == 0
        assert PostgreSQLConnector._parse_affected_rows("UNKNOWN") == 0

    @pytest.mark.asyncio
    async def test_close_releases_connection(
        self, postgres_config: ConnectionConfig
    ):
        connector = PostgreSQLConnector(postgres_config)
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=mock_conn):
            await connector.test_connection()
            await connector.close()

        mock_conn.close.assert_called_once()
        assert connector._connection is None

    @pytest.mark.asyncio
    async def test_async_context_manager(
        self, postgres_config: ConnectionConfig
    ):
        mock_conn = AsyncMock()
        mock_conn.is_closed = MagicMock(return_value=False)
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=mock_conn):
            async with PostgreSQLConnector(postgres_config) as connector:
                result = await connector.test_connection()

        assert result is True
        mock_conn.close.assert_called_once()


# ------------------------------------------------------------------ #
# TableMetadata tests
# ------------------------------------------------------------------ #

class TestTableMetadata:

    def test_construction(self):
        metadata = TableMetadata(
            table_name="orders",
            table_schema="public",
            columns=[
                {
                    "column_name": "id",
                    "data_type": "uuid",
                    "is_nullable": False,
                    "is_primary_key": True,
                    "is_foreign_key": False,
                    "fk_references": None,
                }
            ],
            row_count=10000,
        )
        assert metadata.table_name == "orders"
        assert metadata.table_schema == "public"
        assert len(metadata.columns) == 1
        assert metadata.columns[0]["is_primary_key"] is True
        assert metadata.row_count == 10000

    def test_default_row_count(self):
        metadata = TableMetadata(
            table_name="users",
            table_schema="public",
            columns=[],
        )
        assert metadata.row_count == 0