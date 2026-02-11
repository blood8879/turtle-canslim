#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Database URL: connect to Docker PostgreSQL from host
export DATABASE_URL="postgresql://${POSTGRES_USER:-turtle}:${POSTGRES_PASSWORD:-turtle_secret_2024}@localhost:5432/${POSTGRES_DB:-turtle_canslim}"
export REDIS_URL="redis://localhost:6379/0"
export PYTHONPATH="$SCRIPT_DIR"

# Check if venv exists, create if not
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev]"
else
    source .venv/bin/activate
fi

# Check PostgreSQL is reachable
if ! python3 -c "import asyncpg" 2>/dev/null; then
    pip install -e ".[dev]"
fi

exec python3 scripts/run_tui.py
