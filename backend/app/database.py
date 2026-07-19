"""
Async database engine and session management.

SQLAlchemy 2.0 async engine with connection pooling.
Every request receives a session via FastAPI's dependency injection.
Sessions are automatically committed on success and rolled back on error.

Architecture note:
    Engine → creates → Sessions → used by → Repository/Service layers
    The engine is a singleton created once at startup.
    Sessions are created per-request and always cleaned up.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.utils.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)


# ------------------------------------------------------------------ #
# Engine
# ------------------------------------------------------------------ #

engine = create_async_engine(
    settings.database_url,
    # How many connections to keep open in the pool at all times
    pool_size=10,
    # How many extra connections to allow when pool_size is exhausted
    max_overflow=20,
    # Seconds to wait for a connection from the pool before raising
    pool_timeout=30,
    # Recycle connections older than this many seconds
    # (prevents stale connections from causing errors)
    pool_recycle=1800,
    # Log all SQL statements in development only
    echo=settings.is_development,
)

# ------------------------------------------------------------------ #
# Session factory
# ------------------------------------------------------------------ #

AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    # Do not commit automatically — we commit explicitly
    autocommit=False,
    # Do not flush automatically — we control when DB writes happen
    autoflush=False,
    # Close (return to pool) when context manager exits
    expire_on_commit=False,
)


# ------------------------------------------------------------------ #
# Base model class
# ------------------------------------------------------------------ #

class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy ORM models.

    All models inherit from this class:
        class User(Base):
            __tablename__ = "users"
            ...
    """
    pass


# ------------------------------------------------------------------ #
# Dependency
# ------------------------------------------------------------------ #

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage in a route:
        @router.get("/users")
        async def list_users(db: AsyncSession = Depends(get_db)):
            ...

    The session is:
    - Committed if the handler returns successfully
    - Rolled back if any exception is raised
    - Always returned to the connection pool afterward
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()