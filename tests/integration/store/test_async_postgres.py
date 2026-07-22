from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import (
    AsyncBasePostgresStore,
    AsyncPostgresStore,
    AsyncTypedPostgresStore,
)
from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available
from tests.integration.store.postgres_helpers import (
    get_postgres_conninfo,
    postgres_available,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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


@pytest.fixture(params=[AsyncPostgresStore, AsyncTypedPostgresStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[AsyncBasePostgresStore]:
    return request.param


@pytest.fixture
async def store(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> AsyncGenerator[AsyncBasePostgresStore, None]:
    async with store_cls(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
async def typed_store_no_schema(
    conninfo: str, table_name: str
) -> AsyncGenerator[AsyncTypedPostgresStore, None]:
    """Store with no schema (everything in `extra`)."""

    async with AsyncTypedPostgresStore(conninfo, table=table_name) as store:
        yield store


@pytest.fixture
async def typed_store(
    conninfo: str, table_name: str
) -> AsyncGenerator[AsyncTypedPostgresStore, None]:
    """Store with a typed schema."""

    async with AsyncTypedPostgresStore(
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


async def test_conninfo_connects(conninfo: str) -> None:
    async with await psycopg.AsyncConnection.connect(conninfo) as conn, conn.cursor() as cur:
        await cur.execute("SELECT 1")
        assert await cur.fetchone() == (1,)


###################################################################
#     Tests for AsyncPostgresStore/AsyncTypedPostgresStore        #
###################################################################


# --- constructor ---


async def test_init_creates_table(store: AsyncBasePostgresStore) -> None:
    assert await store.count() == 0


async def test_init_accepts_psycopg_connect_kwargs(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with store_cls(conninfo, table=table_name, connect_timeout=5) as store:
        assert await store.count() == 0


async def test_two_stores_different_tables_are_isolated(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with (
        store_cls(conninfo, table=table_name) as store_a,
        store_cls(conninfo, table=f"{table_name}_other") as store_b,
    ):
        await store_a.set("1", {"text": "a"})
        assert await store_b.get("1") is None
        assert await store_b.count() == 0


# --- repr/str ---


async def test_repr(store: AsyncBasePostgresStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


async def test_str(store: AsyncBasePostgresStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


async def test_repr_after_close_does_not_raise(store: AsyncBasePostgresStore) -> None:
    await store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


async def test_set_increases_count(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


async def test_set_stores_value(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


async def test_set_default_overwrites_existing(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_raise(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_skip(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_overwrite(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_merge(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_on_conflict_new_key_is_unaffected(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="raise")
    assert await store.get("1") == {"text": "hello"}


async def test_set_on_conflict_invalid_raises(store: AsyncBasePostgresStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


async def test_set_many_increases_count(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


async def test_set_many_empty_is_no_op(store: AsyncBasePostgresStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


async def test_set_many_default_overwrites_existing(store: AsyncBasePostgresStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_many_on_conflict_raise(store: AsyncBasePostgresStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


async def test_set_many_on_conflict_skip(store: AsyncBasePostgresStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_overwrite(store: AsyncBasePostgresStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_merge(store: AsyncBasePostgresStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_many_on_conflict_invalid_raises(store: AsyncBasePostgresStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


async def test_set_batches_empty_is_no_op(store: AsyncBasePostgresStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


async def test_set_batches_writes_all_pairs(store: AsyncBasePostgresStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


async def test_set_batches_consumes_a_generator(store: AsyncBasePostgresStore) -> None:
    def gen() -> Any:
        for i in range(5):
            yield str(i), {"v": i}

    await store.set_batches(gen(), batch_size=2)
    assert await store.count() == 5


async def test_set_batches_on_conflict_skip(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


# --- count ---


async def test_count_empty_store(store: AsyncBasePostgresStore) -> None:
    assert await store.count() == 0


async def test_count_after_set_many(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- get ---


async def test_get_existing_value(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get("1") == items["1"]


async def test_get_missing_key_returns_none(store: AsyncBasePostgresStore) -> None:
    assert await store.get("nonexistent") is None


# --- get_many ---


async def test_get_many_returns_correct_length(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.get_many(["1", "2", "99"])) == 3


async def test_get_many_returns_none_for_missing(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


async def test_get_many_preserves_order(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


async def test_get_many_empty_list_returns_empty_list(store: AsyncBasePostgresStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


async def test_filter_no_args_returns_all(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


async def test_filter_single_field(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_filter_multiple_fields(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_filter_no_match_returns_empty(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


async def test_filter_rejects_malicious_field_name(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    await store.set_many(items)
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        await store.filter(**{"bad; DROP TABLE store;--": "x"})


async def test_filter_preserves_full_value(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


async def test_filter_empty_store_returns_empty(store: AsyncBasePostgresStore) -> None:
    assert await store.filter(author="Alice") == []


async def test_filter_integer_field_value(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


async def test_filter_integer_value_no_match_returns_empty(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(year=9999) == []


# --- delete ---


async def test_delete_removes_value(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


async def test_delete_nonexistent_is_silent(store: AsyncBasePostgresStore) -> None:
    await store.delete("nonexistent")


# --- delete_many ---


async def test_delete_many_removes_values(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


async def test_delete_many_preserves_other_values(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.get("2") is not None
    assert await store.get("4") is not None


async def test_delete_many_empty_list_is_no_op(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


async def test_delete_many_nonexistent_keys_are_silent(store: AsyncBasePostgresStore) -> None:
    await store.delete_many(["99", "100"])


async def test_delete_many_single_key(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["2"])
    assert await store.count() == len(items) - 1
    assert await store.get("2") is None


# --- contains_many ---


async def test_contains_many_all_found(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


async def test_contains_many_all_missing(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


async def test_contains_many_mixed(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


async def test_contains_many_empty_input_returns_empty_lists(
    store: AsyncBasePostgresStore,
) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


async def test_contains_many_empty_store_returns_all_missing(
    store: AsyncBasePostgresStore,
) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


async def test_contains_many_returns_tuple_of_two_lists(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


async def test_keys_empty_store_yields_nothing(store: AsyncBasePostgresStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


async def test_keys_returns_all_keys(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert sorted([key async for key in store.keys()]) == sorted(items.keys())  # noqa: SIM118


# --- values ---


async def test_values_empty_store_yields_nothing(store: AsyncBasePostgresStore) -> None:
    assert [value async for value in store.values()] == []


async def test_values_returns_all_values(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


async def test_iter_batches_empty_store_yields_nothing(store: AsyncBasePostgresStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


async def test_iter_batches_default_batch_size(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert sorted(len(b) for b in batches) == [2, 2]


async def test_iter_batches_last_batch_may_be_smaller(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=3)]
    assert sorted(len(b) for b in batches) == [1, 3]


async def test_iter_batches_batch_size_larger_than_store(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=100)]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_iter_batches_batch_size_one(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=1)]
    assert sorted(len(b) for b in batches) == [1, 1, 1, 1]


async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_iter_batches_batches_are_dicts(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert all(isinstance(batch, dict) for batch in batches)


async def test_iter_batches_zero_batch_size_raises(store: AsyncBasePostgresStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


async def test_iter_batches_negative_batch_size_raises(store: AsyncBasePostgresStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=-1):
            pass


async def test_iter_batches_does_not_mutate_store(
    store: AsyncBasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    async for _ in store.iter_batches(batch_size=2):
        pass
    assert await store.count() == len(items)


# --- close ---


async def test_close_closes_underlying_connection(store: AsyncBasePostgresStore) -> None:
    await store.set("1", {"text": "hello"})
    await store.close()
    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        await store._conn.execute("SELECT 1")


async def test_close_is_idempotent(store: AsyncBasePostgresStore) -> None:
    await store.close()
    await store.close()  # should not raise


async def test_close_returns_none(store: AsyncBasePostgresStore) -> None:
    assert await store.close() is None


# --- context manager ---


async def test_context_manager_returns_self(
    store: AsyncBasePostgresStore, store_cls: type[AsyncBasePostgresStore]
) -> None:
    assert isinstance(store, store_cls)


async def test_context_manager_closes_on_normal_exit(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with store_cls(conninfo, table=table_name) as store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1

    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        await store._conn.execute("SELECT 1")


async def test_context_manager_closes_on_exception(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"):  # noqa: PT012
        async with store_cls(conninfo, table=table_name) as store:
            await store.set("1", {"text": "hello"})
            raise ValueError(msg)

    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        await store._conn.execute("SELECT 1")


async def test_context_manager_usable_for_reads_and_writes(
    store_cls: type[AsyncBasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with store_cls(conninfo, table=table_name) as store:
        await store.set_many(
            {
                "1": {"text": "hello", "author": "Alice"},
                "2": {"text": "world", "author": "Bob"},
            }
        )
        assert await store.count() == 2
        result = await store.filter(author="Alice")
        assert result[0]["text"] == "hello"
        await store.delete("1")
        assert await store.count() == 1


# --- to_uri / from_uri ---


async def test_to_uri_from_uri_round_trips_data(
    store_cls: type[AsyncBasePostgresStore], conninfo: str
) -> None:
    # `to_uri()` only encodes `conninfo`, not `table`, so a round trip lands
    # on the default "store" table; a custom `table` isn't round-trippable.
    async with store_cls(conninfo) as store:
        await store.set("1", {"text": "hello", "author": "Alice"})
        uri = store.to_uri()
        try:
            async with store_cls.from_uri(uri) as reloaded:
                assert await reloaded.get("1") == {"text": "hello", "author": "Alice"}
        finally:
            async with await psycopg.AsyncConnection.connect(conninfo) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DROP TABLE IF EXISTS store")
                await conn.commit()


#######################################################
#     TypedPostgresStore-specific schema behavior     #
#######################################################

# AsyncPostgresStore and AsyncTypedPostgresStore share the exact same
# behavior when no schema is involved (covered by every test above, run
# against both `store_cls` params). AsyncTypedPostgresStore additionally
# supports declaring typed columns via `value_schema`, covered here.


async def test_init_no_schema_stores_everything_in_extra(
    typed_store_no_schema: AsyncTypedPostgresStore,
) -> None:
    await typed_store_no_schema.set("1", {"title": "Intro to Python", "author": "Alice"})
    assert await typed_store_no_schema.get("1") == {
        "title": "Intro to Python",
        "author": "Alice",
    }


async def test_init_schema_with_reserved_key_column_raises(conninfo: str, table_name: str) -> None:
    with pytest.raises(ValueError, match=r"reserved key column name"):
        AsyncTypedPostgresStore(conninfo, table=table_name, value_schema={"_KEY_": "TEXT"})


async def test_value_field_named_key_does_not_collide_with_primary_key(
    typed_store_no_schema: AsyncTypedPostgresStore,
) -> None:
    """A value field literally named 'key' must not collide with the
    store's primary key column, and should be stored/retrieved via the
    extra JSONB overflow column."""
    await typed_store_no_schema.set("1", {"key": "not-the-primary-key"})
    assert await typed_store_no_schema.get("1") == {"key": "not-the-primary-key"}
    assert await typed_store_no_schema.filter(key="not-the-primary-key") == [
        {"key": "not-the-primary-key"}
    ]


async def test_set_on_conflict_merge_with_typed_schema(
    typed_store: AsyncTypedPostgresStore,
) -> None:
    await typed_store.set("1", {"author": "Alice", "year": 2022})
    await typed_store.set("1", {"category": "Programming"}, on_conflict="merge")
    assert await typed_store.get("1") == {
        "author": "Alice",
        "year": 2022,
        "category": "Programming",
    }


async def test_get_round_trips_typed_schema_fields(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    assert await typed_store.get("1") == items["1"]


async def test_get_round_trips_extra_field(typed_store: AsyncTypedPostgresStore) -> None:
    await typed_store.set("1", {"author": "Alice", "publisher": "O'Reilly"})
    value = await typed_store.get("1")
    assert value["publisher"] == "O'Reilly"


async def test_filter_single_typed_field(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_filter_multiple_typed_fields(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_filter_extra_field(typed_store: AsyncTypedPostgresStore) -> None:
    await typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Manning"},
        }
    )
    result = await typed_store.filter(publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


async def test_filter_mixed_schema_and_extra_fields(
    typed_store: AsyncTypedPostgresStore,
) -> None:
    await typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Manning"},
        }
    )
    result = await typed_store.filter(author="Alice", publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["publisher"] == "O'Reilly"


async def test_filter_integer_typed_column(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


async def test_filter_integer_typed_column_no_match(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    assert await typed_store.filter(year=9999) == []


async def test_iter_batches_with_typed_schema(
    typed_store: AsyncTypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items
