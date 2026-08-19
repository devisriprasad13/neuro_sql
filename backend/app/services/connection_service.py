"""
Connection service — manages database connection lifecycle.

Handles:
    - Creating connections (with credential encryption)
    - Listing connections (credentials never returned)
    - Testing connection reachability
    - Triggering schema crawl + Pinecone embedding
    - Deleting connections (cascades to schema_snapshots)

Security invariants maintained throughout:
    - Plaintext passwords exist only in memory during test/crawl
    - Encrypted ciphertext is the only form stored in DB
    - Passwords are never included in any return value
"""

import time
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectionConfig, get_connector
from app.core.rag.schema_embedder import SchemaEmbedder
from app.crawlers.schema_crawler import SchemaCrawler
from app.models.database_connection import DatabaseConnection
from app.models.schema_snapshot import SchemaSnapshot
from app.schemas.connection import ConnectionCreateRequest
from app.utils.crypto import encrypt_credential, decrypt_credential
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionService:
    """
    Manages the lifecycle of registered database connections.

    Usage:
        service = ConnectionService(db_session)
        conn = await service.create(request, org_id, user_id)
        result = await service.test(connection_id, org_id)
        crawl = await service.crawl(connection_id, org_id)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(
        self,
        request: ConnectionCreateRequest,
        org_id: uuid.UUID,
        created_by: uuid.UUID,
    ) -> DatabaseConnection:
        """
        Register a new database connection.

        Encrypts the password before storage.
        Does NOT test the connection or crawl schema — those are
        separate explicit actions the user triggers.

        Args:
            request:    Validated connection create request.
            org_id:     Organization that owns this connection.
            created_by: User registering this connection.

        Returns:
            The created DatabaseConnection model instance.
        """
        # Encrypt password if provided
        encrypted_password = None
        if request.password:
            encrypted_password = encrypt_credential(request.password)
            logger.debug("connection_password_encrypted")

        connection = DatabaseConnection(
            org_id=org_id,
            created_by=created_by,
            name=request.name,
            description=request.description,
            db_type=request.db_type,
            host=request.host,
            port=request.port,
            database_name=request.database_name,
            username=request.username,
            encrypted_password=encrypted_password,
            extra_config=request.extra_config or {},
            is_active=True,
            is_verified=False,
            crawl_status="pending",
        )

        self.db.add(connection)
        await self.db.commit()
        await self.db.refresh(connection)

        logger.info(
            "connection_created",
            connection_id=str(connection.id),
            name=connection.name,
            db_type=connection.db_type,
            org_id=str(org_id),
        )

        return connection

    async def list_connections(
        self,
        org_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> tuple[list[DatabaseConnection], int]:
        """
        List all database connections for an organization.

        Args:
            org_id:           Organization to list connections for.
            include_inactive: If True, include soft-deleted connections.

        Returns:
            Tuple of (connections list, total count).
        """
        query = select(DatabaseConnection).where(
            DatabaseConnection.org_id == org_id
        )

        if not include_inactive:
            query = query.where(DatabaseConnection.is_active == True)

        query = query.order_by(DatabaseConnection.created_at.desc())

        result = await self.db.execute(query)
        connections = result.scalars().all()

        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(DatabaseConnection).where(
                DatabaseConnection.org_id == org_id
            )
        )
        total = count_result.scalar() or 0

        return list(connections), total

    async def get(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> DatabaseConnection | None:
        """
        Get a single connection by ID, scoped to the organization.

        Returns None if not found or belongs to a different org.
        """
        result = await self.db.execute(
            select(DatabaseConnection).where(
                DatabaseConnection.id == connection_id,
                DatabaseConnection.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def test(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> dict:
        """
        Test if a registered connection is reachable.

        Decrypts credentials in memory, attempts connection,
        runs SELECT 1, discards plaintext immediately.

        Args:
            connection_id: Connection to test.
            org_id:        Organization context for access control.

        Returns:
            Dict with is_reachable, message, and latency_ms.
        """
        connection = await self.get(connection_id, org_id)
        if not connection:
            return {
                "connection_id": str(connection_id),
                "is_reachable": False,
                "message": "Connection not found",
                "latency_ms": None,
            }

        config = self._build_config(connection)
        start = time.monotonic()

        try:
            async with get_connector(config) as connector:
                is_alive = await connector.test_connection()

            latency_ms = round((time.monotonic() - start) * 1000, 2)

            if is_alive:
                # Mark as verified in DB
                connection.is_verified = True
                await self.db.commit()

                logger.info(
                    "connection_test_passed",
                    connection_id=str(connection_id),
                    latency_ms=latency_ms,
                )
                return {
                    "connection_id": str(connection_id),
                    "is_reachable": True,
                    "message": f"Connection successful to {connection.name}",
                    "latency_ms": latency_ms,
                }
            else:
                return {
                    "connection_id": str(connection_id),
                    "is_reachable": False,
                    "message": "Connection test failed — check credentials and network access",
                    "latency_ms": latency_ms,
                }

        except Exception as e:
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.warning(
                "connection_test_exception",
                connection_id=str(connection_id),
                error=str(e),
            )
            return {
                "connection_id": str(connection_id),
                "is_reachable": False,
                "message": f"Connection error: {str(e)[:200]}",
                "latency_ms": latency_ms,
            }

    async def crawl(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> dict:
        """
        Trigger a schema crawl and Pinecone embedding for a connection.

        Steps:
            1. Crawl schema (save to schema_snapshots)
            2. Load all snapshots for this connection
            3. Embed into Pinecone

        Args:
            connection_id: Connection to crawl.
            org_id:        Organization context.

        Returns:
            Dict with table_count, column_count, embedded_count, status.
        """
        connection = await self.get(connection_id, org_id)
        if not connection:
            return {
                "connection_id": str(connection_id),
                "table_count": 0,
                "column_count": 0,
                "embedded_count": 0,
                "status": "failed",
                "error": "Connection not found",
            }

        # Step 1: Crawl schema
        crawler = SchemaCrawler(self.db)
        crawl_result = await crawler.crawl(connection_id)

        if crawl_result["status"] != "completed":
            return {
                "connection_id": str(connection_id),
                "table_count": 0,
                "column_count": 0,
                "embedded_count": 0,
                "status": "failed",
                "error": crawl_result.get("error", "Schema crawl failed"),
            }

        # Step 2: Load snapshots
        rows = await self.db.execute(
            select(SchemaSnapshot).where(
                SchemaSnapshot.connection_id == connection_id
            )
        )
        snapshots = rows.scalars().all()

        snapshot_dicts = [
            {
                "table_name": s.table_name,
                "table_schema": s.table_schema,
                "column_name": s.column_name,
                "data_type": s.data_type,
                "is_nullable": s.is_nullable,
                "is_primary_key": s.is_primary_key,
                "is_foreign_key": s.is_foreign_key,
                "fk_references": s.fk_references,
                "snapshot_id": str(s.id),
            }
            for s in snapshots
        ]

        # Step 3: Embed into Pinecone
        embedder = SchemaEmbedder()
        embed_result = await embedder.embed_connection_schema(
            connection_id=connection_id,
            org_id=org_id,
            snapshots=snapshot_dicts,
        )

        logger.info(
            "connection_crawl_completed",
            connection_id=str(connection_id),
            table_count=crawl_result["table_count"],
            column_count=crawl_result["column_count"],
            embedded_count=embed_result["embedded_count"],
        )

        return {
            "connection_id": str(connection_id),
            "table_count": crawl_result["table_count"],
            "column_count": crawl_result["column_count"],
            "embedded_count": embed_result["embedded_count"],
            "status": "completed" if embed_result["status"] == "success" else "partial",
            "error": embed_result.get("error"),
        }

    async def delete(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> bool:
        """
        Soft-delete a connection by setting is_active=False.

        Schema snapshots are NOT deleted — they remain for audit history.
        Pinecone vectors are deleted since they're no longer needed.

        Args:
            connection_id: Connection to delete.
            org_id:        Organization context.

        Returns:
            True if deleted, False if not found.
        """
        connection = await self.get(connection_id, org_id)
        if not connection:
            return False

        # Delete Pinecone vectors for this connection
        try:
            embedder = SchemaEmbedder()
            await embedder._delete_connection_vectors(connection_id)
        except Exception as e:
            logger.warning(
                "pinecone_delete_on_connection_delete_failed",
                connection_id=str(connection_id),
                error=str(e),
            )

        # Soft delete
        connection.is_active = False
        await self.db.commit()

        logger.info(
            "connection_deleted",
            connection_id=str(connection_id),
            name=connection.name,
        )
        return True

    def _build_config(self, connection: DatabaseConnection) -> ConnectionConfig:
        """Build ConnectionConfig from a DatabaseConnection model."""
        plaintext_password = None
        if connection.encrypted_password:
            try:
                plaintext_password = decrypt_credential(connection.encrypted_password)
            except Exception as e:
                logger.error(
                    "credential_decrypt_failed",
                    connection_id=str(connection.id),
                    error=str(e),
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