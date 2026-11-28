r"""Postgres-specific tests for :class:`~persista.store.PostgresStore`,
with a real server and no patching.

The ``BaseStore`` contract is tested by ``test_consistency.py`` and
``test_contract.py``, and the concurrent writers by
``test_postgres_concurrency.py``. Only add a test here if it depends on
something specific to Postgres: the connections, the credentials, the
table, the keys and values that it rejects, or the event loops of the
async connections.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import pytest

from persista.record import Record
from persista.record.store import RecordStore
from persista.store import (
    JsonCodec,
    PickleCodec,
    PostgresStore,
    SQLiteStore,
    store_from_uri,
)
from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available
from tests.integration.store.postgres_helpers import (
    drop_tables,
    get_postgres_conninfo,
    postgres_available,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from persista.store import Codec

if is_psycopg_available():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = [psycopg_available, postgres_available]

# The prefix of the tables of this module.
PREFIX = f"postgres_{uuid.uuid4().hex[:12]}_"

# The longest key that the store accepts, in bytes.
MAX_KEY_BYTES = 2692

NUL = chr(0)

NUM_WRITES = 50


def incompressible(length: int) -> str:
    r"""Return an ASCII string of a given length that PostgreSQL cannot
    compress enough to matter."""
    blocks = (hashlib.sha256(str(i).encode()).digest() for i in range(length // 32 + 1))
    # 94 printable ASCII characters, one per byte of the digests.
    return "".join(chr(33 + byte % 94) for block in blocks for byte in block)[:length]


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Generator[None, None, None]:
    r"""Remove the tables of the tests from the server."""
    yield
    drop_tables(PREFIX)


@pytest.fixture
def conninfo() -> str:
    return get_postgres_conninfo()


@pytest.fixture
def table() -> str:
    r"""Return the name of a table that no other test uses."""
    return PREFIX + uuid.uuid4().hex


@pytest.fixture
def name() -> str:
    r"""Return a name for the connections of one test."""
    return f"persista-test-{uuid.uuid4().hex}"


@pytest.fixture
def server(conninfo: str) -> Generator[Any, None, None]:
    r"""Return a connection to the server, outside of any store."""
    with psycopg.connect(conninfo, autocommit=True) as connection:
        yield connection


@pytest.fixture
def store(conninfo: str, table: str, name: str) -> Generator[PostgresStore, None, None]:
    with PostgresStore(conninfo, table=table, application_name=name) as store:
        yield store


def count_connections(server: Any, name: str, expected: int) -> int:
    r"""Return the number of connections of an application, after waiting
    until it is the expected one: the server removes a closed connection
    shortly after."""
    query = "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s"
    for _ in range(500):
        count = server.execute(query, (name,)).fetchone()[0]
        if count == expected:
            break
        server.execute("SELECT pg_sleep(0.01)")
    return count


def execute(server: Any, query: str, table: str, params: tuple | None = None) -> Any:
    r"""Run a query on a table."""
    return server.execute(sql.SQL(query).format(table=sql.Identifier(table)), params)


def with_password(conninfo: str, password: str, **options: str) -> str:
    r"""Return the URI of a server with a password and other options."""
    parts = conninfo_to_dict(conninfo) | options
    return (
        f"postgresql://{quote(parts['user'])}:{password}@{parts['host']}:{parts['port']}"
        f"/{parts['dbname']}"
    )


###################################
#     Tests for PostgresStore     #
###################################


# --- table ---


@pytest.mark.parametrize(
    ("codec", "column_type"),
    [
        pytest.param(JsonCodec(), "jsonb", id="json"),
        pytest.param(PickleCodec(), "bytea", id="pickle"),
    ],
)
def test_open_creates_the_table(
    conninfo: str, table: str, server: Any, codec: Codec, column_type: str
) -> None:
    with PostgresStore(conninfo, codec=codec, table=table):
        pass
    rows = server.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    assert rows == [("key", "text", "NO"), ("value", column_type, "NO")]


def test_open_reads_a_table_of_an_earlier_version(conninfo: str, table: str, server: Any) -> None:
    execute(server, "CREATE TABLE {table} (key TEXT PRIMARY KEY, value JSONB NOT NULL)", table)
    execute(server, "INSERT INTO {table} VALUES ('1', %s::jsonb)", table, ('{"a": 1.50}',))
    with PostgresStore(conninfo, table=table) as store:
        assert store.get("1") == {"a": 1.5}


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param("key TEXT PRIMARY KEY, value BYTEA NOT NULL", id="other_codec"),
        pytest.param("key TEXT PRIMARY KEY, value JSON NOT NULL", id="json_type"),
        pytest.param("key VARCHAR(10) PRIMARY KEY, value JSONB NOT NULL", id="key_type"),
        pytest.param("key TEXT, value JSONB NOT NULL", id="no_primary_key"),
        pytest.param("key TEXT PRIMARY KEY, value JSONB, extra INT", id="extra_column"),
    ],
)
def test_open_table_that_does_not_match_the_codec(
    conninfo: str, table: str, server: Any, columns: str
) -> None:
    execute(server, "CREATE TABLE {table} (" + columns + ")", table)
    store = PostgresStore(conninfo, table=table)
    with pytest.raises(ValueError, match=r"does not match the codec 'json'"):
        store.open()
    assert store.closed


def test_open_failure_closes_the_connection(
    conninfo: str, table: str, server: Any, name: str
) -> None:
    r"""Test that a store that cannot be opened leaks no connection
    (regression test: the connection stayed open)."""
    # The table does not exist, and cannot be created in a read-only
    # session.
    store = PostgresStore(
        conninfo,
        table=table,
        application_name=name,
        options="-c default_transaction_read_only=on",
    )
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction, match=r"read-only"):
        store.open()
    # The count is read while the store is still referenced.
    assert (count_connections(server, name, 0), store.closed) == (0, True)


def test_open_mismatch_closes_the_connection(
    conninfo: str, table: str, server: Any, name: str
) -> None:
    execute(server, "CREATE TABLE {table} (key TEXT PRIMARY KEY, value BYTEA NOT NULL)", table)
    store = PostgresStore(conninfo, table=table, application_name=name)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert (count_connections(server, name, 0), store.closed) == (0, True)


async def test_aopen_failure_closes_the_connection(
    conninfo: str, table: str, server: Any, name: str
) -> None:
    store = PostgresStore(
        conninfo,
        table=table,
        application_name=name,
        options="-c default_transaction_read_only=on",
    )
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction, match=r"read-only"):
        await store.aopen()
    assert (count_connections(server, name, 0), store.closed) == (0, True)


def test_open_existing_table_without_the_right_to_create(conninfo: str, table: str) -> None:
    r"""Test that an existing table can be read by a session that cannot
    create one."""
    with PostgresStore(conninfo, table=table) as store:
        store.set("1", {})
    with PostgresStore(
        conninfo, table=table, options="-c default_transaction_read_only=on"
    ) as reader:
        assert reader.get("1") == {}


def test_table_name_is_case_sensitive(conninfo: str, table: str) -> None:
    with (
        PostgresStore(conninfo, table=f"{table}_case") as lower,
        PostgresStore(conninfo, table=f"{table}_CASE") as upper,
    ):
        lower.set("1", {})
        assert upper.get("1") is None


def test_two_stores_different_tables_are_isolated(conninfo: str, table: str) -> None:
    with (
        PostgresStore(conninfo, table=table[:60]) as first,
        PostgresStore(conninfo, table=f"{table[:60]}_2") as second,
    ):
        first.set("1", {"text": "a"})
        second.clear()
        assert first.count() == 1


def test_longest_table_name(conninfo: str, table: str) -> None:
    longest = table.ljust(63, "x")[:63]
    with PostgresStore(conninfo, table=longest) as store:
        store.set_many({"1": {}, "2": {}}, on_conflict="raise")
        assert store.count() == 2


def test_jsonb_values_can_be_queried(store: PostgresStore, server: Any, table: str) -> None:
    store.set("1", {"author": "Alice"})
    rows = execute(server, "SELECT value->>'author' FROM {table}", table).fetchall()
    assert rows == [("Alice",)]


# --- keys ---


@pytest.mark.parametrize(
    "key",
    [
        pytest.param(incompressible(MAX_KEY_BYTES), id="ascii"),
        pytest.param("é" * (MAX_KEY_BYTES // 2), id="two_bytes"),
        pytest.param("".join(chr(0x4E00 + i) for i in range(897)), id="three_bytes"),
    ],
)
def test_longest_key(store: PostgresStore, key: str) -> None:
    store.set_many({key: {"v": 1}, "other": {}}, on_conflict="raise")
    assert store.get(key) == {"v": 1}


def test_key_limit_is_the_limit_of_the_index(store: PostgresStore, server: Any, table: str) -> None:
    r"""Test that the server rejects the first key that the store
    rejects, if it cannot compress it."""
    key = incompressible(MAX_KEY_BYTES + 1)
    with pytest.raises(psycopg.errors.ProgramLimitExceeded, match=r"index row size"):
        execute(server, "INSERT INTO {table} VALUES (%s, 'null')", table, (key,))
    assert store.count() == 0


@pytest.mark.parametrize(
    ("key", "match"),
    [
        pytest.param("a" + NUL, r"cannot contain a NUL character", id="nul"),
        pytest.param("a" * (MAX_KEY_BYTES + 1), r"has at most 2692 bytes", id="compressible"),
        pytest.param(incompressible(10_000), r"at most 2692 bytes", id="too_long"),
    ],
)
@pytest.mark.parametrize("on_conflict", ["overwrite", "merge"])
def test_rejected_key_writes_nothing(
    store: PostgresStore, key: str, match: str, on_conflict: str
) -> None:
    with pytest.raises(ValueError, match=match):
        store.set_many({"1": {}, key: {}}, on_conflict=on_conflict)
    assert store.count() == 0


# --- values ---


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"a": NUL}, id="value"),
        pytest.param({NUL: 1}, id="key"),
        pytest.param({"a": [{"b": f"x{NUL}y"}]}, id="nested"),
    ],
)
@pytest.mark.parametrize("on_conflict", ["overwrite", "raise", "skip", "merge"])
def test_json_value_with_nul_writes_nothing(
    store: PostgresStore, value: dict, on_conflict: str
) -> None:
    with pytest.raises(ValueError, match=r"cannot keep a NUL character"):
        store.set_many({"1": {}, "2": value}, on_conflict=on_conflict)
    assert store.count() == 0


async def test_json_value_with_nul_writes_nothing_async(store: PostgresStore) -> None:
    with pytest.raises(ValueError, match=r"cannot keep a NUL character"):
        await store.aset_many({"1": {}, "2": {"a": NUL}}, on_conflict="merge")
    assert await store.acount() == 0
    await store.aclose()


def test_pickle_value_with_nul(conninfo: str, table: str) -> None:
    value = {NUL: NUL, "tags": {"a"}, "point": (1, 2)}
    with PostgresStore(conninfo, codec=PickleCodec(), table=table) as store:
        store.set("1", value)
        assert store.get("1") == value


def test_json_value_with_a_literal_escape(store: PostgresStore) -> None:
    value = {"a": chr(92) + "u0000", "b": "1e+22"}
    store.set("1", value)
    assert store.get("1") == value


@pytest.mark.parametrize(
    "number", [1e16, 1e22, -1.5e300, 1.7976931348623157e308, 5e-324, 1e-7, 0.1, 2**100]
)
@pytest.mark.parametrize("on_conflict", ["overwrite", "merge"])
def test_json_numbers_keep_their_type(
    store: PostgresStore, number: float, on_conflict: str
) -> None:
    store.set("1", {"a": number})
    store.set("1", {"a": number}, on_conflict=on_conflict)
    assert repr(store.get("1")) == repr({"a": number})


def test_json_negative_zero_is_read_as_zero(store: PostgresStore) -> None:
    store.set("1", {"a": -0.0})
    assert repr(store.get("1")) == "{'a': 0.0}"


@pytest.mark.parametrize("size", [1, 2, 64, 65, 1000])
@pytest.mark.parametrize("codec", [JsonCodec(), PickleCodec()], ids=["json", "pickle"])
def test_write_of_any_size(conninfo: str, table: str, codec: Codec, size: int) -> None:
    r"""Test the writes that lock one key, several keys and the
    table."""
    items = {str(i): {"text": f'quote " backslash {chr(92)} é {i}'} for i in range(size)}
    with PostgresStore(conninfo, codec=codec, table=table) as store:
        store.set_many(items)
        store.set_many(items, on_conflict="merge")
        assert store.get_many(list(items)) == list(items.values())


# --- filter ---


def test_filter_none_matches_null_and_absent_fields(store: PostgresStore) -> None:
    r"""Regression test: the filter matched nothing."""
    store.set_many({"1": {"id": 1, "v": None}, "2": {"id": 2}, "3": {"id": 3, "v": "x"}})
    assert sorted(store.filter(v=None)) == ["1", "2"]


async def test_afilter_none_matches_null_and_absent_fields(store: PostgresStore) -> None:
    await store.aset_many({"1": {"id": 1, "v": None}, "2": {"id": 2}, "3": {"id": 3, "v": 0}})
    assert sorted(await store.afilter(v=None)) == ["1", "2"]
    await store.aclose()


def test_filter_none_and_value(store: PostgresStore) -> None:
    store.set_many({"1": {"a": 1}, "2": {"a": 1, "b": 2}, "3": {"a": 2}})
    assert store.filter(a=1, b=None) == {"1": {"a": 1}}


def test_record_store_filter_none(store: PostgresStore) -> None:
    records = RecordStore(store)
    records.set(Record("1", {"v": None}))
    records.set(Record("2", {"v": 1}))
    assert [record.id for record in records.filter(v=None)] == ["1"]


@pytest.mark.parametrize("field", ["bad; DROP TABLE store;--", "a' OR '1'='1", "a%s"])
@pytest.mark.parametrize("value", ["x", 1, None])
def test_filter_field_name_is_not_run_as_sql(
    store: PostgresStore, field: str, value: object
) -> None:
    r"""Test that a field name that is not an identifier is not placed
    in the SQL."""
    store.set_many({"1": {field: value}, "2": {field: "y"}})
    assert list(store.filter(**{field: value})) == ["1"]


def write_json(store: PostgresStore, key: str, document: str) -> None:
    r"""Write a JSON document as another program would, with the text of
    its numbers."""
    store.connection.execute(
        sql.SQL("INSERT INTO {} (key, value) VALUES (%s, %s::jsonb)").format(
            sql.Identifier(store._table)
        ),
        (key, document),
    )


@pytest.mark.parametrize("number", ["7", "7.0", "7.00", "7.000000000000000000000000", "0.7e1"])
def test_filter_int_matches_every_representation_of_a_number(
    store: PostgresStore, number: str
) -> None:
    r"""Test that the query of an int filter selects the numbers that
    Python reads as this int."""
    write_json(store, "1", f'{{"v": {number}}}')
    write_json(store, "2", '{"v": 7.5}')
    write_json(store, "3", '{"v": "7"}')
    assert list(store.filter(v=7)) == ["1"]


def test_filter_int_excludes_a_number_with_more_digits_than_a_float(
    store: PostgresStore,
) -> None:
    r"""Test the documented limitation of the int filters: Python reads
    this number, which another program wrote, as 7.0."""
    write_json(store, "1", '{"v": 6.99999999999999999999}')
    assert (store.get("1"), store.filter(v=7)) == ({"v": 7.0}, {})


@pytest.mark.parametrize("value", [2**53 - 1, -(2**53 - 1)])
def test_filter_largest_pushed_down_int(store: PostgresStore, value: int) -> None:
    store.set_many({"int": {"v": value}, "float": {"v": float(value)}, "next": {"v": value - 1}})
    assert sorted(store.filter(v=value)) == ["float", "int"]


@pytest.mark.parametrize(
    ("index", "fields"),
    [
        pytest.param("((value->>'author'))", {"author": "author-1"}, id="str"),
        pytest.param("USING gin (value jsonb_path_ops)", {"year": 1}, id="int"),
    ],
)
def test_filter_uses_expression_index(
    store: PostgresStore, index: str, fields: dict[str, Any]
) -> None:
    r"""Test that PostgreSQL uses the documented indexes for the query
    of a filter."""
    store.set_many({str(i): {"author": f"author-{i % 500}", "year": i % 500} for i in range(5000)})
    table = sql.Identifier(store._table)
    name = sql.Identifier(f"{store._table[-20:]}_index")
    store.connection.execute(sql.SQL("CREATE INDEX {} ON {} " + index).format(name, table))
    store.connection.execute(sql.SQL("ANALYZE {}").format(table))
    query, params = store._filter_statement(fields)
    plan = store.connection.execute(sql.SQL("EXPLAIN ") + query, params).fetchall()
    assert any(name.as_string(None).strip('"') in row[0] for row in plan)


# --- locks ---


def held_locks(server: Any, name: str) -> list[tuple[str, int]]:
    r"""Return the advisory locks that an application holds: the mode of
    each, and 1 if it is identified by one number (a key) or 2 by two
    numbers (the table)."""
    return server.execute(
        "SELECT l.mode, l.objsubid::int FROM pg_locks AS l "
        "JOIN pg_stat_activity AS a ON a.pid = l.pid "
        "WHERE l.locktype = 'advisory' AND l.granted AND a.application_name = %s "
        "ORDER BY l.objsubid, l.mode",
        (name,),
    ).fetchall()


def wait_for_locks(server: Any, name: str, count: int) -> list[tuple[str, int]]:
    r"""Wait until an application holds some number of advisory locks,
    and return them."""
    for _ in range(500):
        locks = held_locks(server, name)
        if len(locks) == count:
            break
        server.execute("SELECT pg_sleep(0.01)")
    return locks


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        pytest.param(1, [("ExclusiveLock", 1), ("ShareLock", 2)], id="one_key"),
        pytest.param(3, [("ExclusiveLock", 1)] * 3 + [("ShareLock", 2)], id="keys"),
        pytest.param(65, [("ExclusiveLock", 2)], id="table"),
    ],
)
@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s, items: s.set_many(items), id="set_many"),
        pytest.param(lambda s, items: s.delete_many(list(items)), id="delete_many"),
        pytest.param(lambda s, items: s.set_many(items, on_conflict="merge"), id="merge"),
    ],
)
def test_locks_of_a_write(
    *,
    conninfo: str,
    table: str,
    name: str,
    server: Any,
    size: int,
    expected: list,
    write: Callable[[PostgresStore, dict], None],
) -> None:
    r"""Test the advisory locks that a write holds while it waits for a
    row that another program locked."""
    items = {str(i): {} for i in range(size)}
    with PostgresStore(conninfo, table=table, application_name=name) as store:
        store.set_many(items)
        with ThreadPoolExecutor(1) as executor:
            with server.transaction():
                execute(server, "SELECT key FROM {table} FOR UPDATE", table)
                future = executor.submit(write, store, items)
                with psycopg.connect(conninfo, autocommit=True) as observer:
                    locks = wait_for_locks(observer, name, len(expected))
            future.result(timeout=30)
        assert (locks, held_locks(server, name)) == (expected, [])


# --- connections ---


def test_close_releases_the_connection(conninfo: str, table: str, name: str, server: Any) -> None:
    with PostgresStore(conninfo, table=table, application_name=name):
        pass
    assert count_connections(server, name, 0) == 0


def test_connection_is_closed_after_close(store: PostgresStore) -> None:
    connection = store.connection
    store.close()
    assert connection.closed


async def test_async_calls_use_one_connection(store: PostgresStore, server: Any, name: str) -> None:
    await asyncio.gather(*(store.aset(str(i), {}) for i in range(NUM_WRITES)))
    # The sync connection and the async one.
    assert count_connections(server, name, 2) == 2
    await store.aclose()


async def test_aclose_releases_the_connections(
    store: PostgresStore, server: Any, name: str
) -> None:
    await store.aset("1", {})
    await store.aclose()
    await store.aclose()
    assert (count_connections(server, name, 0), store.closed) == (0, True)


def test_loop_shutdown_releases_the_async_connection(
    store: PostgresStore, server: Any, name: str
) -> None:
    r"""Test that the async connection is closed when its event loop
    shuts down, and that the sync connection stays."""
    asyncio.run(store.aset("1", {}))
    assert count_connections(server, name, 1) == 1


def test_close_after_async_use_in_a_finished_loop(
    store: PostgresStore, server: Any, name: str
) -> None:
    asyncio.run(store.aset("1", {}))
    store.close()
    assert count_connections(server, name, 0) == 0


def test_close_after_a_loop_closed_without_shutdown(
    store: PostgresStore, server: Any, name: str, caplog: pytest.LogCaptureFixture
) -> None:
    r"""Test that the connection of a loop that was closed without
    shutting down its async generators is released."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.aset("1", {}))
    finally:
        loop.close()
    with caplog.at_level(logging.WARNING, logger="persista.store.loop_clients"):
        store.close()
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert (count_connections(server, name, 0), len(warnings)) == (0, 1)


