"""
Authentication API endpoints + JWT dependency.

POST /api/v1/auth/register  → Create account
POST /api/v1/auth/login     → Get tokens
POST /api/v1/auth/refresh   → Rotate tokens
POST /api/v1/auth/logout    → Revoke refresh token
GET  /api/v1/auth/me        → Get current user info

JWT dependency:
    get_current_user() is injected into protected routes.
    Replaces the dev header approach from earlier milestones.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt_handler import (
    TokenError,
    TokenExpiredError,
    verify_access_token,
    extract_user_id,
)
from app.database import get_db
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    RefreshResponse,
)
from app.services.auth_service import AuthError, AuthService
from app.utils.logger import get_logger
from app.utils.response import error_response, success_response

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


# ------------------------------------------------------------------ #
# JWT dependency — inject into protected routes
# ------------------------------------------------------------------ #

async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
) -> dict:
    """
    FastAPI dependency that validates JWT and returns user context.

    Extracts Bearer token from Authorization header,
    verifies signature and expiry, returns decoded payload.

    Usage in route handlers:
        @router.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user_id": user["sub"]}

    Raises:
        HTTPException 401: If token missing, invalid, or expired.
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "MISSING_TOKEN",
                "message": "Authorization header required",
            },
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_TOKEN_FORMAT",
                "message": "Authorization header must be 'Bearer <token>'",
            },
        )

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = verify_access_token(token)
        return payload
    except TokenExpiredError:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "TOKEN_EXPIRED",
                "message": "Access token expired. Use refresh token to get a new one.",
            },
        )
    except TokenError as e:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "INVALID_TOKEN",
                "message": str(e),
            },
        )


# Convenience type alias for route handlers
CurrentUser = Annotated[dict, Depends(get_current_user)]


# ------------------------------------------------------------------ #
# Auth endpoints
# ------------------------------------------------------------------ #

@router.post("/register", summary="Register a new account")
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new user account and default organization.

    Returns access + refresh tokens on success.
    Password must meet strength requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    """
    service = AuthService(db)
    try:
        result = await service.register(
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            org_name=request.org_name,
        )
        return success_response(data=result, status_code=201)
    except AuthError as e:
        return error_response(
            code=e.code,
            message=e.message,
            status_code=400,
        )


@router.post("/login", summary="Login and get tokens")
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate with email and password.

    Returns access token (60min) and refresh token (7 days).
    Access token goes in Authorization header for API calls.
    Refresh token is used only to get new access tokens.
    """
    service = AuthService(db)
    try:
        # Extract IP and user-agent for refresh token record
        ip_address = http_request.client.host if http_request.client else None
        device_info = http_request.headers.get("user-agent", "")[:200]

        result = await service.login(
            email=request.email,
            password=request.password,
            ip_address=ip_address,
            device_info=device_info,
        )
        return success_response(data=result)
    except AuthError as e:
        return error_response(
            code=e.code,
            message=e.message,
            status_code=401,
        )


@router.post("/refresh", summary="Refresh access token")
async def refresh_token(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Exchange a valid refresh token for a new access + refresh token pair.

    The old refresh token is revoked (token rotation).
    Store the new refresh token — the old one will no longer work.
    """
    service = AuthService(db)
    try:
        result = await service.refresh(request.refresh_token)
        return success_response(data=result)
    except AuthError as e:
        status = 401 if e.code in ("TOKEN_EXPIRED", "TOKEN_REVOKED") else 400
        return error_response(
            code=e.code,
            message=e.message,
            status_code=status,
        )


@router.post("/logout", summary="Logout current session")
async def logout(
    request: LogoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke the provided refresh token.

    The access token will continue to work until it expires (60min).
    For immediate access revocation, use short-lived access tokens.
    """
    service = AuthService(db)
    await service.logout(request.refresh_token)
    # Always return success — don't reveal if token existed
    return success_response(data={"message": "Logged out successfully"})


@router.get("/me", summary="Get current user info")
async def get_me(current_user: CurrentUser):
    """
    Return the authenticated user's info from the JWT payload.

    No database query needed — info is embedded in the token.
    """
    return success_response(data={
        "user_id": current_user.get("sub"),
        "email":   current_user.get("email"),
        "role":    current_user.get("role"),
        "org_id":  current_user.get("org_id"),
    })