r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BasePostgresStore",
    "BaseStore",
    "Codec",
    "DuckDBStore",
    "FileStore",
    "InMemoryStore",
    "JsonCodec",
    "LmdbStore",
    "NullStore",
    "OnConflict",
    "PickleCodec",
    "PostgresStore",
    "RedisStore",
    "SQLiteStore",
    "normalize_on_conflict",
    "register_scheme",
    "split_present_missing",
    "store_from_uri",
    "validate_batch_size",
    "validate_field_name",
    "validate_on_conflict",
]

from persista.store.base import BaseStore
from persista.store.codec import Codec, JsonCodec, PickleCodec
from persista.store.duckdb import DuckDBStore
from persista.store.file import FileStore
from persista.store.in_memory import InMemoryStore
from persista.store.keys import split_present_missing
from persista.store.lmdb import LmdbStore
from persista.store.null import NullStore
from persista.store.postgres import BasePostgresStore, PostgresStore
from persista.store.redis import RedisStore
from persista.store.registry import register_scheme, store_from_uri
from persista.store.sqlite import SQLiteStore
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
