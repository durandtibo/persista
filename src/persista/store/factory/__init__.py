r"""Contain factories for stores."""

from __future__ import annotations

__all__ = [
    "BaseStoreFactory",
    "ConfigurableStoreFactory",
    "DuckDBStoreFactory",
    "InMemoryStoreFactory",
    "JsonFileStoreFactory",
    "LmdbStoreFactory",
    "NullStoreFactory",
    "PickleFileStoreFactory",
    "PickleLmdbStoreFactory",
    "PickleRedisStoreFactory",
    "PickleSQLiteStoreFactory",
    "PostgresStoreFactory",
    "RedisStoreFactory",
    "SQLiteStoreFactory",
    "StoreFactory",
    "TypedDuckDBStoreFactory",
    "TypedPostgresStoreFactory",
    "TypedSQLiteStoreFactory",
]

from persista.store.factory.base import BaseStoreFactory
from persista.store.factory.configurable import ConfigurableStoreFactory
from persista.store.factory.duckdb import DuckDBStoreFactory, TypedDuckDBStoreFactory
from persista.store.factory.file import JsonFileStoreFactory, PickleFileStoreFactory
from persista.store.factory.in_memory import InMemoryStoreFactory
from persista.store.factory.lmdb import LmdbStoreFactory, PickleLmdbStoreFactory
from persista.store.factory.null import NullStoreFactory
from persista.store.factory.postgres import (
    PostgresStoreFactory,
    TypedPostgresStoreFactory,
)
from persista.store.factory.redis import PickleRedisStoreFactory, RedisStoreFactory
from persista.store.factory.sqlite import (
    PickleSQLiteStoreFactory,
    SQLiteStoreFactory,
    TypedSQLiteStoreFactory,
)
from persista.store.factory.vanilla import StoreFactory
