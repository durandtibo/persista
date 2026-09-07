from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.record import Record
from persista.record.store import (
    DuckDBRecordStore,
    InMemoryRecordStore,
    RecordStore,
    SQLiteRecordStore,
    TypedDuckDBRecordStore,
    TypedSQLiteRecordStore,
)
from persista.testing.fixtures import duckdb_available

if TYPE_CHECKING:
    from collections.abc import Generator

#####################################
#     Tests for InMemoryRecordStore     #
#####################################


@pytest.fixture
def in_memory_store() -> Generator[InMemoryRecordStore, None, None]:
    with InMemoryRecordStore() as store:
        yield store


def test_in_memory_record_store_is_record_store(in_memory_store: InMemoryRecordStore) -> None:
    assert isinstance(in_memory_store, RecordStore)


def test_in_memory_record_store_round_trip(in_memory_store: InMemoryRecordStore) -> None:
    in_memory_store.set_many([Record(id="1", metadata={"author": "Alice"})])
    assert in_memory_store.get("1") == Record(id="1", metadata={"author": "Alice"})


###################################
#     Tests for DuckDBRecordStore     #
###################################


@pytest.fixture
def duckdb_store() -> Generator[DuckDBRecordStore, None, None]:
    with DuckDBRecordStore() as store:
        yield store


@duckdb_available
def test_duckdb_record_store_is_record_store(duckdb_store: DuckDBRecordStore) -> None:
    assert isinstance(duckdb_store, RecordStore)


@duckdb_available
def test_duckdb_record_store_round_trip(duckdb_store: DuckDBRecordStore) -> None:
    duckdb_store.set_many([Record(id="1", metadata={"author": "Alice"})])
    assert duckdb_store.get("1") == Record(id="1", metadata={"author": "Alice"})


@duckdb_available
def test_duckdb_record_store_filter(duckdb_store: DuckDBRecordStore) -> None:
    duckdb_store.set_many(
        [
            Record(id="1", metadata={"author": "Alice"}),
            Record(id="2", metadata={"author": "Bob"}),
        ]
    )
    result = duckdb_store.filter(author="Alice")
    assert result == [Record(id="1", metadata={"author": "Alice"})]


########################################
#     Tests for TypedDuckDBRecordStore     #
########################################


@duckdb_available
def test_typed_duckdb_record_store_is_record_store() -> None:
    with TypedDuckDBRecordStore(metadata_schema={"author": "TEXT"}) as store:
        assert isinstance(store, RecordStore)


@duckdb_available
def test_typed_duckdb_record_store_round_trip() -> None:
    with TypedDuckDBRecordStore(metadata_schema={"author": "TEXT"}) as store:
        store.set_many([Record(id="1", metadata={"author": "Alice"})])
        assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


@duckdb_available
def test_typed_duckdb_record_store_filter_on_typed_column() -> None:
    with TypedDuckDBRecordStore(metadata_schema={"author": "TEXT"}) as store:
        store.set_many(
            [
                Record(id="1", metadata={"author": "Alice"}),
                Record(id="2", metadata={"author": "Bob"}),
            ]
        )
        result = store.filter(author="Alice")
        assert result == [Record(id="1", metadata={"author": "Alice"})]


@duckdb_available
def test_typed_duckdb_record_store_default_schema_is_empty() -> None:
    with TypedDuckDBRecordStore() as store:
        store.set_many([Record(id="1", metadata={"author": "Alice"})])
        assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


###################################
#     Tests for SQLiteRecordStore     #
###################################


@pytest.fixture
def sqlite_store() -> Generator[SQLiteRecordStore, None, None]:
    with SQLiteRecordStore() as store:
        yield store


def test_sqlite_record_store_is_record_store(sqlite_store: SQLiteRecordStore) -> None:
    assert isinstance(sqlite_store, RecordStore)


def test_sqlite_record_store_round_trip(sqlite_store: SQLiteRecordStore) -> None:
    sqlite_store.set_many([Record(id="1", metadata={"author": "Alice"})])
    assert sqlite_store.get("1") == Record(id="1", metadata={"author": "Alice"})


########################################
#     Tests for TypedSQLiteRecordStore     #
########################################


def test_typed_sqlite_record_store_is_record_store() -> None:
    with TypedSQLiteRecordStore(metadata_schema={"author": "TEXT"}) as store:
        assert isinstance(store, RecordStore)


def test_typed_sqlite_record_store_round_trip() -> None:
    with TypedSQLiteRecordStore(metadata_schema={"author": "TEXT"}) as store:
        store.set_many([Record(id="1", metadata={"author": "Alice"})])
        assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_typed_sqlite_record_store_filter_on_typed_column() -> None:
    with TypedSQLiteRecordStore(metadata_schema={"author": "TEXT"}) as store:
        store.set_many(
            [
                Record(id="1", metadata={"author": "Alice"}),
                Record(id="2", metadata={"author": "Bob"}),
            ]
        )
        result = store.filter(author="Alice")
        assert result == [Record(id="1", metadata={"author": "Alice"})]
