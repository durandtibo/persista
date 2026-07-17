#!/usr/bin/env bash

# start_postgres.sh - Start a local Postgres server for PostgresStore/TypedPostgresStore integration tests
#
# Description:
#   Starts a Postgres server on localhost so that
#   tests/integration/store/test_postgres.py can run against a real
#   server without needing Docker for every test session (by default
#   those tests spin up a disposable Docker container of their own
#   via testcontainers, and are skipped automatically if Docker isn't
#   available). Prefers Docker for an isolated, disposable instance;
#   falls back to a locally installed `postgres`/`initdb` binary.
#
# Usage:
#   dev/start_postgres.sh [port]
#   export PERSISTA_TEST_POSTGRES_URL="$(...)"  # printed on startup
#   pytest tests/integration/store/test_postgres.py
#
# Environment variables:
#   POSTGRES_PORT - Port to bind the server to (default: 5433, chosen to
#                   avoid colliding with a default local/brew-services
#                   Postgres already listening on 5432).
#   POSTGRES_USER - Superuser name to create (default: postgres).
#   POSTGRES_DB   - Database name to create (default: postgres).
#
# Requirements:
#   - Either Docker, or `postgres`/`initdb`/`pg_ctl` binaries on PATH
#     (e.g. `brew install postgresql@16`).

set -euo pipefail

PORT="${1:-${POSTGRES_PORT:-5433}}"
USER_NAME="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-postgres}"
CONNINFO="postgresql://${USER_NAME}@localhost:${PORT}/${DB_NAME}"

if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN &>/dev/null; then
	echo "Error: port ${PORT} is already in use by another process." >&2
	echo "Pass a different port, e.g.: dev/start_postgres.sh $((PORT + 1))" >&2
	exit 1
fi

if command -v docker &>/dev/null; then
	echo "Starting Postgres on port ${PORT} via Docker (Ctrl+C to stop)..."
	echo "PERSISTA_TEST_POSTGRES_URL=${CONNINFO}"
	exec docker run --rm -p "${PORT}:5432" \
		-e "POSTGRES_USER=${USER_NAME}" \
		-e "POSTGRES_DB=${DB_NAME}" \
		-e POSTGRES_HOST_AUTH_METHOD=trust \
		--name persista-postgres \
		postgres:16-alpine
elif command -v initdb &>/dev/null && command -v postgres &>/dev/null; then
	DATA_DIR="$(mktemp -d)"
	cleanup() { rm -rf "${DATA_DIR}"; }
	trap cleanup EXIT

	echo "Initializing Postgres data directory at ${DATA_DIR}..."
	# --locale=C avoids initdb's "could not find suitable text search
	# configuration for locale" warning triggered by some macOS/UTF-8
	# locale setups. --encoding=UTF8 must be passed explicitly alongside
	# it: without it, --locale=C makes initdb default to SQL_ASCII, which
	# makes psycopg return raw bytes instead of decoded str for text
	# columns.
	initdb -D "${DATA_DIR}" -U "${USER_NAME}" -A trust --locale=C --encoding=UTF8 >/dev/null

	if [[ "${DB_NAME}" != "postgres" ]]; then
		# createdb needs a running server, so start one briefly to create it.
		pg_ctl -D "${DATA_DIR}" -o "-p ${PORT} -k /tmp" -l "${DATA_DIR}/server.log" -w start
		createdb -h /tmp -p "${PORT}" -U "${USER_NAME}" "${DB_NAME}"
		pg_ctl -D "${DATA_DIR}" -m fast stop
	fi

	echo "Starting Postgres on port ${PORT} via postgres binary (Ctrl+C to stop)..."
	echo "PERSISTA_TEST_POSTGRES_URL=${CONNINFO}"
	postgres -D "${DATA_DIR}" -p "${PORT}" -k /tmp
else
	echo "Error: neither Docker nor postgres/initdb is available." >&2
	echo "Install Docker, or install Postgres directly (e.g. 'brew install postgresql@16')." >&2
	exit 1
fi
