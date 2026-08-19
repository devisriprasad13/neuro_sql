"""
Connection management API endpoints.

POST   /api/v1/connections              → Register a new DB connection
GET    /api/v1/connections              → List all connections for this org
GET    /api/v1/connections/{id}         → Get single connection details
DELETE /api/v1/connections/{id}         → Soft-delete a connection
POST   /api/v1/connections/{id}/test    → Test connection reachability
POST   /api/v1/connections/{id}/crawl   → Trigger schema crawl + embedding
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.connection import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    CrawlResponse,
)
from app.services.connection_service import ConnectionService
from app.utils.logger import get_logger
from app.utils.response import error_response, success_response

logger = get_logger(__name__)
router = APIRouter()


# ------------------------------------------------------------------ #
# Dev auth helper (replaced by JWT in Milestone 13)
# ------------------------------------------------------------------ #

def get_dev_user_context(
    x_user_id: Annotated[str | None, Header()] = None,
    x_org_id: Annotated[str | None, Header()] = None,
) -> dict:
    return {
        "user_id": uuid.UUID(x_user_id) if x_user_id else uuid.uuid4(),
        "org_id": uuid.UUID(x_org_id) if x_org_id else uuid.UUID(
            "00000000-0000-0000-0000-000000000001"
        ),
    }


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@router.post(
    "/connections",
    summary="Register a new database connection",
    tags=["Connections"],
)
async def create_connection(
    request: ConnectionCreateRequest,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """
    Register a new target database connection.

    Credentials are encrypted with AES-256-GCM before storage.
    The password is never returned in any response.
    Use POST /connections/{id}/test to verify the connection works.
    """
    service = ConnectionService(db)
    connection = await service.create(
        request=request,
        org_id=user_context["org_id"],
        created_by=user_context["user_id"],
    )

    return success_response(
        data=ConnectionResponse.model_validate(connection).model_dump(mode="json"),
        status_code=201,
    )


@router.get(
    "/connections",
    summary="List all database connections",
    tags=["Connections"],
)
async def list_connections(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """List all registered database connections for this organization."""
    service = ConnectionService(db)
    connections, total = await service.list_connections(
        org_id=user_context["org_id"],
        include_inactive=include_inactive,
    )

    return success_response(data={
        "connections": [
            ConnectionResponse.model_validate(c).model_dump(mode="json")
            for c in connections
        ],
        "total": total,
    })


@router.get(
    "/connections/{connection_id}",
    summary="Get a single connection",
    tags=["Connections"],
)
async def get_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """Get details of a single database connection."""
    service = ConnectionService(db)
    connection = await service.get(connection_id, user_context["org_id"])

    if not connection:
        return error_response(
            code="CONNECTION_NOT_FOUND",
            message=f"Connection {connection_id} not found",
            status_code=404,
        )

    return success_response(
        data=ConnectionResponse.model_validate(connection).model_dump(mode="json")
    )


@router.delete(
    "/connections/{connection_id}",
    summary="Delete a connection",
    tags=["Connections"],
)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """
    Soft-delete a database connection.

    Sets is_active=False. Schema snapshots are preserved for audit.
    Pinecone vectors for this connection are deleted.
    """
    service = ConnectionService(db)
    deleted = await service.delete(connection_id, user_context["org_id"])

    if not deleted:
        return error_response(
            code="CONNECTION_NOT_FOUND",
            message=f"Connection {connection_id} not found",
            status_code=404,
        )

    return success_response(
        data={"message": "Connection deleted successfully"},
        status_code=200,
    )


@router.post(
    "/connections/{connection_id}/test",
    summary="Test connection reachability",
    tags=["Connections"],
)
async def test_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """
    Test if a registered database connection is reachable.

    Decrypts credentials, attempts connection, runs SELECT 1.
    If successful, marks the connection as verified (is_verified=True).
    Returns latency in milliseconds.
    """
    service = ConnectionService(db)
    result = await service.test(connection_id, user_context["org_id"])

    return success_response(data=result)


@router.post(
    "/connections/{connection_id}/crawl",
    summary="Crawl schema and embed into Pinecone",
    tags=["Connections"],
)
async def crawl_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user_context: dict = Depends(get_dev_user_context),
):
    """
    Trigger a full schema crawl and Pinecone embedding for a connection.

    Steps performed:
    1. Connect to target database and read information_schema
    2. Save column metadata to schema_snapshots table
    3. Embed all columns into Pinecone using llama-text-embed-v2

    After this completes, the connection is ready for NL queries.
    """
    service = ConnectionService(db)
    result = await service.crawl(connection_id, user_context["org_id"])

    if result["status"] == "failed":
        return error_response(
            code="CRAWL_FAILED",
            message=result.get("error", "Schema crawl failed"),
            status_code=500,
            detail=result,
        )

    return success_response(data=result)