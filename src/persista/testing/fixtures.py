r"""Define some pytest fixtures for testing.

`pytest` is required to use these fixtures.
"""

from __future__ import annotations

__all__ = [
    "aiosqlite_available",
    "aiosqlite_not_available",
    "duckdb_available",
    "duckdb_not_available",
    "faker_available",
    "faker_not_available",
    "httpx_available",
    "httpx_not_available",
    "lmdb_available",
    "lmdb_not_available",
    "psycopg_available",
    "psycopg_not_available",
    "redis_available",
    "redis_not_available",
    "requests_available",
    "requests_not_available",
    "urllib3_available",
    "urllib3_not_available",
]

import pytest

from persista.utils.imports import (
    is_aiosqlite_available,
    is_duckdb_available,
    is_faker_available,
    is_httpx_available,
    is_lmdb_available,
    is_psycopg_available,
    is_redis_available,
    is_requests_available,
    is_urllib3_available,
)

aiosqlite_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_aiosqlite_available(), reason="Requires aiosqlite"
)
aiosqlite_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_aiosqlite_available(), reason="Skip if aiosqlite is available"
)

duckdb_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_duckdb_available(), reason="Requires duckdb"
)
duckdb_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_duckdb_available(), reason="Skip if duckdb is available"
)

faker_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_faker_available(), reason="Requires faker"
)
faker_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_faker_available(), reason="Skip if faker is available"
)

httpx_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_httpx_available(), reason="Requires httpx"
)
httpx_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_httpx_available(), reason="Skip if httpx is available"
)

lmdb_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_lmdb_available(), reason="Requires lmdb"
)
lmdb_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_lmdb_available(), reason="Skip if lmdb is available"
)

psycopg_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_psycopg_available(), reason="Requires psycopg"
)
psycopg_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_psycopg_available(), reason="Skip if psycopg is available"
)

redis_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_redis_available(), reason="Requires redis"
)
redis_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_redis_available(), reason="Skip if redis is available"
)

requests_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_requests_available(), reason="Requires requests"
)
requests_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_requests_available(), reason="Skip if requests is available"
)

urllib3_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_urllib3_available(), reason="Requires urllib3"
)
urllib3_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_urllib3_available(), reason="Skip if urllib3 is available"
)
