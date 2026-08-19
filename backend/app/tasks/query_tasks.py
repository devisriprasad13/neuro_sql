"""
Celery async task definitions.

Tasks run in Celery worker processes — separate from the FastAPI server.
They use asyncio.run() to execute async business logic synchronously.

Key fix: Each task creates a FRESH SQLAlchemy engine bound to its own
event loop. Cannot reuse the module-level engine — asyncpg connection
objects are bound to the event loop that created them. Reusing them
across asyncio.run() calls causes "Future attached to a different loop".
"""

import asyncio
import uuid

from celery import Task

from app.tasks.celery_app import celery_app
from app.utils.logger import get_logger

logger = get_logger(__name__)


class QueryTask(Task):
    """Base task class with structured error logging."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "celery_task_failed",
            task_id=task_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )


@celery_app.task(
    name="tasks.execute_query",
    bind=True,
    base=QueryTask,
    max_retries=0,
    queue="query",
    track_started=True,
)
def execute_query_task(
    self: Task,
    natural_language_query: str,
    connection_id: str,
    user_id: str,
    org_id: str,
    user_email: str,
    user_role: str,
    org_name: str,
    skip_dry_run: bool = False,
) -> dict:
    """
    Execute a natural language query asynchronously.

    Creates a fresh SQLAlchemy engine per task to avoid
    asyncio event loop conflicts with asyncpg.
    """
    logger.info(
        "query_task_started",
        task_id=self.request.id,
        query=natural_language_query[:100],
        connection_id=connection_id,
        user_email=user_email,
    )

    try:
        self.update_state(
            state="STARTED",
            meta={
                "status": "processing",
                "query": natural_language_query[:100],
            }
        )
    except Exception:
        pass  # task_id is None when called directly

    async def _run():
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession,
        )
        from app.config import get_settings
        from app.services.query_service import QueryService

        settings = get_settings()

        # Fresh engine bound to THIS task's event loop
        engine = create_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
        )

        SessionFactory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

        try:
            async with SessionFactory() as db:
                service = QueryService(db)
                result = await service.execute(
                    natural_language_query=natural_language_query,
                    connection_id=uuid.UUID(connection_id),
                    user_id=uuid.UUID(user_id),
                    org_id=uuid.UUID(org_id),
                    user_email=user_email,
                    user_role=user_role,
                    org_name=org_name,
                    request_id=uuid.UUID(self.request.id)
                    if self.request.id else uuid.uuid4(),
                    skip_dry_run=skip_dry_run,
                )
                return result.to_dict()
        finally:
            await engine.dispose()

    result = asyncio.run(_run())

    logger.info(
        "query_task_completed",
        task_id=self.request.id,
        success=result.get("success"),
        row_count=result.get("row_count", 0),
    )

    return result


@celery_app.task(
    name="tasks.crawl_schema",
    bind=True,
    base=QueryTask,
    max_retries=1,
    queue="schema",
    track_started=True,
)
def crawl_schema_task(
    self: Task,
    connection_id: str,
    org_id: str,
    user_email: str,
) -> dict:
    """
    Crawl schema and embed into Pinecone asynchronously.

    Creates a fresh SQLAlchemy engine per task to avoid
    asyncio event loop conflicts.
    """
    logger.info(
        "crawl_task_started",
        task_id=self.request.id,
        connection_id=connection_id,
        user_email=user_email,
    )

    self.update_state(
        state="STARTED",
        meta={
            "status": "crawling",
            "connection_id": connection_id,
        }
    )

    async def _run():
        from sqlalchemy.ext.asyncio import (
            create_async_engine,
            async_sessionmaker,
            AsyncSession,
        )
        from app.config import get_settings
        from app.services.connection_service import ConnectionService

        settings = get_settings()

        engine = create_async_engine(
            settings.database_url,
            pool_size=2,
            max_overflow=2,
        )

        SessionFactory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

        try:
            async with SessionFactory() as db:
                service = ConnectionService(db)
                result = await service.crawl(
                    connection_id=uuid.UUID(connection_id),
                    org_id=uuid.UUID(org_id),
                )
                return result
        finally:
            await engine.dispose()

    result = asyncio.run(_run())

    logger.info(
        "crawl_task_completed",
        task_id=self.request.id,
        status=result.get("status"),
        table_count=result.get("table_count", 0),
    )

    return result