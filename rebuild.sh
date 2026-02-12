#!/bin/bash
set -euo pipefail

echo "=== Turtle-CANSLIM Rebuild ==="

git pull origin main
docker compose build app
docker compose up -d app

echo ""
echo "=== Rebuild Complete ==="
docker compose logs --tail=5 app
