r"""Postgres-specific tests for :class:`PostgresStore`/:class:`TypedPostgresStore`.

The generic :class:`~persista.store.BaseStore` contract (get/set/filter/
delete/keys/... and their async twins) is already exercised exhaustively,
identically across every backend including these two, by
``tests/integration/store/test_consistency.py``. Do not re-add tests here
for behavior that test file already covers -- only add a test here if it
depends on something specific to Postgres: connection/table lifecycle, SQL
injection guarding, URI round-tripping, or the typed-schema (``value_schema``)
feature that only :class:`TypedPostgresStore` has.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
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
    """Sanity check for the test environment: if this fails, every other
    test in this file will fail for an unrelated reason (no reachable
    Postgres), so it's worth diagnosing separately."""
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


def test_repr_after_close_does_not_raise(store: BasePostgresStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- filter: SQL injection guarding ---


def test_filter_rejects_malicious_field_name(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    store.set_many(items)
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        store.filter(**{"bad; DROP TABLE store;--": "x"})


async def test_afilter_rejects_malicious_field_name(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        await store.afilter(**{"bad; DROP TABLE store;--": "x"})


# --- close / context manager: underlying connection lifecycle ---


def test_close_closes_underlying_connection(store: BasePostgresStore) -> None:
    store.close()
    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        store._conn.execute("SELECT 1")


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


async def test_aclose_is_idempotent(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    store = store_cls(conninfo, table=table_name)
    await store.aget("1")  # forces the lazy async connection open
    await store.aclose()
    await store.aclose()
    assert store.closed


async def test_async_context_manager_closes_underlying_connection(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> None:
    async with store_cls(conninfo, table=table_name) as astore:
        await astore.aset("1", {"text": "hello"})
        assert await astore.acount() == 1
    with pytest.raises(psycopg.OperationalError, match=r"closed"):
        astore._conn.execute("SELECT 1")


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
# no schema is involved (covered by test_consistency.py, run against both
# `store_cls` params above). TypedPostgresStore additionally supports
# declaring typed columns via `value_schema`, covered here.


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


def test_iter_batches_with_typed_schema(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_typed_schema_honored_via_async_api(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    """The typed-schema SQL generation is shared between the sync and
    async code paths, so one smoke test through `a`-prefixed methods is
    enough to confirm it isn't bypassed there."""
    await typed_store.aset_many(items)
    assert await typed_store.aget("1") == items["1"]
    result = await typed_store.afilter(author="Alice", category="Programming")
    assert len(result) == 2
