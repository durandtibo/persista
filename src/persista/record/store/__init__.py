r"""Contain record store utilities."""

from __future__ import annotations

__all__ = [
    "BaseRecordStore",
    "DuckDBRecordStore",
    "InMemoryRecordStore",
    "RecordStore",
    "SQLiteRecordStore",
    "TypedDuckDBRecordStore",
    "TypedSQLiteRecordStore",
    "resolve_record_store",
]

from persista.record.store.base import BaseRecordStore
from persista.record.store.custom import (
    DuckDBRecordStore,
    InMemoryRecordStore,
    SQLiteRecordStore,
    TypedDuckDBRecordStore,
    TypedSQLiteRecordStore,
)
from persista.record.store.record import RecordStore
from persista.record.store.resolve import resolve_record_store
