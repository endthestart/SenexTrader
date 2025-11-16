# syntax=docker/dockerfile:1.4
# Multi-stage Dockerfile for Senex Trader
# Optimized for Podman with Python 3.12, PostgreSQL 15, and Redis 7

# ============================================================================
# Stage 1: Base - System dependencies and user setup
# ============================================================================
FROM python:3.12-slim-bookworm AS base

# Set Python environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# Install system dependencies
RUN --mount=type=cache,target=/var/cache/apt \
    DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client libraries (for PostgreSQL 15)
    libpq5 \
    # Cryptography dependencies
    libssl3 \
    libffi8 \
    # Utilities
    curl \
    ca-certificates \
    # Timezone data
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to America/New_York
ENV TZ=America/New_York
RUN ln -fs /usr/share/zoneinfo/America/New_York /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Create non-root user (UID 1000 for Podman compatibility)
RUN groupadd --gid 1000 senex && \
    useradd --uid 1000 --gid senex --shell /bin/bash --create-home senex

# Create application directories
RUN mkdir -p /app /app/logs /app/staticfiles /app/media /var/log/senex_trader && \
    chown -R senex:senex /app /var/log/senex_trader

# Set working directory
WORKDIR /app

# ============================================================================
# Stage 2: Dependencies - Python package installation (as non-root user)
# ============================================================================
FROM base AS dependencies

# Install build dependencies (needed for compiling Python packages)
RUN --mount=type=cache,target=/var/cache/apt \
    DEBIAN_FRONTEND=noninteractive apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create a user-specific pip directory and set ownership
RUN mkdir -p /home/senex/.local && \
    chown -R senex:senex /home/senex/.local

# Switch to non-root user for package installation
USER senex

# Set PATH to include user's local bin (for pip-installed commands)
ENV PATH="/home/senex/.local/bin:${PATH}"

# Install pinned pip toolchain as user
RUN pip install --user --upgrade pip==24.2 setuptools==69.5.1 wheel==0.43.0

# Copy requirements files
COPY --chown=senex:senex requirements.txt /tmp/requirements.txt

# Install Python dependencies as non-root user with cache mount
RUN --mount=type=cache,target=/home/senex/.cache/pip,uid=1000,gid=1000 \
    pip install --user -r /tmp/requirements.txt

# ============================================================================
# Stage 3: Runtime - Final application image
# ============================================================================
FROM base AS runtime

# Copy Python packages from dependencies stage (user installation)
COPY --from=dependencies --chown=senex:senex /home/senex/.local /home/senex/.local

# Set PATH to include user's local bin
ENV PATH="/home/senex/.local/bin:${PATH}"

# Copy application code
COPY --chown=senex:senex . /app/

# Copy and set up entrypoint script
COPY --chown=senex:senex docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Switch to non-root user
USER senex

# Expose port
EXPOSE 8000

# Health check (depends on /health/ endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# OCI standard labels
LABEL org.opencontainers.image.title="Senex Trader" \
      org.opencontainers.image.description="Automated options trading platform" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.vendor="Senex Trading"

# Entry point
ENTRYPOINT ["/entrypoint.sh"]

# Default command (can be overridden)
CMD ["web"]