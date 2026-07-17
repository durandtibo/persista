from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from persista.store import PostgresStore, TypedPostgresStore

psycopg = pytest.importorskip("psycopg")

logger = logging.getLogger(__name__)


################################
#     Construction / init      #
################################


def test_postgres_store_invalid_table_name_raises_before_connect() -> None:
    with patch("persista.store.postgres.psycopg.connect") as mock_connect:
        with pytest.raises(ValueError, match="Invalid table name"):
            PostgresStore("postgresql://x", table="bad; DROP TABLE store;--")
        mock_connect.assert_not_called()


def test_typed_postgres_store_invalid_table_name_raises_before_connect() -> None:
    with patch("persista.store.postgres.psycopg.connect") as mock_connect:
        with pytest.raises(ValueError, match="Invalid table name"):
            TypedPostgresStore("postgresql://x", table="bad; DROP TABLE store;--")
        mock_connect.assert_not_called()


def test_postgres_store_valid_table_name_calls_connect() -> None:
    with patch("persista.store.postgres.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        PostgresStore("postgresql://x", table="mytable")
        mock_connect.assert_called_once_with("postgresql://x", autocommit=True)


def test_typed_postgres_store_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match="reserved key column name"):
        TypedPostgresStore("postgresql://x", value_schema={"_KEY_": "TEXT"})


################################
#     Helpers to build stores  #
################################


def _make_postgres_store(table: str = "store") -> PostgresStore:
    with patch("persista.store.postgres.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        store = PostgresStore("postgresql://x", table=table)
    # __init__ issues a CREATE TABLE via the mocked connection; reset call
    # history so tests can assert on activity from their own calls only.
    store._conn.reset_mock()
    return store


def _make_typed_postgres_store(
    table: str = "store", value_schema: dict[str, str] | None = None
) -> TypedPostgresStore:
    with patch("persista.store.postgres.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        store = TypedPostgresStore(
            "postgresql://x",
            table=table,
            value_schema=value_schema or {"author": "TEXT", "year": "INTEGER"},
        )
    store._conn.reset_mock()
    return store


################################
#     _create_table_sql        #
################################


def test_postgres_store_create_table_sql() -> None:
    store = _make_postgres_store(table="mytable")
    stmt = store._create_table_sql().as_string(None)
    assert "mytable" in stmt
    assert "value JSONB NOT NULL" in stmt


def test_typed_postgres_store_create_table_sql() -> None:
    store = _make_typed_postgres_store(table="mytable")
    stmt = store._create_table_sql().as_string(None)
    assert "mytable" in stmt
    assert "author" in stmt
    assert "TEXT" in stmt
    assert "year" in stmt
    assert "INTEGER" in stmt
    assert "extra" in stmt


################################
#     _build_filter_condition  #
################################


def test_postgres_store_build_filter_condition() -> None:
    store = _make_postgres_store()
    cond = store._build_filter_condition("author").as_string(None)
    assert "value->>" in cond
    assert "'author'" in cond


def test_postgres_store_build_filter_condition_invalid_field_name() -> None:
    store = _make_postgres_store()
    with pytest.raises(ValueError, match="Invalid filter field name"):
        store._build_filter_condition("bad; DROP TABLE")


def test_typed_postgres_store_build_filter_condition_schema_field() -> None:
    store = _make_typed_postgres_store()
    cond = store._build_filter_condition("author").as_string(None)
    assert "author" in cond
    assert "extra->>" not in cond


def test_typed_postgres_store_build_filter_condition_extra_field() -> None:
    store = _make_typed_postgres_store()
    cond = store._build_filter_condition("publisher").as_string(None)
    assert "extra->>" in cond
    assert "'publisher'" in cond


def test_typed_postgres_store_build_filter_condition_extra_field_invalid_name() -> None:
    store = _make_typed_postgres_store()
    with pytest.raises(ValueError, match="Invalid filter field name"):
        store._build_filter_condition("bad; DROP TABLE")


################################
#     _build_insert            #
################################


def test_typed_postgres_store_build_insert() -> None:
    store = _make_typed_postgres_store()
    stmt = store._build_insert().as_string(None)
    assert "INSERT INTO" in stmt
    assert "ON CONFLICT" in stmt
    assert "_KEY_" in stmt
    assert "author" in stmt
    assert "year" in stmt
    assert "extra" in stmt
    assert "DO UPDATE SET" in stmt


################################
#     _row_to_value/_value_to_row (round-trip)   #
################################


def test_postgres_store_row_to_value_is_passthrough() -> None:
    store = _make_postgres_store()
    value = {"title": "Intro to Python", "author": "Alice"}
    assert store._row_to_value(("1", value)) == value


def test_typed_postgres_store_round_trip_all_known_fields() -> None:
    store = _make_typed_postgres_store()
    value = {"author": "Alice", "year": 2022}
    row = store._value_to_row("1", value)
    assert row == ("1", "Alice", 2022, None)
    assert store._row_to_value(row) == value


def test_typed_postgres_store_round_trip_split_schema_and_extra() -> None:
    store = _make_typed_postgres_store()
    value = {"author": "Alice", "title": "Intro to Python"}
    row = store._value_to_row("1", value)
    assert row == ("1", "Alice", None, {"title": "Intro to Python"})
    assert store._row_to_value(row) == value


def test_typed_postgres_store_round_trip_empty_value() -> None:
    store = _make_typed_postgres_store()
    value: dict[str, object] = {}
    row = store._value_to_row("1", value)
    assert row == ("1", None, None, None)
    assert store._row_to_value(row) == {}


################################
#     Empty-input guard clauses #
################################


def test_postgres_store_get_many_empty_returns_empty_list() -> None:
    store = _make_postgres_store()
    assert store.get_many([]) == []
    store._conn.cursor.assert_not_called()


def test_postgres_store_set_many_empty_is_noop() -> None:
    store = _make_postgres_store()
    assert store.set_many({}) is None
    store._conn.cursor.assert_not_called()
    store._conn.execute.assert_not_called()


def test_postgres_store_delete_many_empty_is_noop() -> None:
    store = _make_postgres_store()
    assert store.delete_many([]) is None
    store._conn.execute.assert_not_called()


def test_postgres_store_contains_many_empty_returns_empty_tuple() -> None:
    store = _make_postgres_store()
    assert store.contains_many([]) == ([], [])
    store._conn.cursor.assert_not_called()


def test_typed_postgres_store_get_many_empty_returns_empty_list() -> None:
    store = _make_typed_postgres_store()
    assert store.get_many([]) == []
    store._conn.cursor.assert_not_called()


def test_typed_postgres_store_set_many_empty_is_noop() -> None:
    store = _make_typed_postgres_store()
    assert store.set_many({}) is None
    store._conn.cursor.assert_not_called()
    store._conn.execute.assert_not_called()


def test_typed_postgres_store_delete_many_empty_is_noop() -> None:
    store = _make_typed_postgres_store()
    assert store.delete_many([]) is None
    store._conn.execute.assert_not_called()


def test_typed_postgres_store_contains_many_empty_returns_empty_tuple() -> None:
    store = _make_typed_postgres_store()
    assert store.contains_many([]) == ([], [])
    store._conn.cursor.assert_not_called()