async def test_close_in_the_loop_of_an_async_call_raises(store: PostgresStore) -> None:
    await store.aset("1", {})
    with pytest.raises(RuntimeError, match=r"An async client of PostgresStore is open"):
        store.close()
    assert await store.aget("1") == {}
    await store.aclose()


def test_aclose_with_the_connection_of_another_loop_raises(store: PostgresStore) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.acount())
        with pytest.raises(RuntimeError, match=r"An async client of PostgresStore is open"):
            asyncio.run(store.aclose())
        assert not store.closed
        loop.run_until_complete(store.aclose())
    finally:
        loop.close()


async def test_reopen_after_aclose(conninfo: str, table: str) -> None:
    store = PostgresStore(conninfo, table=table)
    async with store:
        await store.aset("1", {"a": 1})
    async with store:
        assert await store.aget("1") == {"a": 1}


async def test_aclose_while_calls_are_in_progress(
    store: PostgresStore, server: Any, name: str
) -> None:
    r"""Test that closing a store while async calls use it lets them
    end, and releases every connection."""
    calls = [
        asyncio.ensure_future(store.aset("a", {str(i): i}, on_conflict="merge"))
        for i in range(NUM_WRITES)
    ]
    await asyncio.sleep(0)
    await store.aclose()
    results = await asyncio.gather(*calls, return_exceptions=True)
    assert (results, count_connections(server, name, 0)) == ([None] * NUM_WRITES, 0)


