#!/usr/bin/env bash
# Stop all AgenticAvatar dev services.
set -e

cd "$(dirname "$0")/.."

echo "==> Stopping AgenticAvatar dev stack..."
docker compose down

echo "==> All services stopped."
