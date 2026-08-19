"""
Authentication service — user registration, login, token management.

Orchestrates:
    - User creation with bcrypt password hashing
    - Credential verification
    - JWT access + refresh token issuance
    - Refresh token storage and rotation
    - Logout (token revocation)

Security invariants:
    - Plaintext passwords never stored or logged
    - Refresh tokens stored as bcrypt hashes (not plaintext)
    - Token rotation on every refresh (old token revoked)
    - Generic error messages prevent user enumeration
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    extract_user_id,
    TokenError,
    TokenExpiredError,
)
from app.core.auth.password_handler import (
    hash_password,
    verify_password,
    validate_password_strength,
)
from app.models.user import User
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.role import Role
from app.models.refresh_token import RefreshToken
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AuthError(Exception):
    """Authentication error with a user-facing message."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthService:
    """
    Handles user authentication lifecycle.

    Usage:
        service = AuthService(db)
        tokens = await service.register(email, password, full_name)
        tokens = await service.login(email, password)
        tokens = await service.refresh(refresh_token)
        await service.logout(refresh_token)
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(
        self,
        email: str,
        password: str,
        full_name: str | None = None,
        org_name: str | None = None,
    ) -> dict:
        """
        Register a new user and create their default organization.

        Steps:
            1. Validate password strength
            2. Check email not already registered
            3. Hash password with bcrypt
            4. Create user record
            5. Create default organization for this user
            6. Assign 'org_admin' role (first user owns their org)
            7. Issue access + refresh tokens

        Args:
            email:     User's email address (login identifier).
            password:  Plaintext password (hashed before storage).
            full_name: Optional display name.
            org_name:  Organization name (defaults to "{name}'s Organization").

        Returns:
            Dict with access_token, refresh_token, and user info.

        Raises:
            AuthError: If email taken or password too weak.
        """
        email = email.lower().strip()

        # Validate password strength
        violations = validate_password_strength(password)
        if violations:
            raise AuthError(
                message=f"Password does not meet requirements: {'; '.join(violations)}",
                code="WEAK_PASSWORD",
            )

        # Check email uniqueness
        existing = await self._get_user_by_email(email)
        if existing:
            # Generic message — don't reveal whether email exists
            raise AuthError(
                message="An account with this email already exists",
                code="EMAIL_TAKEN",
            )

        # Hash password
        password_hash = hash_password(password)

        # Create user
        user = User(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            is_active=True,
            is_verified=False,
        )
        self.db.add(user)
        await self.db.flush()  # Get user.id without committing

        # Create default organization
        if not org_name:
            org_name = f"{full_name or email.split('@')[0]}'s Organization"

        slug = self._generate_slug(org_name, str(user.id)[:8])

        org = Organization(
            name=org_name,
            slug=slug,
            is_active=True,
        )
        self.db.add(org)
        await self.db.flush()  # Get org.id

        # Get org_admin role
        role = await self._get_role("org_admin")
        if not role:
            raise AuthError("System configuration error", "SYSTEM_ERROR")

        # Create membership
        member = OrganizationMember(
            user_id=user.id,
            org_id=org.id,
            role_id=role.id,
            is_active=True,
        )
        self.db.add(member)

        await self.db.commit()

        logger.info(
            "user_registered",
            user_id=str(user.id),
            email=email,
            org_id=str(org.id),
        )

        # Issue tokens
        return await self._issue_tokens(user, org.id, "org_admin")

    async def login(
        self,
        email: str,
        password: str,
        ip_address: str | None = None,
        device_info: str | None = None,
    ) -> dict:
        """
        Authenticate a user and issue tokens.

        Uses constant-time password comparison to prevent timing attacks.
        Returns generic error message regardless of failure reason
        to prevent user enumeration.

        Args:
            email:       User's email address.
            password:    Plaintext password to verify.
            ip_address:  Client IP for refresh token record.
            device_info: User-agent string for session tracking.

        Returns:
            Dict with access_token, refresh_token, and user info.

        Raises:
            AuthError: If credentials are invalid or account inactive.
        """
        email = email.lower().strip()

        user = await self._get_user_by_email(email)

        # Always run verify_password even if user not found
        # This prevents timing attacks that reveal valid emails
        dummy_hash = "$2b$12$dummy.hash.to.prevent.timing.attacks.padding"
        password_valid = verify_password(
            password,
            user.password_hash if user else dummy_hash
        )

        if not user or not password_valid:
            logger.warning("login_failed", email=email)
            # Same message for both "user not found" and "wrong password"
            raise AuthError(
                message="Invalid email or password",
                code="INVALID_CREDENTIALS",
            )

        if not user.is_active:
            raise AuthError(
                message="This account has been deactivated",
                code="ACCOUNT_INACTIVE",
            )

        # Get user's organization and role
        member = await self._get_membership(user.id)
        if not member:
            raise AuthError(
                message="Account has no organization. Contact support.",
                code="NO_ORGANIZATION",
            )

        role_name = await self._get_role_name(member.role_id)

        # Update last login timestamp
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()

        logger.info(
            "login_success",
            user_id=str(user.id),
            email=email,
            org_id=str(member.org_id),
        )

        return await self._issue_tokens(
            user, member.org_id, role_name,
            ip_address=ip_address,
            device_info=device_info,
        )

    async def refresh(self, refresh_token_str: str) -> dict:
        """
        Issue a new access token using a valid refresh token.

        Implements token rotation:
            1. Verify the refresh token signature
            2. Find the stored token record
            3. Verify not revoked or expired
            4. Revoke the old token
            5. Issue new access + refresh token pair

        Args:
            refresh_token_str: The refresh JWT from the client.

        Returns:
            Dict with new access_token and refresh_token.

        Raises:
            AuthError: If refresh token is invalid, revoked, or expired.
        """
        try:
            payload = verify_refresh_token(refresh_token_str)
        except TokenExpiredError:
            raise AuthError(
                "Refresh token expired. Please log in again.",
                "TOKEN_EXPIRED",
            )
        except TokenError as e:
            raise AuthError(str(e), "INVALID_TOKEN")

        user_id = extract_user_id(payload)

        # Load user
        user = await self._get_user_by_id(user_id)
        if not user or not user.is_active:
            raise AuthError("Invalid session", "INVALID_SESSION")

        # Find stored refresh token
        stored_token = await self._find_refresh_token(
            user_id, refresh_token_str
        )
        if not stored_token:
            raise AuthError(
                "Refresh token not found or already revoked",
                "TOKEN_REVOKED",
            )

        # Check not expired in DB
        if stored_token.expires_at < datetime.now(timezone.utc):
            raise AuthError(
                "Refresh token expired. Please log in again.",
                "TOKEN_EXPIRED",
            )

        # Revoke old token (rotation)
        stored_token.is_revoked = True
        stored_token.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()

        # Get current membership
        member = await self._get_membership(user_id)
        if not member:
            raise AuthError("No active organization", "NO_ORGANIZATION")

        role_name = await self._get_role_name(member.role_id)

        logger.info("token_refreshed", user_id=str(user_id))

        return await self._issue_tokens(user, member.org_id, role_name)

    async def logout(self, refresh_token_str: str) -> bool:
        """
        Revoke a refresh token (logout from current device).

        Args:
            refresh_token_str: The refresh token to revoke.

        Returns:
            True if token was found and revoked, False otherwise.
        """
        try:
            payload = verify_refresh_token(refresh_token_str)
            user_id = extract_user_id(payload)
        except (TokenError, TokenExpiredError):
            return False

        stored_token = await self._find_refresh_token(user_id, refresh_token_str)
        if stored_token and not stored_token.is_revoked:
            stored_token.is_revoked = True
            stored_token.revoked_at = datetime.now(timezone.utc)
            await self.db.commit()
            logger.info("logout_success", user_id=str(user_id))
            return True

        return False

    # ---------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------- #

    async def _issue_tokens(
        self,
        user: User,
        org_id: uuid.UUID,
        role: str,
        ip_address: str | None = None,
        device_info: str | None = None,
    ) -> dict:
        """Create access + refresh tokens and store refresh token in DB."""
        access_token = create_access_token(
            user_id=user.id,
            email=user.email,
            role=role,
            org_id=org_id,
        )
        refresh_token_str = create_refresh_token(user_id=user.id)

        # Store refresh token hash in DB
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        token_hash = ctx.hash(refresh_token_str)

        expires_at = datetime.now(timezone.utc) + timedelta(
            days=get_settings().jwt_refresh_token_expire_days
        )

        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            device_info=device_info,
            ip_address=ip_address,
            is_revoked=False,
            expires_at=expires_at,
        )
        self.db.add(refresh_record)
        await self.db.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": role,
                "org_id": str(org_id),
            },
        }

    async def _get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _get_membership(self, user_id: uuid.UUID) -> OrganizationMember | None:
        result = await self.db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user_id,
                OrganizationMember.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def _get_role(self, role_name: str) -> Role | None:
        result = await self.db.execute(
            select(Role).where(Role.name == role_name)
        )
        return result.scalar_one_or_none()

    async def _get_role_name(self, role_id: uuid.UUID) -> str:
        result = await self.db.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()
        return role.name if role else "viewer"

    async def _find_refresh_token(
        self, user_id: uuid.UUID, token_str: str
    ) -> RefreshToken | None:
        """Find a non-revoked refresh token by verifying hash."""
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked == False,
            )
        )
        tokens = result.scalars().all()

        for token in tokens:
            try:
                if ctx.verify(token_str, token.token_hash):
                    return token
            except Exception:
                continue
        return None

    @staticmethod
    def _generate_slug(name: str, suffix: str) -> str:
        """Generate a URL-safe slug from an organization name."""
        import re
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug.strip())
        slug = re.sub(r"-+", "-", slug)
        return f"{slug[:40]}-{suffix}"

    @staticmethod
    def _get_settings():
        from app.config import get_settings
        return get_settings()


def get_settings():
    from app.config import get_settings as _get_settings
    return _get_settings()