@pytest.mark.parametrize(
    "iterate",
    [
        pytest.param(lambda s: s.aiter_batches(batch_size=1), id="aiter_batches"),
        pytest.param(lambda s: s.akeys(), id="akeys"),
    ],
)
async def test_aclose_during_an_iteration(
    store: PostgresStore, iterate: Callable[[PostgresStore], Any]
) -> None:
    store.set_many({str(i): {} for i in range(600)})
    iterator = iterate(store)
    await anext(iterator)
    await store.aclose()
    with pytest.raises(RuntimeError, match=r"is not open"):
        [item async for item in iterator]


def test_close_during_an_iteration(store: PostgresStore) -> None:
    store.set_many({"1": {}, "2": {}})
    iterator = store.iter_batches(batch_size=1)
    next(iterator)
    store.close()
    with pytest.raises(RuntimeError, match=r"is not open"):
        next(iterator)


def test_iteration_keeps_no_transaction_open(store: PostgresStore) -> None:
    store.set_many({"1": {}, "2": {}})
    iterator = store.iter_batches(batch_size=1)
    next(iterator)
    assert store.connection.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    iterator.close()


@pytest.mark.parametrize(
    "items",
    [
        pytest.param({"a": {"v": 2}}, id="key_lock"),
        pytest.param({str(i): {} for i in range(100)} | {"a": {"v": 2}}, id="table_lock"),
    ],
)
@pytest.mark.parametrize("on_conflict", ["overwrite", "merge"])
async def test_cancelled_write_leaves_the_store_usable(
    store: PostgresStore, conninfo: str, table: str, items: dict, on_conflict: str
) -> None:
    r"""Test that cancelling an async write that waits for a lock writes
    nothing, releases its locks and leaves the store usable."""
    store.set("a", {"v": 1})
    lock_row = sql.SQL("SELECT key FROM {} WHERE key = 'a' FOR UPDATE").format(
        sql.Identifier(table)
    )
    async with (
        await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as holder,
        holder.transaction(),
    ):
        await holder.execute(lock_row)
        task = asyncio.ensure_future(store.aset_many(items, on_conflict=on_conflict))
        done, _ = await asyncio.wait([task], timeout=0.5)
        task.cancel()
        await asyncio.wait([task], timeout=10)
    assert (done, task.cancelled()) == (set(), True)
    await asyncio.wait_for(store.aset("b", {}), timeout=10)
    await asyncio.wait_for(
        asyncio.to_thread(store.set, "a", {"w": 1}, on_conflict="merge"), timeout=10
    )
    assert (await store.aget("a"), await store.acount()) == ({"v": 1, "w": 1}, 2)
    await store.aclose()


