# ================================================================== #
# NeuroSQL Backend — Dockerfile
#
# Multi-stage build:
#   Stage 1 (builder): installs all dependencies with build tools
#   Stage 2 (runtime): clean minimal image, copies compiled packages
#
# Result: ~200MB production image instead of 2GB+
# ================================================================== #


# ================================================================== #
# Stage 1 — Builder
#
# This stage has compilers and build tools.
# It exists only to compile Python packages.
# Nothing from this stage reaches production except /install.
# ================================================================== #
FROM python:3.12-slim AS builder

# Set working directory for this stage
WORKDIR /build

# Install system build dependencies
#   gcc       — C compiler required by asyncpg, cryptography
#   libpq-dev — PostgreSQL client headers required by asyncpg
#   libssl-dev — SSL headers required by cryptography package
#
# --no-install-recommends: skip suggested packages to keep image small
# rm -rf /var/lib/apt/lists/*: delete apt cache after install
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first — before copying any application code.
#
# Why? Docker layer caching.
# Each line in a Dockerfile is a cached layer.
# If requirements.txt hasn't changed, Docker skips pip install entirely.
# If you copy source code first, any code change invalidates the pip layer
# and forces a full reinstall of all packages — very slow.
COPY requirements.txt .

# Install all Python dependencies into /install
#   --prefix=/install    — install to a specific directory (not system Python)
#   --no-cache-dir       — don't cache downloads (saves ~100MB)
#   --upgrade pip        — ensure latest pip is used
RUN pip install --upgrade pip \
    && pip install \
        --prefix=/install \
        --no-cache-dir \
        -r requirements.txt


# ================================================================== #
# Stage 2 — Runtime
#
# Clean minimal image.
# Only contains: Python runtime + compiled packages + application code.
# No build tools, no compilers, no pip cache.
# ================================================================== #
FROM python:3.12-slim AS runtime

# Python environment variables
#   PYTHONDONTWRITEBYTECODE=1 — don't write .pyc files (saves disk space)
#   PYTHONUNBUFFERED=1        — flush stdout/stderr immediately (critical for logs)
#   PYTHONPATH                — tells Python where to find our app module
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/home/neurosql/app

# Install only runtime system libraries (not build tools)
#   libpq5 — PostgreSQL client runtime library (asyncpg needs this at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------------ #
# Security: create and use a non-root user
#
# Running as root inside a container means if an attacker exploits
# your application, they get root access to the container.
# Running as a non-root user limits the blast radius.
# ------------------------------------------------------------------ #
RUN useradd \
    --create-home \
    --shell /bin/bash \
    --uid 1000 \
    neurosql

# Set working directory to the app's home
WORKDIR /home/neurosql/app

# Copy compiled Python packages from builder stage
# /install contains all packages installed by pip
COPY --from=builder /install /usr/local

# Copy application source code
# --chown: set file ownership to our non-root user
COPY --chown=neurosql:neurosql app/ ./app/
COPY --chown=neurosql:neurosql alembic/ ./alembic/
COPY --chown=neurosql:neurosql alembic.ini ./alembic.ini

# Switch to non-root user for all subsequent commands
# and for the running container
USER neurosql

# Document which port the application listens on
# (does not actually publish the port — that's done in docker-compose.yml)
EXPOSE 8000

# ------------------------------------------------------------------ #
# Health check
#
# Docker will run this command every 30 seconds.
# If it fails 3 times consecutively, Docker marks the container
# as unhealthy and can restart it automatically.
# ------------------------------------------------------------------ #
HEALTHCHECK \
    --interval=30s \
    --timeout=10s \
    --start-period=40s \
    --retries=3 \
    CMD python -c "\
import urllib.request; \
urllib.request.urlopen('http://localhost:8000/api/v1/health')"

# ------------------------------------------------------------------ #
# Start command
#
# uvicorn: production ASGI server for FastAPI
#   app.main:app     — import path to the FastAPI instance
#   --host 0.0.0.0   — listen on all interfaces (required inside Docker)
#   --port 8000      — port to listen on
#   --reload         — restart on code changes (development only)
#                      remove --reload in production
# ------------------------------------------------------------------ #
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--reload"]