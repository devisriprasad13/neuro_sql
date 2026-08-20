# ================================================================== #
# NeuroSQL Backend — Multi-stage Dockerfile
#
# Stage 1 (builder): Install all Python dependencies
# Stage 2 (runtime): Minimal production image
#
# Why multi-stage?
#   Build tools (gcc, libpq-dev) are needed to compile C extensions
#   but must NOT be in the production image — security and size.
#   Builder: ~800MB. Runtime: ~200MB.
# ================================================================== #

# ------------------------------------------------------------------ #
# Stage 1: Builder — install Python packages with build tools
# ------------------------------------------------------------------ #
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools needed to compile C extensions:
#   gcc:       compiler for asyncpg, cryptography
#   libpq-dev: PostgreSQL headers for psycopg2
#   libssl-dev: OpenSSL headers for cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install to /install so we can copy just the packages in stage 2
RUN pip install --upgrade pip \
    && pip install \
        --prefix=/install \
        --no-cache-dir \
        -r requirements.txt

# ------------------------------------------------------------------ #
# Stage 2: Runtime — minimal production image
# ------------------------------------------------------------------ #
FROM python:3.12-slim AS runtime

# Install only runtime libraries (not build tools):
#   libpq5: PostgreSQL client library (runtime only, not dev headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
# Running as root inside containers is a security risk:
# if the app is compromised, attacker has root inside the container
RUN useradd \
    --create-home \
    --shell /bin/bash \
    --uid 1000 \
    neurosql

WORKDIR /home/neurosql/app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code with correct ownership
COPY --chown=neurosql:neurosql app/ ./app/
COPY --chown=neurosql:neurosql alembic/ ./alembic/
COPY --chown=neurosql:neurosql alembic.ini ./alembic.ini

# Switch to non-root user
USER neurosql

# ------------------------------------------------------------------ #
# Environment variables with production defaults
# ------------------------------------------------------------------ #
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/home/neurosql/app \
    PORT=8000 \
    WORKERS=2

# Expose the application port
EXPOSE 8000

# ------------------------------------------------------------------ #
# Health check
# Used by Docker Compose and container orchestrators to verify
# the application is ready to receive traffic.
# ------------------------------------------------------------------ #
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')" \
    || exit 1

# ------------------------------------------------------------------ #
# Startup command
#
# Development: uvicorn with --reload (in docker-compose.yml command)
# Production:  gunicorn with multiple uvicorn workers
#
# Gunicorn manages worker processes:
#   --workers 2:            2 worker processes (adjust per CPU count)
#   UvicornWorker:          each worker is an async uvicorn instance
#   --bind 0.0.0.0:8000:    listen on all interfaces
#   --access-logfile -:     log to stdout (captured by Docker)
#   --error-logfile -:      errors to stderr
#   --log-level info:       production log level
#   --timeout 120:          worker timeout (long for LLM calls)
#   --graceful-timeout 30:  time to finish in-flight requests on shutdown
#   --keep-alive 5:         keep-alive connections
# ------------------------------------------------------------------ #
CMD ["gunicorn", "app.main:app", \
     "--workers", "2", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "--log-level", "info", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5"]