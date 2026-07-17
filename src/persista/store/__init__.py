r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BaseDuckDBStore",
    "BaseSQLiteStore",
    "BaseStore",
    "DuckDBStore",
    "InMemoryStore",
    "OnConflict",
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
from persista.store.duckdb import BaseDuckDBStore, DuckDBStore
from persista.store.duckdb_typed import TypedDuckDBStore
from persista.store.in_memory import InMemoryStore
from persista.store.redis import RedisStore
from persista.store.sqlite import BaseSQLiteStore, SQLiteStore
from persista.store.sqlite_typed import TypedSQLiteStore
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
