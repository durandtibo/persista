r"""Contain utilities for optional dependencies."""

from __future__ import annotations

__all__ = [
    "aiosqlite_available",
    "check_aiosqlite",
    "check_duckdb",
    "check_faker",
    "check_httpx",
    "check_lmdb",
    "check_psycopg",
    "check_redis",
    "duckdb_available",
    "faker_available",
    "httpx_available",
    "is_aiosqlite_available",
    "is_duckdb_available",
    "is_faker_available",
    "is_httpx_available",
    "is_lmdb_available",
    "is_psycopg_available",
    "is_redis_available",
    "lmdb_available",
    "psycopg_available",
    "raise_aiosqlite_missing_error",
    "raise_duckdb_missing_error",
    "raise_faker_missing_error",
    "raise_httpx_missing_error",
    "raise_lmdb_missing_error",
    "raise_psycopg_missing_error",
    "raise_redis_missing_error",
    "redis_available",
]

from persista.utils.imports.aiosqlite import (
    aiosqlite_available,
    check_aiosqlite,
    is_aiosqlite_available,
    raise_aiosqlite_missing_error,
)
from persista.utils.imports.duckdb import (
    check_duckdb,
    duckdb_available,
    is_duckdb_available,
    raise_duckdb_missing_error,
)
from persista.utils.imports.faker import (
    check_faker,
    faker_available,
    is_faker_available,
    raise_faker_missing_error,
)
from persista.utils.imports.httpx import (
    check_httpx,
    httpx_available,
    is_httpx_available,
    raise_httpx_missing_error,
)
from persista.utils.imports.lmdb import (
    check_lmdb,
    is_lmdb_available,
    lmdb_available,
    raise_lmdb_missing_error,
)
from persista.utils.imports.psycopg import (
    check_psycopg,
    is_psycopg_available,
    psycopg_available,
    raise_psycopg_missing_error,
)
from persista.utils.imports.redis import (
    check_redis,
    is_redis_available,
    raise_redis_missing_error,
    redis_available,
)
