"""
Application configuration.

Pydantic Settings reads values from environment variables automatically.
All configuration for the entire application lives here — never call
os.getenv() directly anywhere else in the codebase.
"""

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object.

    Pydantic reads each field from the matching environment variable.
    Field names are case-insensitive: 'app_name' matches APP_NAME.
    """

    model_config = SettingsConfigDict(
        env_file="backend/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # silently ignore unknown env vars
    )

    # ------------------------------------------------------------------ #
    # Application
    # ------------------------------------------------------------------ #
    app_name: str = Field(default="NeuroSQL")
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    secret_key: str = Field(...)  # ... means required — app will not start without it
    api_v1_prefix: str = Field(default="/api/v1")

    # ------------------------------------------------------------------ #
    # JWT
    # ------------------------------------------------------------------ #
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=60)
    jwt_refresh_token_expire_days: int = Field(default=7)

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    database_url: str = Field(...)

    # ------------------------------------------------------------------ #
    # Redis
    # ------------------------------------------------------------------ #
    redis_url: str = Field(default="redis://redis:6379/0")

    # ------------------------------------------------------------------ #
    # OpenAI
    # ------------------------------------------------------------------ #
    openai_api_key: str = Field(...)
    openai_model: str = Field(default="gpt-4o")
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    # ------------------------------------------------------------------ #
    # Pinecone
    # ------------------------------------------------------------------ #
    pinecone_api_key: str = Field(...)
    pinecone_index_name: str = Field(default="neurosql")
    pinecone_environment: str = Field(default="us-east-1")
    pinecone_use_hosted_embedding: bool = Field(default=True)

    # ------------------------------------------------------------------ #
    # Encryption
    # ------------------------------------------------------------------ #
    credential_encryption_key: str = Field(...)

    # ------------------------------------------------------------------ #
    # Celery
    # ------------------------------------------------------------------ #
    celery_broker_url: str = Field(default="redis://redis:6379/1")
    celery_result_backend: str = Field(default="redis://redis:6379/2")

    # ------------------------------------------------------------------ #
    # RBAC defaults
    # ------------------------------------------------------------------ #
    default_org_name: str = Field(default="Default Organization")
    super_admin_email: str = Field(default="admin@neurosql.dev")
    super_admin_password: str = Field(...)

    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Ensure app_env is one of the known values."""
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"app_env must be one of {allowed}, got '{v}'")
        return v

    @property
    def is_production(self) -> bool:
        """Convenience property used throughout the app."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached Settings instance.

    @lru_cache means this function only instantiates Settings once,
    no matter how many times it is called. Use this everywhere:

        from app.config import get_settings
        settings = get_settings()
    """
    return Settings()