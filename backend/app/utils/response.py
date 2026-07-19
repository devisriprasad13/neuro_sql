"""
Standard API response builder.

Every endpoint returns a consistent envelope:
{
    "success": true/false,
    "data": {...} or null,
    "error": null or {"code": "...", "message": "...", "detail": {...}},
    "request_id": "uuid",
    "timestamp": "ISO-8601"
}

Usage:
    from app.utils.response import success_response, error_response
    return success_response(data={"user": user_dict})
    return error_response(code="NOT_FOUND", message="User not found", status_code=404)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse


def _build_envelope(
    success: bool,
    data: Any = None,
    error: dict | None = None,
    request_id: str | None = None,
) -> dict:
    """Build the standard response envelope."""
    return {
        "success": success,
        "data": data,
        "error": error,
        "request_id": request_id or str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def success_response(
    data: Any = None,
    status_code: int = 200,
    request_id: str | None = None,
) -> JSONResponse:
    """
    Return a successful API response.

    Args:
        data: The payload to return. Can be any JSON-serializable type.
        status_code: HTTP status code (default 200).
        request_id: Optional request ID to include in the response.
    """
    return JSONResponse(
        status_code=status_code,
        content=_build_envelope(
            success=True,
            data=data,
            request_id=request_id,
        ),
    )


def error_response(
    code: str,
    message: str,
    status_code: int = 400,
    detail: dict | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """
    Return an error API response.

    Args:
        code: Machine-readable error code (e.g. "RBAC_PERMISSION_DENIED").
        message: Human-readable error message for display.
        status_code: HTTP status code.
        detail: Optional structured detail dict for debugging.
        request_id: Optional request ID.
    """
    return JSONResponse(
        status_code=status_code,
        content=_build_envelope(
            success=False,
            error={
                "code": code,
                "message": message,
                "detail": detail or {},
            },
            request_id=request_id,
        ),
    )