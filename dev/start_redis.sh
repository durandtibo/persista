#!/usr/bin/env bash

# start_redis.sh - Start a local Redis server for RedisStore integration tests
#
# Description:
#   Starts a Redis server on localhost so that
#   tests/integration/store/test_redis.py can run against a real
#   server (those tests are skipped automatically if no server is
#   reachable). Prefers Docker for an isolated, disposable instance;
#   falls back to a locally installed `redis-server` binary.
#
# Usage:
#   dev/start_redis.sh [port]
#
# Environment variables:
#   REDIS_PORT - Port to bind the server to (default: 6379).
#
# Requirements:
#   - Either Docker, or a `redis-server` binary on PATH
#     (e.g. `brew install redis` / `apt install redis-server`).

set -euo pipefail

PORT="${1:-${REDIS_PORT:-6379}}"

if command -v docker &>/dev/null; then
	echo "Starting Redis ${PORT} via Docker (Ctrl+C to stop)..."
	exec docker run --rm -p "${PORT}:6379" --name persista-redis redis:7
elif command -v redis-server &>/dev/null; then
	echo "Starting Redis on port ${PORT} via redis-server (Ctrl+C to stop)..."
	exec redis-server --port "${PORT}" --save "" --appendonly no
else
	echo "Error: neither Docker nor redis-server is available." >&2
	echo "Install Docker, or install Redis directly (e.g. 'brew install redis')." >&2
	exit 1
fi
