from __future__ import annotations

import pytest
from coola.equality import objects_are_equal

pytest.importorskip("duckdb")

from persista.store import BaseStore, DuckDBStore, TypedDuckDBStore
from persista.store.factory import (
    BaseStoreFactory,
    DuckDBStoreFactory,
    TypedDuckDBStoreFactory,
)

########################################
#     Tests for DuckDBStoreFactory     #
########################################


# --- Inheritance ---


def test_duckdb_store_factory_is_base_store_factory() -> None:
    assert isinstance(DuckDBStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_duckdb_store_factory_make_store_returns_base_store() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert isinstance(factory.make_store(), BaseStore)


def test_duckdb_store_factory_make_store_returns_duckdb_store() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert isinstance(factory.make_store(), DuckDBStore)


def test_duckdb_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_duckdb_store_factory_get_repr_kwargs() -> None:
    factory = DuckDBStoreFactory(":memory:", read_only=False)
    assert objects_are_equal(
        factory._get_repr_kwargs(), {"database": ":memory:", "read_only": False}
    )


# --- __repr__ and __str__ ---


def test_duckdb_store_factory_repr_starts_with_class_name() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert repr(factory).startswith("DuckDBStoreFactory(")


def test_duckdb_store_factory_str_starts_with_class_name() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert str(factory).startswith("DuckDBStoreFactory(")


def test_duckdb_store_factory_repr_contains_database() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert "database" in repr(factory)


def test_duckdb_store_factory_str_contains_database() -> None:
    factory = DuckDBStoreFactory(":memory:")
    assert "database" in str(factory)


#############################################
#     Tests for TypedDuckDBStoreFactory     #
#############################################


# --- Inheritance ---


def test_typed_duckdb_store_factory_is_base_store_factory() -> None:
    assert isinstance(TypedDuckDBStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_typed_duckdb_store_factory_make_store_returns_base_store() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert isinstance(factory.make_store(), BaseStore)


def test_typed_duckdb_store_factory_make_store_returns_typed_duckdb_store() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert isinstance(factory.make_store(), TypedDuckDBStore)


def test_typed_duckdb_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_typed_duckdb_store_factory_get_repr_kwargs() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"database": ":memory:", "value_schema": {"author": "TEXT"}},
    )


# --- __repr__ and __str__ ---


def test_typed_duckdb_store_factory_repr_starts_with_class_name() -> None:
    factory = TypedDuckDBStoreFactory(":memory:")
    assert repr(factory).startswith("TypedDuckDBStoreFactory(")


def test_typed_duckdb_store_factory_str_starts_with_class_name() -> None:
    factory = TypedDuckDBStoreFactory(":memory:")
    assert str(factory).startswith("TypedDuckDBStoreFactory(")


def test_typed_duckdb_store_factory_repr_contains_value_schema() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert "value_schema" in repr(factory)


def test_typed_duckdb_store_factory_str_contains_value_schema() -> None:
    factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
    assert "value_schema" in str(factory)
