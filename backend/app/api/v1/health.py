"""
Health check endpoint.

GET /api/v1/health performs a deep health check:
- Verifies database connectivity with a lightweight query
- Verifies Redis connectivity with a PING command
- Reports individual component status

Used by:
- Docker Compose healthcheck directives
- Load balancers for traffic routing decisions
- Monitoring systems for alerting
"""

import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.utils.logger import get_logger
from app.utils.response import error_response, success_response

router = APIRouter()
settings = get_settings()
logger = get_logger(__name__)


@router.get("/health", tags=["System"])
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Deep health check for all system dependencies.

    Returns 200 if all systems are healthy.
    Returns 503 if any critical dependency is unreachable.

    Response format:
    {
        "status": "healthy" | "degraded",
        "components": {
            "database": {"status": "healthy", "latency_ms": 2},
            "redis":    {"status": "healthy", "latency_ms": 1},
        }
    }
    """
    components = {}
    overall_healthy = True

    # ------------------------------------------------------------------ #
    # Check 1: PostgreSQL metadata database
    # ------------------------------------------------------------------ #
    try:
        start = time.monotonic()
        # SELECT 1 is the lightest possible query — just tests connectivity
        await db.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        components["database"] = {
            "status": "healthy",
            "latency_ms": latency_ms,
        }
        logger.debug("health_check_db_ok", latency_ms=latency_ms)
    except Exception as e:
        components["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        overall_healthy = False
        logger.error("health_check_db_failed", error=str(e))

    # ------------------------------------------------------------------ #
    # Check 2: Redis
    # ------------------------------------------------------------------ #
    try:
        start = time.monotonic()
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.aclose()
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        components["redis"] = {
            "status": "healthy",
            "latency_ms": latency_ms,
        }
        logger.debug("health_check_redis_ok", latency_ms=latency_ms)
    except Exception as e:
        components["redis"] = {
            "status": "unhealthy",
            "error": str(e),
        }
        overall_healthy = False
        logger.error("health_check_redis_failed", error=str(e))

    # ------------------------------------------------------------------ #
    # Build response
    # ------------------------------------------------------------------ #
    status = "healthy" if overall_healthy else "degraded"
    response_data = {
        "status": status,
        "environment": settings.app_env,
        "version": "1.0.0",
        "components": components,
    }

    if not overall_healthy:
        logger.warning("health_check_degraded", components=components)
        return error_response(
            code="SERVICE_DEGRADED",
            message="One or more system components are unhealthy.",
            status_code=503,
            detail=response_data,
        )

    return success_response(data=response_data)