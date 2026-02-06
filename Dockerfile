# Turtle-CANSLIM Docker Image
# Multi-stage build for smaller image size

# ============================================
# Stage 1: Builder
# ============================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy project files needed for build
COPY pyproject.toml ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY README.md ./

# Build wheels for all dependencies
RUN pip install --no-cache-dir build pip-tools && \
    pip wheel --no-cache-dir --wheel-dir /wheels ".[dev]"

# ============================================
# Stage 2: Runtime
# ============================================
FROM python:3.11-slim as runtime

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash turtle

# Copy wheels from builder
COPY --from=builder /wheels /wheels

# Install Python packages from wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY --chown=turtle:turtle . .

RUN mkdir -p /app/logs /app/results && \
    chown -R turtle:turtle /app

# Switch to non-root user
USER turtle

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from src.core.config import get_settings; get_settings()" || exit 1

# Default command (can be overridden)
CMD ["python", "scripts/run_trading.py", "--market", "both"]
