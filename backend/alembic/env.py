"""
Alembic migration environment.

Uses a synchronous SQLAlchemy engine since Alembic's migration
runner is inherently synchronous. We use psycopg2 (sync driver)
here — asyncpg is only used by the FastAPI application at runtime.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.database import Base
from app.config import get_settings

# Import all models so Alembic can detect them
import app.models  # noqa: F401

# ------------------------------------------------------------------ #
# Alembic config object
# ------------------------------------------------------------------ #
config = context.config

# ------------------------------------------------------------------ #
# Inject database URL from settings
#
# Replace asyncpg driver with psycopg2 for synchronous Alembic use.
# asyncpg is async-only and cannot be used by Alembic's sync runner.
# ------------------------------------------------------------------ #
settings = get_settings()

sync_url = settings.database_url.replace(
    "postgresql+asyncpg://",
    "postgresql+psycopg2://"
)
config.set_main_option("sqlalchemy.url", sync_url)

# ------------------------------------------------------------------ #
# Configure logging from alembic.ini
# ------------------------------------------------------------------ #
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ------------------------------------------------------------------ #
# Target metadata — all our models
# ------------------------------------------------------------------ #
target_metadata = Base.metadata


# ------------------------------------------------------------------ #
# Offline mode
# ------------------------------------------------------------------ #
def run_migrations_offline() -> None:
    """Generate SQL script without connecting to the database."""
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_server_default=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ------------------------------------------------------------------ #
# Online mode
# ------------------------------------------------------------------ #
def run_migrations_online() -> None:
    """Connect to the database and apply migrations directly."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_server_default=True,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ------------------------------------------------------------------ #
# Entry point
# ------------------------------------------------------------------ #
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()