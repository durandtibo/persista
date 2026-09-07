r"""Contain factories for record stores."""

from __future__ import annotations

__all__ = [
    "BaseRecordStoreFactory",
    "ConfigurableRecordStoreFactory",
    "DuckDBRecordStoreFactory",
    "InMemoryRecordStoreFactory",
    "RecordStoreFactory",
    "SQLiteRecordStoreFactory",
    "StoreRecordStoreFactory",
    "TypedDuckDBRecordStoreFactory",
    "TypedSQLiteRecordStoreFactory",
]

from persista.record.store.factory.base import BaseRecordStoreFactory
from persista.record.store.factory.configurable import ConfigurableRecordStoreFactory
from persista.record.store.factory.custom import (
    DuckDBRecordStoreFactory,
    InMemoryRecordStoreFactory,
    SQLiteRecordStoreFactory,
    TypedDuckDBRecordStoreFactory,
    TypedSQLiteRecordStoreFactory,
)
from persista.record.store.factory.store import StoreRecordStoreFactory
from persista.record.store.factory.vanilla import RecordStoreFactory