def test_raise_conflict_leaves_the_connection_usable(store: PostgresStore) -> None:
    store.set("a", {})
    with pytest.raises(KeyError, match=r"already exist"):
        store.set_many({"a": {}, "b": {}}, on_conflict="raise")
    assert (store.connection.info.transaction_status, store.count()) == (
        psycopg.pq.TransactionStatus.IDLE,
        1,
    )


async def test_async_raise_conflict_keeps_the_connection(
    store: PostgresStore, server: Any, name: str
) -> None:
    await store.aset("a", {})
    query = "SELECT pid FROM pg_stat_activity WHERE application_name = %s ORDER BY pid"
    before = server.execute(query, (name,)).fetchall()
    with pytest.raises(KeyError, match=r"already exist"):
        await store.aset_many({"a": {}, "b": {}}, on_conflict="raise")
    await store.aset("b", {}, on_conflict="raise")
    assert server.execute(query, (name,)).fetchall() == before
    await store.aclose()


async def test_async_connection_lost_is_replaced(
    store: PostgresStore, server: Any, name: str
) -> None:
    r"""Test that an async call fails if the server closed the
    connection, and that the next one opens a new connection."""
    await store.aset("a", {})
    server.execute(
        "SELECT pg_terminate_backend(pid, 5000) FROM pg_stat_activity WHERE application_name = %s",
        (name,),
    )
    with pytest.raises(psycopg.OperationalError, match=r"connection"):
        await store.aget("a")
    assert await store.aget("a") == {}
    await store.aclose()


