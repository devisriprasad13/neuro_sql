"""
FastAPI application factory.

Creates and configures the FastAPI application instance.
All middleware, routers, and startup/shutdown events are registered here.

Usage:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health
from app.config import get_settings
from app.utils.logger import configure_logging, get_logger

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Code before 'yield' runs on startup.
    Code after 'yield' runs on shutdown.

    This replaces the deprecated @app.on_event("startup") pattern.
    """
    # --- Startup ---
    configure_logging()
    logger = get_logger(__name__)
    logger.info(
        "neurosql_starting",
        environment=settings.app_env,
        debug=settings.app_debug,
    )

    # Future milestones will add:
    # - Database table creation / migration check
    # - Pinecone index initialization
    # - RBAC permission registry loading
    # - Celery connection verification

    yield

    # --- Shutdown ---
    logger.info("neurosql_shutting_down")


def create_application() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance.
    """
    app = FastAPI(
        title="NeuroSQL",
        description="AI-powered database management platform",
        version="1.0.0",
        # Disable docs in production — never expose API docs publicly
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------ #
    # CORS middleware
    # Allows the React frontend to call the API from a different port
    # In production: restrict origins to your actual domain
    # ------------------------------------------------------------------ #
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------ #
    # Routers
    # Each router handles a specific domain of the API
    # ------------------------------------------------------------------ #
    app.include_router(
        health.router,
        prefix=settings.api_v1_prefix,
    )

    # Future milestones will register:
    # app.include_router(auth.router, prefix=settings.api_v1_prefix)
    # app.include_router(connections.router, prefix=settings.api_v1_prefix)
    # app.include_router(query.router, prefix=settings.api_v1_prefix)

    return app


# Module-level app instance — this is what uvicorn imports
app = create_application()