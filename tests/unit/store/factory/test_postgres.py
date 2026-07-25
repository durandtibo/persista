from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from coola.equality import objects_are_equal

from persista.store import BaseStore, PostgresStore, TypedPostgresStore
from persista.store.factory import (
    BaseStoreFactory,
    PostgresStoreFactory,
    TypedPostgresStoreFactory,
)

psycopg = pytest.importorskip("psycopg")

MODULE = "persista.store.postgres"


@pytest.fixture(autouse=True)
def _fake_psycopg_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.psycopg.connect", lambda *_args, **_kwargs: MagicMock())


#########################################
#     Tests for PostgresStoreFactory     #
#########################################


# --- Inheritance ---


def test_postgres_store_factory_is_base_store_factory() -> None:
    assert isinstance(PostgresStoreFactory("postgresql://localhost/db"), BaseStoreFactory)


# --- make_store ---


def test_postgres_store_factory_make_store_returns_base_store() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert isinstance(factory.make_store(), BaseStore)


def test_postgres_store_factory_make_store_returns_postgres_store() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert isinstance(factory.make_store(), PostgresStore)


def test_postgres_store_factory_make_store_uses_table_name() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db", table="items")
    store = factory.make_store()
    assert store._table == "items"


# --- _get_repr_kwargs ---


def test_postgres_store_factory_get_repr_kwargs() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db", table="items")
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"conninfo": "postgresql://localhost/db", "table": "items"},
    )


# --- __repr__ and __str__ ---


def test_postgres_store_factory_repr_starts_with_class_name() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert repr(factory).startswith("PostgresStoreFactory(")


def test_postgres_store_factory_str_starts_with_class_name() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert str(factory).startswith("PostgresStoreFactory(")


def test_postgres_store_factory_repr_contains_conninfo() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert "conninfo" in repr(factory)


def test_postgres_store_factory_str_contains_conninfo() -> None:
    factory = PostgresStoreFactory("postgresql://localhost/db")
    assert "conninfo" in str(factory)


###############################################
#     Tests for TypedPostgresStoreFactory     #
###############################################


# --- Inheritance ---


def test_typed_postgres_store_factory_is_base_store_factory() -> None:
    assert isinstance(TypedPostgresStoreFactory("postgresql://localhost/db"), BaseStoreFactory)


# --- make_store ---


def test_typed_postgres_store_factory_make_store_returns_base_store() -> None:
    factory = TypedPostgresStoreFactory(
        "postgresql://localhost/db", value_schema={"author": "TEXT"}
    )
    assert isinstance(factory.make_store(), BaseStore)


def test_typed_postgres_store_factory_make_store_returns_typed_postgres_store() -> None:
    factory = TypedPostgresStoreFactory(
        "postgresql://localhost/db", value_schema={"author": "TEXT"}
    )
    assert isinstance(factory.make_store(), TypedPostgresStore)


# --- _get_repr_kwargs ---


def test_typed_postgres_store_factory_get_repr_kwargs() -> None:
    factory = TypedPostgresStoreFactory(
        "postgresql://localhost/db", table="items", value_schema={"author": "TEXT"}
    )
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {
            "conninfo": "postgresql://localhost/db",
            "table": "items",
            "value_schema": {"author": "TEXT"},
        },
    )


# --- __repr__ and __str__ ---


def test_typed_postgres_store_factory_repr_starts_with_class_name() -> None:
    factory = TypedPostgresStoreFactory("postgresql://localhost/db")
    assert repr(factory).startswith("TypedPostgresStoreFactory(")


def test_typed_postgres_store_factory_str_starts_with_class_name() -> None:
    factory = TypedPostgresStoreFactory("postgresql://localhost/db")
    assert str(factory).startswith("TypedPostgresStoreFactory(")


def test_typed_postgres_store_factory_repr_contains_value_schema() -> None:
    factory = TypedPostgresStoreFactory(
        "postgresql://localhost/db", value_schema={"author": "TEXT"}
    )
    assert "value_schema" in repr(factory)


def test_typed_postgres_store_factory_str_contains_value_schema() -> None:
    factory = TypedPostgresStoreFactory(
        "postgresql://localhost/db", value_schema={"author": "TEXT"}
    )
    assert "value_schema" in str(factory)
