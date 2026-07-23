from __future__ import annotations

import uuid
from collections.abc import Generator, Iterator
from typing import Any

import pytest

from persista.store import BasePostgresStore, PostgresStore, TypedPostgresStore
from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available
from tests.integration.store.postgres_helpers import (
    get_postgres_conninfo,
    postgres_available,
)

if is_psycopg_available():
    import psycopg

pytestmark = [psycopg_available, postgres_available]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def conninfo() -> str:
    return get_postgres_conninfo()


@pytest.fixture
def table_name() -> str:
    return f"store_{uuid.uuid4().hex}"


@pytest.fixture(params=[PostgresStore, TypedPostgresStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[BasePostgresStore]:
    return request.param


@pytest.fixture
def store(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> Generator[BasePostgresStore, None, None]:
    with store_cls(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
def typed_store_no_schema(
    conninfo: str, table_name: str
) -> Generator[TypedPostgresStore, None, None]:
    """Store with no schema (everything in `extra`)."""
    with TypedPostgresStore(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
def typed_store(conninfo: str, table_name: str) -> Generator[TypedPostgresStore, None, None]:
    """Store with a typed schema."""
    with TypedPostgresStore(
        conninfo,
        table=table_name,
        value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"},
    ) as store:
        yield store


@pytest.fixture
def items() -> dict[str, dict[str, Any]]:
    return {
        "1": {
            "title": "Intro to Python",
            "author": "Alice",
            "year": 2022,
            "category": "Programming",
        },
        "2": {
            "title": "Advanced Python",
            "author": "Alice",
            "year": 2023,
            "category": "Programming",
        },
        "3": {"title": "History of Rome", "author": "Bob", "year": 2021, "category": "History"},
        "4": {"title": "History of Greece", "author": "Bob", "year": 2020, "category": "History"},
    }


def test_conninfo_connects(conninfo: str) -> None:
    with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


#####################################################
#     Tests for PostgresStore/TypedPostgresStore     #
#####################################################


# --- constructor ---


def test_init_creates_table(store: BasePostgresStore) -> None:
    assert store.count() == 0


def test_init_accepts_psycopg_connect_kwargs(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    with store_cls(conninfo, table=table_name, connect_timeout=5) as store:
        assert store.count() == 0


def test_two_stores_different_tables_are_isolated(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    with (
        store_cls(conninfo, table=table_name) as store_a,
        store_cls(conninfo, table=f"{table_name}_other") as store_b,
    ):
        store_a.set("1", {"text": "a"})
        assert store_b.get("1") is None
        assert store_b.count() == 0


# --- repr/str ---


def test_repr(store: BasePostgresStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


def test_str(store: BasePostgresStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


def test_repr_after_close_does_not_raise(store: BasePostgresStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


def test_set_increases_count(store: BasePostgresStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


def test_set_stores_value(store: BasePostgresStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


def test_set_default_overwrites_existing(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_raise(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_new_key_is_unaffected(store: BasePostgresStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


def test_set_on_conflict_invalid_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


def test_set_many_increases_count(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: BasePostgresStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_default_overwrites_existing(store: BasePostgresStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_many_on_conflict_raise(store: BasePostgresStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: BasePostgresStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_overwrite(store: BasePostgresStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: BasePostgresStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_many_on_conflict_invalid_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


def test_set_batches_empty_is_no_op(store: BasePostgresStore) -> None:
    store.set_batches([])
    assert store.count() == 0


def test_set_batches_writes_all_pairs(store: BasePostgresStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_consumes_a_generator(store: BasePostgresStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_set_batches_on_conflict_skip(store: BasePostgresStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


def test_count_empty_store(store: BasePostgresStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


def test_get_existing_value(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


def test_get_missing_key_returns_none(store: BasePostgresStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


def test_get_many_returns_correct_length(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


def test_get_many_returns_none_for_missing(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_preserves_order(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


def test_get_many_empty_list_returns_empty_list(store: BasePostgresStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


def test_filter_no_args_returns_all(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_no_match_returns_empty(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_rejects_malicious_field_name(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    store.set_many(items)
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        store.filter(**{"bad; DROP TABLE store;--": "x"})


def test_filter_preserves_full_value(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


def test_filter_empty_store_returns_empty(store: BasePostgresStore) -> None:
    assert store.filter(author="Alice") == []


def test_filter_integer_field_value(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_value_no_match_returns_empty(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(year=9999) == []


# --- delete ---


def test_delete_removes_value(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: BasePostgresStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


def test_delete_many_removes_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_preserves_other_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


def test_delete_many_empty_list_is_no_op(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: BasePostgresStore) -> None:
    store.delete_many(["99", "100"])


def test_delete_many_single_key(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- contains_many ---


def test_contains_many_all_found(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


def test_contains_many_all_missing(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


def test_contains_many_mixed(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


def test_contains_many_empty_input_returns_empty_lists(store: BasePostgresStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


def test_contains_many_empty_store_returns_all_missing(store: BasePostgresStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


def test_contains_many_returns_tuple_of_two_lists(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


def test_keys_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: BasePostgresStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


def test_values_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert list(store.values()) == []


def test_values_returns_all_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


def test_values_is_lazy_generator(store: BasePostgresStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: BasePostgresStore) -> None:
    assert isinstance(store.iter_batches(), Iterator)


def test_iter_batches_default_batch_size(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_yields_correct_batch_sizes(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


def test_iter_batches_last_batch_may_be_smaller(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=3))
    assert sorted(len(b) for b in batches) == [1, 3]


def test_iter_batches_batch_size_larger_than_store(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_batch_size_one(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=1))
    assert sorted(len(b) for b in batches) == [1, 1, 1, 1]


def test_iter_batches_returns_all_key_value_pairs(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_batches_are_dicts(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


def test_iter_batches_zero_batch_size_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


def test_iter_batches_negative_batch_size_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


def test_iter_batches_error_raised_before_any_query(store: BasePostgresStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


def test_iter_batches_does_not_mutate_store(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


def test_close_closes_underlying_connection(store: BasePostgresStore) -> None:
    store.close()
    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        store._conn.execute("SELECT 1")


def test_close_is_idempotent(store: BasePostgresStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BasePostgresStore) -> None:
    assert store.close() is None


# --- context manager ---


def test_context_manager_returns_self(
    store: BasePostgresStore, store_cls: type[BasePostgresStore]
) -> None:
    assert isinstance(store, store_cls)


def test_context_manager_closes_on_normal_exit(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    with store_cls(conninfo, table=table_name) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1

    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        store._conn.execute("SELECT 1")


def test_context_manager_closes_on_exception(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), store_cls(conninfo, table=table_name) as store:
        raise ValueError(msg)

    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        store._conn.execute("SELECT 1")


def test_context_manager_usable_for_reads_and_writes(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    with store_cls(conninfo, table=table_name) as store:
        store.set_many(
            {
                "1": {"text": "hello", "author": "Alice"},
                "2": {"text": "world", "author": "Bob"},
            }
        )
        assert store.count() == 2
        assert store.filter(author="Alice")[0]["text"] == "hello"
        store.delete("1")
        assert store.count() == 1


# --- to_uri / from_uri ---


def test_to_uri_from_uri_round_trips_data(
    store_cls: type[BasePostgresStore], conninfo: str
) -> None:
    # `to_uri()` only encodes `conninfo`, not `table`, so a round trip lands
    # on the default "store" table; a custom `table` isn't round-trippable.
    with store_cls(conninfo) as store:
        store.set("1", {"text": "hello", "author": "Alice"})
        uri = store.to_uri()
        try:
            with store_cls.from_uri(uri) as reloaded:
                assert reloaded.get("1") == {"text": "hello", "author": "Alice"}
        finally:
            with psycopg.connect(conninfo) as conn, conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS store")
                conn.commit()


#######################################################
#     TypedPostgresStore-specific schema behavior     #
#######################################################

# PostgresStore and TypedPostgresStore share the exact same behavior when
# no schema is involved (covered by every test above, run against both
# `store_cls` params). TypedPostgresStore additionally supports declaring typed
# columns via `value_schema`, covered here.


def test_init_no_schema_stores_everything_in_extra(
    typed_store_no_schema: TypedPostgresStore,
) -> None:
    typed_store_no_schema.set("1", {"title": "Intro to Python", "author": "Alice"})
    assert typed_store_no_schema.get("1") == {"title": "Intro to Python", "author": "Alice"}


def test_init_schema_with_reserved_key_column_raises(conninfo: str, table_name: str) -> None:
    with pytest.raises(ValueError, match=r"reserved key column name"):
        TypedPostgresStore(conninfo, table=table_name, value_schema={"_KEY_": "TEXT"})


def test_value_field_named_key_does_not_collide_with_primary_key(
    typed_store_no_schema: TypedPostgresStore,
) -> None:
    """A value field literally named 'key' must not collide with the
    store's primary key column, and should be stored/retrieved via the
    extra JSONB overflow column."""
    typed_store_no_schema.set("1", {"key": "not-the-primary-key"})
    assert typed_store_no_schema.get("1") == {"key": "not-the-primary-key"}
    assert typed_store_no_schema.filter(key="not-the-primary-key") == [
        {"key": "not-the-primary-key"}
    ]


def test_set_on_conflict_merge_with_typed_schema(typed_store: TypedPostgresStore) -> None:
    typed_store.set("1", {"author": "Alice", "year": 2022})
    typed_store.set("1", {"category": "Programming"}, on_conflict="merge")
    assert typed_store.get("1") == {"author": "Alice", "year": 2022, "category": "Programming"}


def test_get_round_trips_typed_schema_fields(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.get("1") == items["1"]


def test_get_round_trips_extra_field(typed_store: TypedPostgresStore) -> None:
    typed_store.set("1", {"author": "Alice", "publisher": "O'Reilly"})
    assert typed_store.get("1")["publisher"] == "O'Reilly"


def test_filter_single_typed_field(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_typed_fields(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_extra_field(typed_store: TypedPostgresStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


def test_filter_mixed_schema_and_extra_fields(typed_store: TypedPostgresStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(author="Alice", publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["publisher"] == "O'Reilly"


def test_filter_integer_typed_column(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_typed_column_no_match(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.filter(year=9999) == []


def test_iter_batches_with_typed_schema(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


# ---------------------------------------------------------------------------
# Async methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_aget_aset_round_trip(store: BasePostgresStore) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}
    assert await store.aget("missing") is None


@pytest.mark.asyncio
async def test_postgres_store_aset_many_and_afilter(store: BasePostgresStore) -> None:
    await store.aset_many(
        {
            "1": {"author": "Alice", "category": "Programming"},
            "2": {"author": "Bob", "category": "History"},
        }
    )
    assert len(await store.afilter(author="Alice")) == 1
    assert len(await store.afilter(category="History")) == 1


@pytest.mark.asyncio
async def test_postgres_store_acontains_many(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_postgres_store_adelete_acount(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acount() == 1


@pytest.mark.asyncio
async def test_postgres_store_akeys_aiter_batches(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3


@pytest.mark.asyncio
async def test_postgres_store_aclose_is_idempotent(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    store = store_cls(conninfo, table=table_name)
    await store.aget("1")  # forces the lazy async connection open
    await store.aclose()
    await store.aclose()
    assert store.closed


@pytest.mark.asyncio
async def test_postgres_store_aset_on_conflict_merge(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original", "author": "Alice"})
    await store.aset("1", {"text": "updated"}, on_conflict="merge")
    assert await store.aget("1") == {"text": "updated", "author": "Alice"}


@pytest.mark.asyncio
async def test_postgres_store_aset_on_conflict_raise(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.aset("1", {"text": "updated"}, on_conflict="raise")
    assert await store.aget("1") == {"text": "original"}


@pytest.mark.asyncio
async def test_postgres_store_async_context_manager(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with store_cls(conninfo, table=table_name) as astore:
        await astore.aset_many(
            {
                "1": {"text": "hello", "author": "Alice"},
                "2": {"text": "world", "author": "Bob"},
            }
        )
        assert await astore.acount() == 2
        result = await astore.afilter(author="Alice")
        assert result[0]["text"] == "hello"
        await astore.adelete("1")
        assert await astore.acount() == 1
    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        astore._conn.execute("SELECT 1")
