r"""Shared helpers for Postgres-backed integration tests.

Used by ``test_consistency.py`` and ``test_consistency_async.py``, which
both need to resolve a Postgres conninfo the same way: prefer
``PERSISTA_TEST_POSTGRES_URL`` if it points at a reachable server, and
otherwise lazily start a shared Docker container (skipping Postgres tests
if Docker or psycopg is unavailable). The resolution is cached at module
scope so the sync and async consistency suites share a single container
instead of paying the startup cost twice.
"""

from __future__ import annotations

__all__ = ["get_postgres_conninfo"]

import atexit
import os

from persista.utils.imports import is_psycopg_available

if is_psycopg_available():
    import psycopg
    from testcontainers.postgres import PostgresContainer

try:
    from docker.errors import DockerException
except ImportError:  # pragma: no cover
    DockerException = Exception

# PERSISTA_TEST_POSTGRES_URL lets a manually-managed server (e.g. one
# started via `dev/start_postgres.sh`) be reused instead of paying the cost
# of a fresh testcontainers/Docker container every session.
POSTGRES_URL = os.environ.get(
    "PERSISTA_TEST_POSTGRES_URL", "postgresql://postgres@localhost:5433/postgres"
)

_postgres_conninfo: str | None = None
_postgres_conninfo_resolved = False


def _postgres_url_reachable(url: str) -> bool:
    if not is_psycopg_available():
        return False
    try:
        with psycopg.connect(url, connect_timeout=1):
            return True
    except psycopg.OperationalError:
        return False


def get_postgres_conninfo() -> str | None:
    r"""Return a Postgres conninfo, preferring
    ``PERSISTA_TEST_POSTGRES_URL`` and otherwise lazily starting a
    shared container.

    ``None`` is returned (and cached) if psycopg is not installed, the
    configured server is unreachable, or Docker is unavailable, so this
    only pays the container-startup cost once per test session, and only
    when Postgres tests can actually run.
    """
    global _postgres_conninfo, _postgres_conninfo_resolved
    if _postgres_conninfo_resolved:
        return _postgres_conninfo
    _postgres_conninfo_resolved = True
    if not is_psycopg_available():
        return None
    if POSTGRES_URL:
        _postgres_conninfo = POSTGRES_URL if _postgres_url_reachable(POSTGRES_URL) else None
        return _postgres_conninfo
    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except DockerException:
        return None
    atexit.register(container.stop)
    _postgres_conninfo = (
        f"postgresql://{container.username}:{container.password}"
        f"@{container.get_container_host_ip()}"
        f":{container.get_exposed_port(5432)}"
        f"/{container.dbname}"
    )
    return _postgres_conninfo
