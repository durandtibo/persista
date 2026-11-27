r"""Postgres-specific tests for :class:`PostgresStore`.

The generic :class:`~persista.store.BaseStore` contract (get/set/filter/
delete/keys/... and their async twins) is already exercised
exhaustively, identically across every backend including these two, by
``tests/integration/store/test_consistency.py``. Do not re-add tests
here for behavior that test file already covers -- only add a test here
if it depends on something specific to Postgres: connection/table
lifecycle, SQL injection guarding or URI round-tripping.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BasePostgresStore, PostgresStore
from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available
from tests.integration.store.postgres_helpers import (
    get_postgres_conninfo,
    postgres_available,
)

if TYPE_CHECKING:
    from collections.abc import Generator

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


@pytest.fixture
def store_cls() -> type[BasePostgresStore]:
    return PostgresStore


@pytest.fixture
def store(
    store_cls: type[BasePostgresStore], conninfo: str, table_name: str
) -> Generator[BasePostgresStore, None, None]:
    with store_cls(conninfo, table=table_name) as store:
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


###################################
#     Tests for PostgresStore     #
###################################


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
    await store.aopen()
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