def test_threads_share_a_store(store: PostgresStore) -> None:
    r"""Test that threads that use one store at the same time keep every
    field, and that their transactions do not mix."""
    barrier = threading.Barrier(8)

    def write(thread: int) -> None:
        barrier.wait(timeout=30)
        for i in range(NUM_WRITES):
            store.set("a", {f"{thread}-{i}": i}, on_conflict="merge")
            store.get("a")

    with ThreadPoolExecutor(8) as executor:
        list(executor.map(write, range(8)))
    assert len(store.get("a")) == 8 * NUM_WRITES


# --- secrets ---


def test_repr_and_logs_hide_the_password(
    conninfo: str, table: str, caplog: pytest.LogCaptureFixture
) -> None:
    password = uuid.uuid4().hex
    url = with_password(conninfo, password)
    texts = []
    with caplog.at_level(logging.DEBUG):
        store = PostgresStore(url, table=table)
        with store:
            store.set("1", {})
            texts.append(repr(store))
        texts.append(repr(store))
    assert [text for text in [*texts, *caplog.messages] if password in text] == []


@pytest.mark.parametrize(
    ("options", "match"),
    [
        pytest.param({"dbname": "persista_missing"}, r"does not exist", id="database"),
        pytest.param({"port": "1"}, r"connection failed", id="port"),
    ],
)
def test_open_error_hides_the_password(
    conninfo: str, caplog: pytest.LogCaptureFixture, options: dict, match: str
) -> None:
    password = uuid.uuid4().hex
    store = PostgresStore(with_password(conninfo, password, **options), connect_timeout=5)
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(psycopg.OperationalError, match=match) as info,
    ):
        store.open()
    assert password not in "".join([str(info.value), repr(info.value), *caplog.messages])


