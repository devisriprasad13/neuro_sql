"""
Query service — orchestrates the full NL→SQL→Execute pipeline.

This is the central orchestration layer that connects:
    IntentClassifier → SchemaRetriever → SelfCorrectionEngine → Connector

Called by:
    POST /api/v1/query  (route handler)
    Celery query task   (async worker)

Responsibilities:
    1. Classify NL query intent
    2. Load user's database connections
    3. Retrieve relevant schema from Pinecone
    4. Generate and validate SQL (with self-correction)
    5. Execute SQL against target database
    6. Write audit log entry
    7. Return structured result
"""

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import ConnectionConfig, get_connector
from app.core.correction import SelfCorrectionEngine
from app.core.nlp.intent_classifier import IntentClassifier, SQLOperationType
from app.core.rag.schema_retriever import SchemaRetriever
from app.models.database_connection import DatabaseConnection
from app.models.audit_log import AuditLog
from app.utils.crypto import decrypt_credential
from app.utils.logger import get_logger

logger = get_logger(__name__)


class QueryResult:
    """
    Structured result returned by QueryService.execute().

    Attributes:
        success:          True if query produced results
        sql:              The final validated SQL that was executed
        columns:          List of column names in result
        rows:             List of rows (each row is a list of values)
        row_count:        Number of rows returned
        affected_rows:    Rows modified (for write operations)
        execution_time_ms: Total pipeline time
        was_corrected:    True if self-correction was needed
        correction_attempts: How many SQL generation attempts were made
        intent:           Classified operation type (READ/INSERT/etc.)
        error:            Error message if failed
        audit_log_id:     UUID of the audit log entry created
    """

    def __init__(
        self,
        success: bool,
        sql: str = "",
        columns: list[str] | None = None,
        rows: list[list] | None = None,
        row_count: int = 0,
        affected_rows: int = 0,
        execution_time_ms: float = 0.0,
        was_corrected: bool = False,
        correction_attempts: int = 1,
        intent: str = "READ",
        error: str | None = None,
        audit_log_id: uuid.UUID | None = None,
    ) -> None:
        self.success = success
        self.sql = sql
        self.columns = columns or []
        self.rows = rows or []
        self.row_count = row_count
        self.affected_rows = affected_rows
        self.execution_time_ms = execution_time_ms
        self.was_corrected = was_corrected
        self.correction_attempts = correction_attempts
        self.intent = intent
        self.error = error
        self.audit_log_id = audit_log_id

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "affected_rows": self.affected_rows,
            "execution_time_ms": self.execution_time_ms,
            "was_corrected": self.was_corrected,
            "correction_attempts": self.correction_attempts,
            "intent": self.intent,
            "error": self.error,
            "audit_log_id": str(self.audit_log_id) if self.audit_log_id else None,
        }


