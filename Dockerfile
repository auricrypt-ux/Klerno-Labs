# ==============================================================================
# Klerno Labs - Production-Ready Multi-Stage Dockerfile
# ==============================================================================
# World-class containerization for enterprise SaaS deployment
# Features: Multi-stage builds, security hardening, optimization

# ==============================================================================
# Base Image Selection
# ==============================================================================
ARG PYTHON_VERSION=3.11
ARG ALPINE_VERSION=3.18
FROM python:${PYTHON_VERSION}-slim AS base

# ==============================================================================
# Build Arguments & Environment Variables
# ==============================================================================
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=latest

# Security and performance environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VENV_IN_PROJECT=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# ==============================================================================
# Security Labels (OCI Standard)
# ==============================================================================
LABEL org.opencontainers.image.title="Klerno Labs"
LABEL org.opencontainers.image.description="AI-Powered AML Risk Intelligence Platform"
LABEL org.opencontainers.image.url="https://klerno.com"
LABEL org.opencontainers.image.documentation="https://github.com/Klerno-Labs/Klerno-Labs"
LABEL org.opencontainers.image.source="https://github.com/Klerno-Labs/Klerno-Labs"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.created=${BUILD_DATE}
LABEL org.opencontainers.image.revision=${VCS_REF}
LABEL org.opencontainers.image.vendor="Klerno Labs"
LABEL org.opencontainers.image.licenses="Proprietary"

# ==============================================================================
# Security Hardening - Create Non-Root User
# ==============================================================================
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# ==============================================================================
# System Dependencies & Security Updates
# ==============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Essential system packages
    ca-certificates \
    curl \
    wget \
    gnupg2 \
    # Build tools (removed in final stage)
    gcc \
    g++ \
    make \
    # Security tools
    dumb-init \
    # Cleanup
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# ==============================================================================
# Build Stage - Dependencies Installation
# ==============================================================================
FROM base AS builder

# Set working directory
WORKDIR /app

# Copy dependency files first (for better caching)
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --user -r requirements.txt

# ==============================================================================
# Development Stage (Optional)
# ==============================================================================
FROM builder AS development

# Install development dependencies
RUN pip install --no-cache-dir --user \
    pytest \
    pytest-asyncio \
    pytest-cov \
    black \
    isort \
    flake8 \
    mypy

# Copy application code
COPY --chown=appuser:appuser . /app/

# Switch to non-root user
USER appuser

# Development server command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ==============================================================================
# Production Stage - Optimized Runtime
# ==============================================================================
FROM base AS production

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Runtime essentials only
    ca-certificates \
    curl \
    # Remove build tools
    && apt-get purge -y gcc g++ make \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* \
    && rm -rf /var/tmp/*

# Create application directory
WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser *.py /app/
COPY --chown=appuser:appuser requirements.txt /app/

# Create necessary directories with proper permissions
RUN mkdir -p /app/data /app/logs /app/static && \
    chown -R appuser:appuser /app

# ==============================================================================
# Security Hardening
# ==============================================================================
# Remove unnecessary packages and files
RUN apt-get autoremove -y && \
    apt-get autoclean && \
    rm -rf /var/lib/{apt,dpkg,cache,log}/ && \
    # Remove potential security risks
    rm -rf /tmp/* /var/tmp/* && \
    # Secure file permissions
    find /app -type f -name "*.py" -exec chmod 644 {} \; && \
    find /app -type d -exec chmod 755 {} \;

# ==============================================================================
# Runtime Configuration
# ==============================================================================
# Switch to non-root user
USER appuser

# Add user's local bin to PATH
ENV PATH="/home/appuser/.local/bin:$PATH"

# Application configuration
ENV APP_ENV=production \
    PORT=8000 \
    WORKERS=1 \
    LOG_LEVEL=info

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:$PORT/health || exit 1

# Expose port
EXPOSE $PORT

# ==============================================================================
# Startup Script with Error Handling
# ==============================================================================
# Use dumb-init to handle signals properly
ENTRYPOINT ["dumb-init", "--"]

# Production command with error handling
CMD ["sh", "-c", "\
    echo 'Starting Klerno Labs Application...' && \
    echo 'Environment: $APP_ENV' && \
    echo 'Port: $PORT' && \
    echo 'Workers: $WORKERS' && \
    uvicorn app.main:app \
        --host 0.0.0.0 \
        --port $PORT \
        --workers $WORKERS \
        --log-level $LOG_LEVEL \
        --access-log \
        --loop uvloop \
        --http httptools \
        || (echo 'Application failed to start' && exit 1) \
"]

# ==============================================================================
# Multi-Architecture Support (Optional)
# ==============================================================================
# This Dockerfile supports multiple architectures:
# docker buildx build --platform linux/amd64,linux/arm64 -t klerno-labs .

# ==============================================================================
# Build Instructions & Examples
# ==============================================================================
# 
# Development build:
# docker build --target development -t klerno-labs:dev .
# docker run -p 8000:8000 -v $(pwd):/app klerno-labs:dev
#
# Production build:
# docker build --target production -t klerno-labs:latest .
# docker run -p 8000:8000 -e APP_ENV=production klerno-labs:latest
#
# With build args:
# docker build \
#   --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
#   --build-arg VCS_REF=$(git rev-parse HEAD) \
#   --build-arg VERSION=1.0.0 \
#   -t klerno-labs:1.0.0 .
#
# Security scan:
# docker scout cves klerno-labs:latest
# 
# ==============================================================================