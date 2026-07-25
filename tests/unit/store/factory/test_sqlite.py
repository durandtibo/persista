from __future__ import annotations

from coola.equality import objects_are_equal

from persista.store import BaseStore, PickleSQLiteStore, SQLiteStore, TypedSQLiteStore
from persista.store.factory import (
    BaseStoreFactory,
    PickleSQLiteStoreFactory,
    SQLiteStoreFactory,
    TypedSQLiteStoreFactory,
)

########################################
#     Tests for SQLiteStoreFactory     #
########################################


# --- Inheritance ---


def test_sqlite_store_factory_is_base_store_factory() -> None:
    assert isinstance(SQLiteStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_sqlite_store_factory_make_store_returns_base_store() -> None:
    factory = SQLiteStoreFactory(":memory:")
    with factory.make_store() as store:
        assert isinstance(store, BaseStore)


def test_sqlite_store_factory_make_store_returns_sqlite_store() -> None:
    factory = SQLiteStoreFactory(":memory:")
    with factory.make_store() as store:
        assert isinstance(store, SQLiteStore)


def test_sqlite_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = SQLiteStoreFactory(":memory:")
    with factory.make_store() as store1, factory.make_store() as store2:
        assert store1 is not store2


# --- _get_repr_kwargs ---


def test_sqlite_store_factory_get_repr_kwargs() -> None:
    factory = SQLiteStoreFactory(":memory:", timeout=5)
    assert objects_are_equal(factory._get_repr_kwargs(), {"database": ":memory:", "timeout": 5})


# --- __repr__ and __str__ ---


def test_sqlite_store_factory_repr_starts_with_class_name() -> None:
    factory = SQLiteStoreFactory(":memory:")
    assert repr(factory).startswith("SQLiteStoreFactory(")


def test_sqlite_store_factory_str_starts_with_class_name() -> None:
    factory = SQLiteStoreFactory(":memory:")
    assert str(factory).startswith("SQLiteStoreFactory(")


def test_sqlite_store_factory_repr_contains_database() -> None:
    factory = SQLiteStoreFactory(":memory:")
    assert "database" in repr(factory)


def test_sqlite_store_factory_str_contains_database() -> None:
    factory = SQLiteStoreFactory(":memory:")
    assert "database" in str(factory)


#############################################
#     Tests for TypedSQLiteStoreFactory     #
#############################################


# --- Inheritance ---


def test_typed_sqlite_store_factory_is_base_store_factory() -> None:
    assert isinstance(TypedSQLiteStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_typed_sqlite_store_factory_make_store_returns_base_store() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    with factory.make_store() as store:
        assert isinstance(store, BaseStore)


def test_typed_sqlite_store_factory_make_store_returns_typed_sqlite_store() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    with factory.make_store() as store:
        assert isinstance(store, TypedSQLiteStore)


def test_typed_sqlite_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    with factory.make_store() as store1, factory.make_store() as store2:
        assert store1 is not store2


# --- _get_repr_kwargs ---


def test_typed_sqlite_store_factory_get_repr_kwargs() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"database": ":memory:", "value_schema": {"author": "TEXT"}},
    )


# --- __repr__ and __str__ ---


def test_typed_sqlite_store_factory_repr_starts_with_class_name() -> None:
    factory = TypedSQLiteStoreFactory(":memory:")
    assert repr(factory).startswith("TypedSQLiteStoreFactory(")


def test_typed_sqlite_store_factory_str_starts_with_class_name() -> None:
    factory = TypedSQLiteStoreFactory(":memory:")
    assert str(factory).startswith("TypedSQLiteStoreFactory(")


def test_typed_sqlite_store_factory_repr_contains_value_schema() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert "value_schema" in repr(factory)


def test_typed_sqlite_store_factory_str_contains_value_schema() -> None:
    factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert "value_schema" in str(factory)


##############################################
#     Tests for PickleSQLiteStoreFactory     #
##############################################


# --- Inheritance ---


def test_pickle_sqlite_store_factory_is_base_store_factory() -> None:
    assert isinstance(PickleSQLiteStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_pickle_sqlite_store_factory_make_store_returns_base_store() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    with factory.make_store() as store:
        assert isinstance(store, BaseStore)


def test_pickle_sqlite_store_factory_make_store_returns_pickle_sqlite_store() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    with factory.make_store() as store:
        assert isinstance(store, PickleSQLiteStore)


def test_pickle_sqlite_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    with factory.make_store() as store1, factory.make_store() as store2:
        assert store1 is not store2


# --- _get_repr_kwargs ---


def test_pickle_sqlite_store_factory_get_repr_kwargs() -> None:
    factory = PickleSQLiteStoreFactory(":memory:", timeout=5)
    assert objects_are_equal(factory._get_repr_kwargs(), {"database": ":memory:", "timeout": 5})


# --- __repr__ and __str__ ---


def test_pickle_sqlite_store_factory_repr_starts_with_class_name() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    assert repr(factory).startswith("PickleSQLiteStoreFactory(")


def test_pickle_sqlite_store_factory_str_starts_with_class_name() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    assert str(factory).startswith("PickleSQLiteStoreFactory(")


def test_pickle_sqlite_store_factory_repr_contains_database() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    assert "database" in repr(factory)


def test_pickle_sqlite_store_factory_str_contains_database() -> None:
    factory = PickleSQLiteStoreFactory(":memory:")
    assert "database" in str(factory)