@pytest.mark.parametrize(
    "template",
    [
        pytest.param("postgresql://postgres:PASSWORD@[127.0.0.1/db", id="bracket"),
        pytest.param("postgresql://postgres:x@PASSWORD@127.0.0.1/db", id="at"),
        pytest.param("postgresql://postgres:x/PASSWORD@127.0.0.1/db", id="slash"),
        pytest.param("host=127.0.0.1 password=x PASSWORD", id="space"),
    ],
)
def test_open_malformed_conninfo_hides_the_password(template: str) -> None:
    password = uuid.uuid4().hex
    store = PostgresStore(template.replace("PASSWORD", password))
    with pytest.raises(ValueError, match=r"Invalid PostgreSQL connection string") as info:
        store.open()
    assert password not in str(info.value) + repr(store)


# --- URI ---


def test_from_uri_with_the_options_reads_the_data(conninfo: str, table: str) -> None:
    codec = PickleCodec()
    with PostgresStore(conninfo, codec=codec, table=table) as store:
        store.set("1", {"tags": {"a"}})
        uri = store.to_uri()
    with PostgresStore.from_uri(uri, codec=codec, table=table) as restored:
        assert restored.get("1") == {"tags": {"a"}}


def test_connection_string_round_trips_through_a_uri(conninfo: str, table: str) -> None:
    secrets = ["p@ss word/?#%"]
    dsn = make_conninfo(conninfo, password=secrets[0], application_name="a b")
    with PostgresStore(dsn, table=table) as store:
        store.set("1", {})
        uri = store.to_uri()
    with PostgresStore.from_uri(uri, table=table) as restored:
        assert restored.get("1") == {}


def test_store_from_uri_uses_the_default_options(conninfo: str, server: Any) -> None:
    schema = f"persista_{uuid.uuid4().hex}"
    server.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    separator = "&" if "?" in conninfo else "?"
    uri = f"{conninfo}{separator}options=-c%20search_path%3D{schema}"
    try:
        with store_from_uri(uri) as restored:
            assert (type(restored), restored._table) == (PostgresStore, "store")
    finally:
        server.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_sqlite_data_moves_to_postgres(store: PostgresStore) -> None:
    value = {"title": "Intro", "year": 2024, "tags": ["a"], "score": 1.5, "none": None}
    with SQLiteStore() as source:
        source.set("1", value)
        for batch in source.iter_batches():
            store.set_many(batch)
    assert store.get("1") == value
