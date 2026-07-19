"""
Schema crawler.

Orchestrates schema discovery for a registered database connection:
    1. Connect to the target database using the connector layer
    2. Read all tables and columns via get_schema()
    3. Save raw metadata to schema_snapshots table in Postgres
    4. Trigger embedding pipeline to index schema in Pinecone

This module is called by:
    - POST /connections/{id}/crawl (manual trigger)
    - Celery scheduled task (nightly re-crawl)
    - First-time connection verification

Why separate from the connector?
    Connectors know HOW to talk to a database.
    The crawler knows WHAT to do with the schema data —
    persist it, track crawl status, and trigger embedding.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.connectors.base import ConnectionConfig, TableMetadata, get_connector
from app.models.database_connection import DatabaseConnection
from app.models.schema_snapshot import SchemaSnapshot
from app.utils.logger import get_logger
from app.utils.crypto import decrypt_credential

logger = get_logger(__name__)


class SchemaCrawler:
    """
    Crawls schema metadata from a registered database connection.

    Usage:
        crawler = SchemaCrawler(db_session)
        result = await crawler.crawl(connection_id)
        print(f"Crawled {result['table_count']} tables")
    """

    def __init__(self, db: AsyncSession) -> None:
        """
        Args:
            db: Async SQLAlchemy session for the NeuroSQL metadata DB.
                Used to read connection config and write schema snapshots.
        """
        self.db = db

    async def crawl(self, connection_id: uuid.UUID) -> dict:
        """
        Perform a full schema crawl for a database connection.

        Steps:
            1. Load connection record from DB
            2. Update crawl_status to 'crawling'
            3. Connect to target database
            4. Read all tables and columns
            5. Delete old schema_snapshots for this connection
            6. Save new schema_snapshots to Postgres
            7. Update crawl_status to 'completed'

        Args:
            connection_id: UUID of the DatabaseConnection to crawl.

        Returns:
            Dict with crawl results:
            {
                "connection_id": str,
                "table_count": int,
                "column_count": int,
                "status": "completed" | "failed",
                "error": str | None,
            }
        """
        logger.info("schema_crawl_started", connection_id=str(connection_id))

        # ------------------------------------------------------------ #
        # Step 1: Load the connection record
        # ------------------------------------------------------------ #
        connection = await self._get_connection(connection_id)
        if not connection:
            logger.error(
                "schema_crawl_connection_not_found",
                connection_id=str(connection_id),
            )
            return {
                "connection_id": str(connection_id),
                "table_count": 0,
                "column_count": 0,
                "status": "failed",
                "error": f"Connection {connection_id} not found",
            }

        # ------------------------------------------------------------ #
        # Step 2: Mark as crawling
        # ------------------------------------------------------------ #
        await self._update_crawl_status(connection, "crawling")

        try:
            # -------------------------------------------------------- #
            # Step 3: Build connector config
            # Decrypt the stored password before connecting
            # -------------------------------------------------------- #
            config = await self._build_connector_config(connection)

            # -------------------------------------------------------- #
            # Step 4: Connect and crawl schema
            # -------------------------------------------------------- #
            async with get_connector(config) as connector:
                # Verify connection first
                is_alive = await connector.test_connection()
                if not is_alive:
                    raise ConnectionError(
                        f"Cannot connect to {connection.name}. "
                        "Check credentials and network access."
                    )

                # Get all tables and columns
                tables: list[TableMetadata] = await connector.get_schema()

            logger.info(
                "schema_crawl_data_retrieved",
                connection_id=str(connection_id),
                table_count=len(tables),
            )

            # -------------------------------------------------------- #
            # Step 5: Delete old snapshots for this connection
            # We replace the entire schema on each crawl
            # -------------------------------------------------------- #
            await self._delete_existing_snapshots(connection_id)

            # -------------------------------------------------------- #
            # Step 6: Save new snapshots to Postgres
            # -------------------------------------------------------- #
            column_count = await self._save_snapshots(
                connection_id, tables
            )

            # -------------------------------------------------------- #
            # Step 7: Mark as completed
            # -------------------------------------------------------- #
            await self._update_crawl_status(
                connection,
                "completed",
                last_crawled_at=datetime.now(timezone.utc),
            )

            logger.info(
                "schema_crawl_completed",
                connection_id=str(connection_id),
                table_count=len(tables),
                column_count=column_count,
            )

            return {
                "connection_id": str(connection_id),
                "table_count": len(tables),
                "column_count": column_count,
                "status": "completed",
                "error": None,
            }

        except Exception as e:
            # Mark as failed and re-raise for the caller to handle
            await self._update_crawl_status(connection, "failed")
            logger.error(
                "schema_crawl_failed",
                connection_id=str(connection_id),
                error=str(e),
            )
            return {
                "connection_id": str(connection_id),
                "table_count": 0,
                "column_count": 0,
                "status": "failed",
                "error": str(e),
            }

    async def _get_connection(
        self, connection_id: uuid.UUID
    ) -> DatabaseConnection | None:
        """Load a DatabaseConnection record from Postgres."""
        result = await self.db.execute(
            select(DatabaseConnection).where(
                DatabaseConnection.id == connection_id
            )
        )
        return result.scalar_one_or_none()

    async def _build_connector_config(
        self, connection: DatabaseConnection
    ) -> ConnectionConfig:
        """
        Build a ConnectionConfig from a DatabaseConnection model.

        Decrypts the stored password before returning.
        The decrypted password lives only in memory — never logged
        or persisted.
        """
        # Decrypt password only when needed for connection
        plaintext_password = None
        if connection.encrypted_password:
            plaintext_password = decrypt_credential(
                connection.encrypted_password
            )

        return ConnectionConfig(
            db_type=connection.db_type,
            host=connection.host,
            port=connection.port,
            database_name=connection.database_name,
            username=connection.username,
            password=plaintext_password,
            extra_config=connection.extra_config or {},
        )

    async def _update_crawl_status(
        self,
        connection: DatabaseConnection,
        status: str,
        last_crawled_at: datetime | None = None,
    ) -> None:
        """Update the crawl_status field on the connection record."""
        connection.crawl_status = status
        if last_crawled_at:
            connection.last_crawled_at = last_crawled_at
        await self.db.commit()

    async def _delete_existing_snapshots(
        self, connection_id: uuid.UUID
    ) -> None:
        """
        Delete all existing schema snapshots for this connection.

        We replace the entire schema on each crawl to handle:
        - Dropped tables/columns
        - Renamed columns
        - Type changes
        """
        await self.db.execute(
            delete(SchemaSnapshot).where(
                SchemaSnapshot.connection_id == connection_id
            )
        )
        await self.db.commit()

    async def _save_snapshots(
        self,
        connection_id: uuid.UUID,
        tables: list[TableMetadata],
    ) -> int:
        """
        Save TableMetadata objects as SchemaSnapshot rows.

        Args:
            connection_id: The database connection these schemas belong to.
            tables:        List of TableMetadata from the connector.

        Returns:
            Total number of columns saved across all tables.
        """
        column_count = 0

        for table in tables:
            for column in table.columns:
                snapshot = SchemaSnapshot(
                    connection_id=connection_id,
                    table_name=table.table_name,
                    table_schema=table.table_schema,
                    column_name=column["column_name"],
                    data_type=column.get("data_type"),
                    is_nullable=column.get("is_nullable", True),
                    is_primary_key=column.get("is_primary_key", False),
                    is_foreign_key=column.get("is_foreign_key", False),
                    fk_references=column.get("fk_references"),
                )
                self.db.add(snapshot)
                column_count += 1

        await self.db.commit()
        logger.debug(
            "schema_snapshots_saved",
            connection_id=str(connection_id),
            column_count=column_count,
        )
        return column_count