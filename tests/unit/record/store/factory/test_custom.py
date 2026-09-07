from __future__ import annotations

from coola.equality import objects_are_equal

from persista.record.store import (
    DuckDBRecordStore,
    InMemoryRecordStore,
    SQLiteRecordStore,
    TypedDuckDBRecordStore,
    TypedSQLiteRecordStore,
)
from persista.record.store.factory import (
    BaseRecordStoreFactory,
    DuckDBRecordStoreFactory,
    InMemoryRecordStoreFactory,
    SQLiteRecordStoreFactory,
    TypedDuckDBRecordStoreFactory,
    TypedSQLiteRecordStoreFactory,
)
from persista.testing.fixtures import duckdb_available

###############################################
#     Tests for DuckDBRecordStoreFactory     #
###############################################


def test_duckdb_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(DuckDBRecordStoreFactory(), BaseRecordStoreFactory)


@duckdb_available
def test_duckdb_record_store_factory_make_record_store_returns_duckdb_record_store() -> None:
    factory = DuckDBRecordStoreFactory()
    assert isinstance(factory.make_record_store(), DuckDBRecordStore)


@duckdb_available
def test_duckdb_record_store_factory_make_record_store_returns_new_instance_each_call() -> None:
    factory = DuckDBRecordStoreFactory()
    assert factory.make_record_store() is not factory.make_record_store()


def test_duckdb_record_store_factory_get_repr_kwargs() -> None:
    factory = DuckDBRecordStoreFactory()
    assert objects_are_equal(factory._get_repr_kwargs(), {"database": ":memory:"})


def test_duckdb_record_store_factory_repr_starts_with_class_name() -> None:
    factory = DuckDBRecordStoreFactory()
    assert repr(factory).startswith("DuckDBRecordStoreFactory(")


####################################################
#     Tests for TypedDuckDBRecordStoreFactory     #
####################################################


def test_typed_duckdb_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(
        TypedDuckDBRecordStoreFactory(metadata_schema={"author": "TEXT"}), BaseRecordStoreFactory
    )


@duckdb_available
def test_typed_duckdb_record_store_factory_make_record_store_returns_typed_duckdb_record_store() -> (
    None
):
    factory = TypedDuckDBRecordStoreFactory(metadata_schema={"author": "TEXT"})
    assert isinstance(factory.make_record_store(), TypedDuckDBRecordStore)


def test_typed_duckdb_record_store_factory_get_repr_kwargs() -> None:
    factory = TypedDuckDBRecordStoreFactory(metadata_schema={"author": "TEXT"})
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"database": ":memory:", "metadata_schema": {"author": "TEXT"}},
    )


#################################################
#     Tests for InMemoryRecordStoreFactory     #
#################################################


def test_in_memory_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(InMemoryRecordStoreFactory(), BaseRecordStoreFactory)


def test_in_memory_record_store_factory_make_record_store_returns_in_memory_record_store() -> None:
    factory = InMemoryRecordStoreFactory()
    assert isinstance(factory.make_record_store(), InMemoryRecordStore)


def test_in_memory_record_store_factory_make_record_store_returns_new_instance_each_call() -> None:
    factory = InMemoryRecordStoreFactory()
    assert factory.make_record_store() is not factory.make_record_store()


def test_in_memory_record_store_factory_get_repr_kwargs() -> None:
    factory = InMemoryRecordStoreFactory()
    assert objects_are_equal(factory._get_repr_kwargs(), {})


def test_in_memory_record_store_factory_repr_starts_with_class_name() -> None:
    factory = InMemoryRecordStoreFactory()
    assert repr(factory).startswith("InMemoryRecordStoreFactory(")


###############################################
#     Tests for SQLiteRecordStoreFactory     #
###############################################


def test_sqlite_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(SQLiteRecordStoreFactory(), BaseRecordStoreFactory)


def test_sqlite_record_store_factory_make_record_store_returns_sqlite_record_store() -> None:
    factory = SQLiteRecordStoreFactory()
    assert isinstance(factory.make_record_store(), SQLiteRecordStore)


def test_sqlite_record_store_factory_get_repr_kwargs() -> None:
    factory = SQLiteRecordStoreFactory()
    assert objects_are_equal(factory._get_repr_kwargs(), {"database": ":memory:"})


####################################################
#     Tests for TypedSQLiteRecordStoreFactory     #
####################################################


def test_typed_sqlite_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(
        TypedSQLiteRecordStoreFactory(metadata_schema={"author": "TEXT"}), BaseRecordStoreFactory
    )


def test_typed_sqlite_record_store_factory_make_record_store_returns_typed_sqlite_record_store() -> (
    None
):
    factory = TypedSQLiteRecordStoreFactory(metadata_schema={"author": "TEXT"})
    assert isinstance(factory.make_record_store(), TypedSQLiteRecordStore)


def test_typed_sqlite_record_store_factory_get_repr_kwargs() -> None:
    factory = TypedSQLiteRecordStoreFactory(metadata_schema={"author": "TEXT"})
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"database": ":memory:", "metadata_schema": {"author": "TEXT"}},
    )
