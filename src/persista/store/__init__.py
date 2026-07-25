r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BaseDuckDBStore",
    "BaseFileStore",
    "BaseLmdbStore",
    "BasePostgresStore",
    "BaseRedisStore",
    "BaseSQLiteStore",
    "BaseStore",
    "DuckDBStore",
    "InMemoryStore",
    "JsonFileStore",
    "LmdbStore",
    "NullStore",
    "OnConflict",
    "PickleFileStore",
    "PickleLmdbStore",
    "PickleRedisStore",
    "PickleSQLiteStore",
    "PostgresStore",
    "RedisStore",
    "SQLiteStore",
    "TypedDuckDBStore",
    "TypedPostgresStore",
    "TypedSQLiteStore",
    "normalize_on_conflict",
    "register_scheme",
    "split_present_missing",
    "store_from_uri",
    "validate_batch_size",
    "validate_field_name",
    "validate_on_conflict",
]

from persista.store.base import BaseStore
from persista.store.duckdb import BaseDuckDBStore, DuckDBStore, TypedDuckDBStore
from persista.store.file import BaseFileStore, JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.keys import split_present_missing
from persista.store.lmdb import BaseLmdbStore, LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import BasePostgresStore, PostgresStore, TypedPostgresStore
from persista.store.redis import BaseRedisStore, PickleRedisStore, RedisStore
from persista.store.registry import register_scheme, store_from_uri
from persista.store.sqlite import (
    BaseSQLiteStore,
    PickleSQLiteStore,
    SQLiteStore,
    TypedSQLiteStore,
)
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
