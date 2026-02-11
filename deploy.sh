#!/bin/bash
set -euo pipefail

echo "=== Turtle-CANSLIM Deploy ==="

git pull origin main
docker compose build --no-cache app
docker compose up -d

echo ""
echo "=== Deploy Complete ==="
echo "TUI: docker compose --profile tui run --rm tui"
