r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BaseDuckDBStore",
    "BasePostgresStore",
    "BaseRedisStore",
    "BaseSQLiteStore",
    "BaseStore",
    "DuckDBStore",
    "InMemoryStore",
    "OnConflict",
    "PickleRedisStore",
    "PostgresStore",
    "RedisStore",
    "SQLiteStore",
    "TypedDuckDBStore",
    "TypedSQLiteStore",
    "normalize_on_conflict",
    "validate_batch_size",
    "validate_field_name",
    "validate_on_conflict",
]

from persista.store.base import BaseStore
from persista.store.duckdb import BaseDuckDBStore, DuckDBStore, TypedDuckDBStore
from persista.store.in_memory import InMemoryStore
from persista.store.postgres import BasePostgresStore, PostgresStore
from persista.store.redis import BaseRedisStore, PickleRedisStore, RedisStore
from persista.store.sqlite import BaseSQLiteStore, SQLiteStore, TypedSQLiteStore
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