class QueryService:
    """
    Orchestrates the full natural language to SQL execution pipeline.

    Usage:
        service = QueryService(db_session)
        result = await service.execute(
            natural_language_query="Show me all active users",
            connection_id=uuid,
            user_id=uuid,
            org_id=uuid,
            user_email="user@example.com",
            user_role="analyst",
            org_name="Acme Corp",
        )
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.classifier = IntentClassifier()
        self.retriever = SchemaRetriever()
        self.correction_engine = SelfCorrectionEngine()

    async def execute(
        self,
        natural_language_query: str,
        connection_id: uuid.UUID,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        user_email: str,
        user_role: str,
        org_name: str,
        request_id: uuid.UUID | None = None,
        skip_dry_run: bool = False,
    ) -> QueryResult:
        """
        Execute a natural language query end-to-end.

        Args:
            natural_language_query: The user's plain English question.
            connection_id:          Which database to query.
            user_id:                Requesting user's ID.
            org_id:                 Organization context.
            user_email:             For audit log (denormalized).
            user_role:              For audit log (denormalized).
            org_name:               For audit log (denormalized).
            request_id:             Optional request ID for tracing.
            skip_dry_run:           Skip Stage 3 validation (for testing).

        Returns:
            QueryResult with SQL, data, and execution metadata.
        """
        start_time = time.monotonic()
        request_id = request_id or uuid.uuid4()

        logger.info(
            "query_service_started",
            query=natural_language_query[:100],
            connection_id=str(connection_id),
            user_id=str(user_id),
            request_id=str(request_id),
        )

        # ------------------------------------------------------------ #
        # Step 1: Load database connection
        # ------------------------------------------------------------ #
        connection = await self._load_connection(connection_id, org_id)
        if not connection:
            return await self._fail(
                query=natural_language_query,
                error=f"Database connection {connection_id} not found or not accessible",
                user_id=user_id, org_id=org_id,
                user_email=user_email, user_role=user_role,
                org_name=org_name, request_id=request_id,
                start_time=start_time,
            )

        # ------------------------------------------------------------ #
        # Step 2: Classify intent
        # ------------------------------------------------------------ #
        try:
            intent = await self.classifier.classify(natural_language_query)
            logger.info(
                "intent_classified",
                operation=intent.operation_type.value,
                tables=intent.target_tables,
                confidence=intent.confidence,
            )
        except Exception as e:
            return await self._fail(
                query=natural_language_query,
                error=f"Intent classification failed: {str(e)}",
                user_id=user_id, org_id=org_id,
                user_email=user_email, user_role=user_role,
                org_name=org_name, request_id=request_id,
                start_time=start_time,
            )

        # ------------------------------------------------------------ #
        # Step 3: Retrieve schema context from Pinecone
        # ------------------------------------------------------------ #
        try:
            schema_context = await self.retriever.retrieve(
                query=natural_language_query,
                connection_ids=[connection_id],
                top_k=15,
            )
            schema_matches = await self.retriever.retrieve_raw(
                query=natural_language_query,
                connection_ids=[connection_id],
                top_k=15,
            )
            logger.debug(
                "schema_retrieved",
                match_count=len(schema_matches),
            )
        except Exception as e:
            logger.warning(
                "schema_retrieval_failed",
                error=str(e),
            )
            # Continue with empty schema — Stage 2 will warn
            schema_context = ""
            schema_matches = []

        # ------------------------------------------------------------ #
        # Step 4: Build connector config for dry-run and execution
        # ------------------------------------------------------------ #
        connection_config = self._build_connection_config(connection)

        # ------------------------------------------------------------ #
        # Step 5: Generate + validate SQL (with self-correction)
        # ------------------------------------------------------------ #
        correction_result = await self.correction_engine.generate_and_validate(
            query=natural_language_query,
            schema_context=schema_context,
            schema_matches=schema_matches,
            operation_type=intent.operation_type,
            db_type=connection.db_type,
            connection_config=connection_config,
            skip_dry_run=skip_dry_run,
        )

        if not correction_result.success:
            return await self._fail(
                query=natural_language_query,
                error=correction_result.final_error or "SQL generation and validation failed",
                generated_sql=correction_result.final_sql,
                intent=intent.operation_type.value,
                was_corrected=correction_result.was_corrected,
                correction_attempts=correction_result.attempts,
                user_id=user_id, org_id=org_id,
                user_email=user_email, user_role=user_role,
                org_name=org_name, request_id=request_id,
                connection_id=connection_id,
                connection_name=connection.name,
                start_time=start_time,
            )

        final_sql = correction_result.final_sql

        # ------------------------------------------------------------ #
        # Step 6: Execute SQL against target database
        # ------------------------------------------------------------ #
        try:
            async with get_connector(connection_config) as connector:
                is_read = intent.operation_type == SQLOperationType.READ
                db_result = await connector.execute_query(
                    sql=final_sql,
                    read_only=is_read,
                )

            if not db_result.success:
                return await self._fail(
                    query=natural_language_query,
                    error=db_result.error or "Query execution failed",
                    generated_sql=final_sql,
                    intent=intent.operation_type.value,
                    was_corrected=correction_result.was_corrected,
                    correction_attempts=correction_result.attempts,
                    user_id=user_id, org_id=org_id,
                    user_email=user_email, user_role=user_role,
                    org_name=org_name, request_id=request_id,
                    connection_id=connection_id,
                    connection_name=connection.name,
                    start_time=start_time,
                )

        except Exception as e:
            return await self._fail(
                query=natural_language_query,
                error=f"Execution error: {str(e)}",
                generated_sql=final_sql,
                intent=intent.operation_type.value,
                user_id=user_id, org_id=org_id,
                user_email=user_email, user_role=user_role,
                org_name=org_name, request_id=request_id,
                connection_id=connection_id,
                connection_name=connection.name,
                start_time=start_time,
            )

        # ------------------------------------------------------------ #
        # Step 7: Write audit log
        # ------------------------------------------------------------ #
        total_time = (time.monotonic() - start_time) * 1000
        audit_id = await self._write_audit_log(
            user_id=user_id,
            user_email=user_email,
            user_role=user_role,
            org_id=org_id,
            org_name=org_name,
            request_id=request_id,
            natural_language_query=natural_language_query,
            intent=intent.operation_type.value,
            generated_sql=final_sql,
            connection_id=connection_id,
            connection_name=connection.name,
            status="success",
            affected_rows=db_result.affected_rows,
            result_row_count=db_result.row_count,
            execution_time_ms=int(total_time),
            was_corrected=correction_result.was_corrected,
            correction_attempts=correction_result.attempts,
        )

        logger.info(
            "query_service_completed",
            query=natural_language_query[:100],
            sql_preview=final_sql[:80],
            row_count=db_result.row_count,
            total_time_ms=round(total_time, 2),
            was_corrected=correction_result.was_corrected,
        )

        return QueryResult(
            success=True,
            sql=final_sql,
            columns=db_result.columns,
            rows=db_result.rows,
            row_count=db_result.row_count,
            affected_rows=db_result.affected_rows,
            execution_time_ms=round(total_time, 2),
            was_corrected=correction_result.was_corrected,
            correction_attempts=correction_result.attempts,
            intent=intent.operation_type.value,
            audit_log_id=audit_id,
        )

    # ---------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------- #

    async def _load_connection(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> DatabaseConnection | None:
        """Load and verify a database connection belongs to this org."""
        result = await self.db.execute(
            select(DatabaseConnection).where(
                DatabaseConnection.id == connection_id,
                DatabaseConnection.org_id == org_id,
                DatabaseConnection.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    def _build_connection_config(
        self, connection: DatabaseConnection
    ) -> ConnectionConfig:
        """Build ConnectionConfig from a DatabaseConnection model."""
        plaintext_password = None
        if connection.encrypted_password:
            try:
                plaintext_password = decrypt_credential(
                    connection.encrypted_password
                )
            except Exception as e:
                logger.error(
                    "credential_decryption_failed",
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

    async def _write_audit_log(
        self,
        user_id: uuid.UUID,
        user_email: str,
        user_role: str,
        org_id: uuid.UUID,
        org_name: str,
        request_id: uuid.UUID,
        natural_language_query: str,
        intent: str,
        generated_sql: str,
        connection_id: uuid.UUID,
        connection_name: str,
        status: str,
        affected_rows: int = 0,
        result_row_count: int = 0,
        execution_time_ms: int = 0,
        was_corrected: bool = False,
        correction_attempts: int = 1,
        error_message: str | None = None,
        block_reason: str | None = None,
    ) -> uuid.UUID:
        """Write an immutable audit log entry."""
        try:
            audit = AuditLog(
                user_id=user_id,
                user_email=user_email,
                user_role=user_role,
                org_id=org_id,
                org_name=org_name,
                request_id=request_id,
                natural_language_query=natural_language_query,
                intent_classification=intent,
                generated_sql=generated_sql,
                connection_id=connection_id,
                connection_name=connection_name,
                status=status,
                affected_rows=affected_rows,
                result_row_count=result_row_count,
                execution_time_ms=execution_time_ms,
                was_self_corrected=was_corrected,
                correction_attempts=correction_attempts,
                error_message=error_message,
                block_reason=block_reason,
                requested_at=datetime.now(timezone.utc),
                executed_at=datetime.now(timezone.utc) if status == "success" else None,
            )
            self.db.add(audit)
            await self.db.commit()
            await self.db.refresh(audit)
            return audit.id
        except Exception as e:
            logger.error("audit_log_write_failed", error=str(e))
            return uuid.uuid4()

    async def _fail(
        self,
        query: str,
        error: str,
        user_id: uuid.UUID,
        org_id: uuid.UUID,
        user_email: str,
        user_role: str,
        org_name: str,
        request_id: uuid.UUID,
        start_time: float,
        generated_sql: str = "",
        intent: str = "READ",
        was_corrected: bool = False,
        correction_attempts: int = 1,
        connection_id: uuid.UUID | None = None,
        connection_name: str = "",
    ) -> QueryResult:
        """Record failure in audit log and return failed QueryResult."""
        total_time = (time.monotonic() - start_time) * 1000

        if connection_id:
            await self._write_audit_log(
                user_id=user_id,
                user_email=user_email,
                user_role=user_role,
                org_id=org_id,
                org_name=org_name,
                request_id=request_id,
                natural_language_query=query,
                intent=intent,
                generated_sql=generated_sql,
                connection_id=connection_id,
                connection_name=connection_name,
                status="failed",
                execution_time_ms=int(total_time),
                error_message=error,
                was_corrected=was_corrected,
                correction_attempts=correction_attempts,
            )

        logger.error(
            "query_service_failed",
            query=query[:100],
            error=error,
            total_time_ms=round(total_time, 2),
        )

        return QueryResult(
            success=False,
            sql=generated_sql,
            error=error,
            execution_time_ms=round(total_time, 2),
            intent=intent,
            was_corrected=was_corrected,
            correction_attempts=correction_attempts,
        )