# Turtle-CANSLIM Docker Image

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libpq5 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash turtle

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY scripts/ ./scripts/

# Install Python dependencies directly (most reliable method)
RUN pip install --no-cache-dir -e ".[dev]" && \
    pip cache purge

# Copy remaining application files
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

# Default command
CMD ["python", "scripts/run_trading.py", "--market", "both"]
