"""
Query API endpoints — async task pattern.

POST /api/v1/query          → Submit task, return task_id (202)
GET  /api/v1/query/{task_id} → Poll for result
GET  /api/v1/query/history  → Paginated query history
"""

import uuid
from typing import Annotated

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.tasks.celery_app import celery_app
from app.tasks.query_tasks import execute_query_task
from app.utils.logger import get_logger
from app.utils.response import error_response, success_response

logger = get_logger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Dev auth helper (replaced by JWT in Milestone 13)
# ------------------------------------------------------------------ #

def get_dev_user_context(
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_email: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
    x_org_name: Annotated[str | None, Header()] = None,
) -> dict:
    return {
        "user_id": x_user_id or str(uuid.uuid4()),
        "user_email": x_user_email or "dev@neurosql.local",
        "user_role": x_user_role or "analyst",
        "org_id": x_org_id or "00000000-0000-0000-0000-000000000001",
        "org_name": x_org_name or "Development Organization",
    }


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@router.post(
    "/query",
    summary="Submit a natural language query",
    tags=["Query"],
)
async def submit_query(
    request: dict,
    user_context: dict = Depends(get_dev_user_context),
):
    """
    Submit a natural language query for async execution.

    Returns a task_id immediately (202 Accepted).
    Poll GET /query/{task_id} for the result.

    Request body:
        natural_language_query: str
        connection_id: UUID string
        skip_dry_run: bool (optional, default false)
    """
    natural_language_query = request.get("natural_language_query", "").strip()
    connection_id = request.get("connection_id")
    skip_dry_run = request.get("skip_dry_run", False)

    if not natural_language_query:
        return error_response(
            code="INVALID_REQUEST",
            message="natural_language_query is required",
            status_code=400,
        )

    if not connection_id:
        return error_response(
            code="INVALID_REQUEST",
            message="connection_id is required",
            status_code=400,
        )

    logger.info(
        "query_submitted",
        query=natural_language_query[:100],
        connection_id=str(connection_id),
        user_email=user_context["user_email"],
    )

    # Submit to Celery worker — returns immediately with task_id
    task = execute_query_task.delay(
        natural_language_query=natural_language_query,
        connection_id=str(connection_id),
        user_id=user_context["user_id"],
        org_id=user_context["org_id"],
        user_email=user_context["user_email"],
        user_role=user_context["user_role"],
        org_name=user_context["org_name"],
        skip_dry_run=skip_dry_run,
    )

    return success_response(
        data={
            "task_id": task.id,
            "status": "pending",
            "message": "Query submitted. Poll GET /api/v1/query/{task_id} for result.",
        },
        status_code=202,
    )


@router.get(
    "/query/{task_id}",
    summary="Poll for query result",
    tags=["Query"],
)
async def get_query_result(task_id: str):
    """
    Poll for the result of an async query task.

    Status values:
        pending   → task queued, not yet started
        started   → task is currently executing
        complete  → task finished successfully
        failed    → task failed with an error

    Poll every 2 seconds until status is 'complete' or 'failed'.
    """
    task_result = AsyncResult(task_id, app=celery_app)

    if task_result.state == "PENDING":
        return success_response(data={
            "task_id": task_id,
            "status": "pending",
            "result": None,
        })

    elif task_result.state == "STARTED":
        meta = task_result.info or {}
        return success_response(data={
            "task_id": task_id,
            "status": "started",
            "message": meta.get("status", "processing"),
            "result": None,
        })

    elif task_result.state == "SUCCESS":
        result = task_result.result
        return success_response(data={
            "task_id": task_id,
            "status": "complete",
            "result": result,
        })

    elif task_result.state == "FAILURE":
        return success_response(data={
            "task_id": task_id,
            "status": "failed",
            "error": str(task_result.info),
            "result": None,
        })

    else:
        return success_response(data={
            "task_id": task_id,
            "status": task_result.state.lower(),
            "result": None,
        })


@router.get(
    "/query/history",
    summary="Get query history",
    tags=["Query"],
)
async def get_query_history(
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """Return paginated query history from audit_logs."""
    from sqlalchemy import select, func
    from app.models.audit_log import AuditLog

    page_size = min(page_size, 100)
    offset = (page - 1) * page_size

    user_id_str = user_context["user_id"]
    try:
        user_uuid = uuid.UUID(user_id_str)
    except (ValueError, AttributeError):
        user_uuid = uuid.uuid4()

    count_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.user_id == user_uuid
        )
    )
    total = count_result.scalar() or 0

    logs_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_uuid)
        .order_by(AuditLog.requested_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    logs = logs_result.scalars().all()

    items = [{
        "id": str(log.id),
        "natural_language_query": log.natural_language_query,
        "generated_sql": log.generated_sql,
        "intent_classification": log.intent_classification,
        "status": log.status,
        "execution_time_ms": log.execution_time_ms,
        "result_row_count": log.result_row_count,
        "was_self_corrected": log.was_self_corrected,
        "correction_attempts": log.correction_attempts,
        "requested_at": log.requested_at.isoformat() if log.requested_at else None,
        "connection_name": log.connection_name,
    } for log in logs]

    return success_response(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })