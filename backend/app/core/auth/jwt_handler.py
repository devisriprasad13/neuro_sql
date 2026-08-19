"""
JWT token handler — issue and verify JSON Web Tokens.

Access tokens:  60 minutes, stateless, verified by signature
Refresh tokens: 7 days, stored in DB, can be revoked

Token payload structure:
{
    "sub":    "user-uuid",       # subject (user ID)
    "email":  "user@example.com",
    "role":   "analyst",
    "org_id": "org-uuid",
    "type":   "access" | "refresh",
    "exp":    1234567890,        # expiry unix timestamp
    "iat":    1234567890,        # issued at unix timestamp
}
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Literal

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class TokenError(Exception):
    """Raised when a token is invalid or expired."""
    pass


class TokenExpiredError(TokenError):
    """Raised specifically when a token has expired."""
    pass


def create_access_token(
    user_id: uuid.UUID,
    email: str,
    role: str,
    org_id: uuid.UUID,
) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        user_id: The user's UUID.
        email:   User's email address.
        role:    User's role in their organization.
        org_id:  Organization UUID.

    Returns:
        Signed JWT string. Valid for JWT_ACCESS_TOKEN_EXPIRE_MINUTES.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    payload = {
        "sub":    str(user_id),
        "email":  email,
        "role":   role,
        "org_id": str(org_id),
        "type":   "access",
        "exp":    expire,
        "iat":    now,
        "jti":    str(uuid.uuid4()),  # unique token ID
    }

    token = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    logger.debug(
        "access_token_created",
        user_id=str(user_id),
        expires_at=expire.isoformat(),
    )

    return token


def create_refresh_token(user_id: uuid.UUID) -> str:
    """
    Create a long-lived JWT refresh token.

    Refresh tokens contain minimal claims — only the user ID.
    The full identity is re-loaded from DB when refreshing.

    Args:
        user_id: The user's UUID.

    Returns:
        Signed JWT string. Valid for JWT_REFRESH_TOKEN_EXPIRE_DAYS.
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.jwt_refresh_token_expire_days)

    payload = {
        "sub":  str(user_id),
        "type": "refresh",
        "exp":  expire,
        "iat":  now,
        "jti":  str(uuid.uuid4()),
    }

    token = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    logger.debug(
        "refresh_token_created",
        user_id=str(user_id),
        expires_at=expire.isoformat(),
    )

    return token


def verify_access_token(token: str) -> dict:
    """
    Verify and decode a JWT access token.

    Args:
        token: The JWT string from Authorization header.

    Returns:
        Decoded payload dict with user_id, email, role, org_id.

    Raises:
        TokenExpiredError: Token has expired — frontend should refresh.
        TokenError:        Token is invalid (bad signature, wrong type, etc.)
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        # Verify this is an access token, not a refresh token
        if payload.get("type") != "access":
            raise TokenError("Invalid token type — expected access token")

        return payload

    except ExpiredSignatureError:
        raise TokenExpiredError("Access token has expired")
    except JWTError as e:
        raise TokenError(f"Invalid token: {str(e)}")


def verify_refresh_token(token: str) -> dict:
    """
    Verify and decode a JWT refresh token.

    Args:
        token: The refresh JWT string.

    Returns:
        Decoded payload with user_id (sub field).

    Raises:
        TokenExpiredError: Token has expired — user must log in again.
        TokenError:        Token is invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != "refresh":
            raise TokenError("Invalid token type — expected refresh token")

        return payload

    except ExpiredSignatureError:
        raise TokenExpiredError("Refresh token has expired — please log in again")
    except JWTError as e:
        raise TokenError(f"Invalid refresh token: {str(e)}")


def extract_user_id(payload: dict) -> uuid.UUID:
    """Extract and validate the user_id from a decoded token payload."""
    sub = payload.get("sub")
    if not sub:
        raise TokenError("Token missing subject claim")
    try:
        return uuid.UUID(sub)
    except ValueError:
        raise TokenError("Token subject is not a valid UUID")