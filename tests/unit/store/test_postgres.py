r"""Unit tests of :class:`~persista.store.PostgresStore`.

They replace the connections by mocks, so they check what the store asks
the database to do. What a real server does with it is tested in
``tests/integration/store/``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from persista.store import JsonCodec, PickleCodec, PostgresStore
from persista.store.plan import build_plan
from persista.store.postgres import (
    _JSON_STRING_OR_LARGE_NUMBER,
    MAX_KEY_BYTES,
    _AsyncConnection,
    _check_conninfo,
    _check_keys,
    _conninfo_to_uri,
    _expand_number,
    _parse_location,
    _pipeline,
    _redact_conninfo,
    _to_jsonb,
)
from persista.testing.fixtures import psycopg_available, psycopg_not_available
from persista.utils.imports import is_psycopg_available

if is_psycopg_available():
    import psycopg

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

MODULE = "persista.store.postgres"

URL = "postgresql://localhost:5432/db"

SURROGATE = chr(0xD800)
NUL = chr(0)
BACKSLASH = chr(92)
# How a JSON document writes a NUL character in a string.
NUL_ESCAPE = BACKSLASH + "u0000"

HIDDEN = "<hidden PostgreSQL conninfo>"

JSON_COLUMNS = [("key", "text", True), ("value", "jsonb", False)]
PICKLE_COLUMNS = [("key", "text", True), ("value", "bytea", False)]

SPACE = 0x70657273

# Every primitive that takes keys.
KEY_PRIMITIVES = [
    pytest.param(lambda s, k: s._get_many(["a", k]), id="get_many"),
    pytest.param(lambda s, k: s._contains_many(["a", k]), id="contains_many"),
    pytest.param(lambda s, k: s._put_many({"a": "{}", k: "{}"}), id="put_many"),
    pytest.param(lambda s, k: s._update(["a", k], MagicMock()), id="update"),
    pytest.param(lambda s, k: s._delete_many(["a", k]), id="delete_many"),
]

ASYNC_KEY_PRIMITIVES = [
    pytest.param(lambda s, k: s._aget_many(["a", k]), id="aget_many"),
    pytest.param(lambda s, k: s._acontains_many(["a", k]), id="acontains_many"),
    pytest.param(lambda s, k: s._aput_many({"a": "{}", k: "{}"}), id="aput_many"),
    pytest.param(lambda s, k: s._aupdate(["a", k], MagicMock()), id="aupdate"),
    pytest.param(lambda s, k: s._adelete_many(["a", k]), id="adelete_many"),
]


def text(query: Any) -> str:
    r"""Return the SQL of a query."""
    return query if isinstance(query, str) else query.as_string(None)


def cursor(rows: list[Any]) -> MagicMock:
    r"""Return a cursor that reads some rows."""
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def acursor(rows: list[Any]) -> MagicMock:
    r"""Return an async cursor that reads some rows."""
    result = MagicMock()
    result.fetchall = AsyncMock(return_value=rows)
    return result


def sync_connection(columns: list[Any] | None = None) -> MagicMock:
    r"""Return a mock connection to a database that has the table."""
    connection = MagicMock()
    connection.execute.return_value = cursor(columns or JSON_COLUMNS)
    return connection


def async_connection() -> MagicMock:
    r"""Return a mock async connection, which is idle."""
    connection = MagicMock()
    connection.closed = False
    connection.info.transaction_status = psycopg.pq.TransactionStatus.IDLE
    connection.execute = AsyncMock(return_value=acursor([]))
    connection.close = AsyncMock()
    connection.set_isolation_level = AsyncMock()
    return connection


def built_store(**kwargs: Any) -> PostgresStore:
    r"""Return a store that is not open, with its queries."""
    store = PostgresStore(URL, **kwargs)
    store._build_queries()
    return store


def statements(connection: MagicMock) -> list[str]:
    r"""Return the SQL of the statements run on a mock connection."""
    return [text(call.args[0]) for call in connection.execute.call_args_list]


@pytest.fixture
def connection(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    r"""Replace the sync connection by a mock, and return it."""
    connection = sync_connection()
    monkeypatch.setattr(f"{MODULE}.psycopg.connect", MagicMock(return_value=connection))
    return connection


@pytest.fixture
def aconnection(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    r"""Replace the async connections by one mock, and return it."""
    connection = async_connection()
    monkeypatch.setattr(
        f"{MODULE}.psycopg.AsyncConnection.connect", AsyncMock(return_value=connection)
    )
    return connection


@pytest.fixture
def store(connection: MagicMock) -> Generator[PostgresStore, None, None]:
    with PostgresStore(URL) as store:
        connection.reset_mock()
        yield store


@pytest.fixture
async def astore(store: PostgresStore, aconnection: MagicMock) -> Any:
    del aconnection  # The store connects to the mock.
    yield store
    await store._aclose()


###################################
#     Tests for PostgresStore     #
###################################


# --- constructor ---


@psycopg_not_available
def test_init_without_psycopg() -> None:
    with pytest.raises(RuntimeError, match=r"'psycopg' package is required"):
        PostgresStore(URL)


@psycopg_available
def test_init_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock()
    monkeypatch.setattr(f"{MODULE}.psycopg.connect", connect)
    assert (PostgresStore(URL).closed, connect.call_count) == (True, 0)


@psycopg_available
def test_init_default_codec() -> None:
    assert isinstance(PostgresStore(URL)._codec, JsonCodec)


@psycopg_available
@pytest.mark.parametrize("table", ["", "1a", "a-b", 'a"b', "a; DROP TABLE b"])
def test_init_invalid_table_name(table: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid table name"):
        PostgresStore(URL, table=table)


@psycopg_available
def test_init_longest_table_name() -> None:
    assert PostgresStore(URL, table="a" * 63)._table == "a" * 63


@psycopg_available
def test_init_too_long_table_name() -> None:
    with pytest.raises(ValueError, match=r"at most 63 characters"):
        PostgresStore(URL, table="a" * 64)


@psycopg_available
def test_init_unsupported_codec() -> None:
    codec = MagicMock()
    codec.name = "yaml"
    with pytest.raises(ValueError, match=r"A SQL store needs a codec named"):
        PostgresStore(URL, codec=codec)


@psycopg_available
def test_init_codec_and_table_are_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        PostgresStore(URL, "documents")


# --- connection ---


@psycopg_available
def test_connection(store: PostgresStore, connection: MagicMock) -> None:
    assert store.connection is connection


@psycopg_available
def test_connection_closed_store() -> None:
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        _ = PostgresStore(URL).connection


# --- URI ---


@psycopg_available
@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_to_uri_keeps_a_uri(scheme: str) -> None:
    uri = f"{scheme}://user:secret@localhost/db?sslmode=require"
    assert PostgresStore(uri, table="t", codec=PickleCodec()).to_uri() == uri


@psycopg_available
def test_to_uri_converts_a_connection_string() -> None:
    store = PostgresStore("host=localhost port=5433 dbname=db user=ann")
    assert store.to_uri() == "postgresql://ann@localhost:5433/db"


@psycopg_available
@pytest.mark.parametrize("read_only", [True, False])
def test_from_uri(read_only: bool) -> None:
    store = PostgresStore.from_uri(URL, read_only=read_only)
    assert (store.to_uri(), store.closed) == (URL, True)


@psycopg_available
def test_from_uri_passes_the_arguments() -> None:
    codec = PickleCodec()
    store = PostgresStore.from_uri(URL, codec=codec, table="t", connect_timeout=3)
    assert (store._codec, store._table, store._kwargs) == (codec, "t", {"connect_timeout": 3})


# --- _open ---


@psycopg_available
def test__open_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock(return_value=sync_connection())
    monkeypatch.setattr(f"{MODULE}.psycopg.connect", connect)
    PostgresStore(URL, connect_timeout=3).open()
    connect.assert_called_once_with(URL, autocommit=True, connect_timeout=3)


@psycopg_available
def test__open_uses_read_committed(connection: MagicMock) -> None:
    with PostgresStore(URL):
        assert (connection.isolation_level, statements(connection)[0]) == (
            psycopg.IsolationLevel.READ_COMMITTED,
            "SET default_transaction_isolation = 'read committed'",
        )


@psycopg_available
def test__open_invalid_conninfo_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock()
    monkeypatch.setattr(f"{MODULE}.psycopg.connect", connect)
    with pytest.raises(ValueError, match=r"Invalid PostgreSQL connection string"):
        PostgresStore("host=localhost password=a b").open()
    assert connect.call_count == 0


@psycopg_available
def test__open_failure_closes_the_connection(connection: MagicMock) -> None:
    connection.execute.return_value = cursor(PICKLE_COLUMNS)
    store = PostgresStore(URL)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert (store.closed, connection.close.call_count, store._conn) == (True, 1, None)


# --- _close ---


@psycopg_available
def test__close(store: PostgresStore, connection: MagicMock) -> None:
    store._close()
    assert (connection.close.call_count, store._conn) == (1, None)


@psycopg_available
def test__close_without_connection(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=MODULE):
        PostgresStore(URL)._close()
    assert caplog.messages == []


@psycopg_available
def test__close_logs_no_password(connection: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    del connection
    with caplog.at_level(logging.DEBUG), PostgresStore("postgresql://u:s3cret@localhost/db"):
        pass
    assert "s3cret" not in caplog.text


# --- reads ---


@psycopg_available
def test__get_many_one_key(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("a", "{}")])
    assert store._get_many(["a"]) == {"a": "{}"}
    query, params = connection.execute.call_args.args
    assert (text(query), params) == (
        'SELECT key, value::text FROM "store" WHERE key = %s',
        ("a",),
    )


@psycopg_available
def test__get_many_several_keys(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("a", "{}")])
    assert store._get_many(["a", "b"]) == {"a": "{}"}
    query, params = connection.execute.call_args.args
    assert (text(query), params) == (
        'SELECT key, value::text FROM "store" WHERE key = ANY(%s)',
        (["a", "b"],),
    )


@psycopg_available
def test__contains_many(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("b",)])
    assert store._contains_many(["a", "b"]) == {"b"}


@psycopg_available
def test__count(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([(3,)])
    assert store._count() == 3


@psycopg_available
@pytest.mark.parametrize("key", [NUL, SURROGATE, "a" * (MAX_KEY_BYTES + 1)])
@pytest.mark.parametrize("operation", KEY_PRIMITIVES)
def test_rejected_key_runs_no_statement(
    store: PostgresStore,
    connection: MagicMock,
    operation: Callable[[PostgresStore, str], Any],
    key: str,
) -> None:
    with pytest.raises(ValueError, match=r"A key of PostgresStore"):
        operation(store, key)
    assert connection.mock_calls == []


# --- writes ---


@psycopg_available
def test__put_many_runs_one_statement(store: PostgresStore, connection: MagicMock) -> None:
    store._put_many({"a": "{}"})
    assert (connection.execute.call_count, connection.transaction.call_count) == (1, 0)


@psycopg_available
def test__put_many_locks_the_key(store: PostgresStore, connection: MagicMock) -> None:
    store._put_many({"a": "{}"})
    query, params = connection.execute.call_args.args
    assert ("pg_advisory_xact_lock(hashtextextended" in text(query), params) == (
        True,
        {"space": SPACE, "table": '"store"', "key": "a", "value": "{}"},
    )


@psycopg_available
def test__put_many_rejected_value(store: PostgresStore, connection: MagicMock) -> None:
    with pytest.raises(ValueError, match=r"cannot keep a NUL character"):
        store._put_many({"a": "{}", "b": f'{{"v": "{NUL_ESCAPE}"}}'})
    assert connection.mock_calls == []


@psycopg_available
def test__update_writes_the_result_of_the_plan(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("a", '{"x": 1}')])
    store._update(["a"], build_plan({"a": '{"y": 2}'}, "merge", JsonCodec()))
    assert connection.execute.call_args.args[1]["value"] == '{"x": 1, "y": 2}'


@psycopg_available
def test__update_locks_before_it_reads(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([])
    store._update(["a"], lambda _existing: {})
    table, lock, read = statements(connection)
    assert (table, "pg_advisory_xact_lock" in lock, read) == (
        'LOCK TABLE "store" IN ROW EXCLUSIVE MODE',
        True,
        'SELECT key, value::text FROM "store" WHERE key = %s',
    )


@psycopg_available
def test__update_runs_in_a_transaction(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([])
    store._update(["a"], lambda _existing: {})
    assert connection.transaction.call_count == 1


@psycopg_available
def test__update_plan_error_writes_nothing(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("a", "{}")])
    connection.transaction.return_value.__exit__.return_value = False
    with pytest.raises(KeyError, match=r"already exist"):
        store._update(["a"], build_plan({"a": "{}"}, "raise", JsonCodec()))
    assert not any("INSERT" in statement for statement in statements(connection))


@psycopg_available
def test__delete_many(store: PostgresStore, connection: MagicMock) -> None:
    store._delete_many(["a", "b"])
    _, lock, delete = connection.execute.call_args_list
    assert (lock.args[1]["keys"], text(delete.args[0]), delete.args[1]) == (
        ["a", "b"],
        'DELETE FROM "store" WHERE key = ANY(%s)',
        (["a", "b"],),
    )


@psycopg_available
def test__clear_locks_the_table(store: PostgresStore, connection: MagicMock) -> None:
    store._clear()
    _, lock, delete = statements(connection)
    assert ("pg_advisory_xact_lock(%(space)s" in lock, delete) == (True, 'DELETE FROM "store"')


# --- iteration ---


@psycopg_available
def test__iter_batches_uses_the_last_key(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.side_effect = [cursor([("a", "1"), ("b", "2")]), cursor([("c", "3")])]
    assert list(store._iter_batches(2)) == [{"a": "1", "b": "2"}, {"c": "3"}]
    assert [call.args[1] for call in connection.execute.call_args_list] == [(2,), ("b", 2)]


@psycopg_available
def test__iter_batches_full_last_batch(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.side_effect = [cursor([("a", "1")]), cursor([])]
    assert list(store._iter_batches(1)) == [{"a": "1"}]


@psycopg_available
def test__iter_batches_empty(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([])
    assert list(store._iter_batches(2)) == []


@psycopg_available
def test__iter_key_batches(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.side_effect = [cursor([("a",), ("b",)]), cursor([("c",)])]
    assert list(store._iter_key_batches(2)) == [["a", "b"], ["c"]]
    assert [call.args[1] for call in connection.execute.call_args_list] == [(2,), ("b", 2)]


@psycopg_available
def test__iter_key_batches_empty(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([])
    assert list(store._iter_key_batches(2)) == []


# --- filter ---


@psycopg_available
def test__filter_candidates_json(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("a", "{}")])
    assert list(store._filter_candidates({"author": "Alice"})) == [{"a": "{}"}]
    query, params = connection.execute.call_args.args
    assert (text(query), params) == (
        "SELECT key, value::text FROM \"store\" WHERE value->>'author' = %s::text",
        ["Alice"],
    )


@psycopg_available
def test__filter_candidates_pickle(connection: MagicMock) -> None:
    connection.execute.return_value = cursor(PICKLE_COLUMNS)
    with PostgresStore(URL, codec=PickleCodec()) as store:
        connection.execute.return_value = cursor([("a", b"x")])
        assert list(store._filter_candidates({"author": "Alice"})) == [{"a": b"x"}]
        assert "WHERE" not in statements(connection)[-1]


@psycopg_available
def test__select_candidates_no_match(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([])
    assert list(store._select_candidates({"a": 1})) == []


@psycopg_available
def test__filter_condition_str() -> None:
    assert PostgresStore(URL)._filter_condition("author", "Alice") == (
        "value->>'author' = %s::text",
        ["Alice"],
    )


@psycopg_available
def test__filter_condition_int() -> None:
    assert PostgresStore(URL)._filter_condition("year", -7) == (
        "value @> %s::jsonb",
        ['{"year": -7}'],
    )


@psycopg_available
@pytest.mark.parametrize("field", ["a'; DROP TABLE store; --", "a b", "a%s", "a\n"])
def test__filter_condition_invalid_field(field: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        PostgresStore(URL)._filter_condition(field, "x")


@psycopg_available
@pytest.mark.parametrize(
    "fields", [{}, {"a": None, "b": True, "c": 1.5, "d": [1], "e-f": "x", "g": 2**53}]
)
def test__filter_statement_without_condition(fields: dict[str, Any]) -> None:
    query, params = built_store()._filter_statement(fields)
    assert (text(query), params) == ('SELECT key, value::text FROM "store"', None)


@psycopg_available
def test__filter_statement() -> None:
    query, params = built_store()._filter_statement({"a": "x", "b": None, "c": 1})
    expected = (
        "SELECT key, value::text FROM \"store\" WHERE value->>'a' = %s::text AND value @> %s::jsonb"
    )
    assert (text(query), params) == (expected, ["x", '{"c": 1}'])


# --- async primitives ---


@psycopg_available
async def test__aget_many(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([("a", "{}")])
    assert await astore._aget_many(["a"]) == {"a": "{}"}


@psycopg_available
async def test__acontains_many(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([("b",)])
    assert await astore._acontains_many(["a", "b"]) == {"b"}


@psycopg_available
async def test__acount(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([(3,)])
    assert await astore._acount() == 3


@psycopg_available
@pytest.mark.parametrize("key", [NUL, SURROGATE, "a" * (MAX_KEY_BYTES + 1)])
@pytest.mark.parametrize("operation", ASYNC_KEY_PRIMITIVES)
async def test_async_rejected_key_runs_no_statement(
    astore: PostgresStore,
    aconnection: MagicMock,
    operation: Callable[[PostgresStore, str], Any],
    key: str,
) -> None:
    with pytest.raises(ValueError, match=r"A key of PostgresStore"):
        await operation(astore, key)
    assert aconnection.execute.await_count == 0


@psycopg_available
async def test__aput_many(astore: PostgresStore, aconnection: MagicMock) -> None:
    await astore._aput_many({"a": "{}"})
    # The first statement sets the isolation level of the connection.
    assert aconnection.execute.await_args.args[1] == {
        "space": SPACE,
        "table": '"store"',
        "key": "a",
        "value": "{}",
    }


@psycopg_available
async def test__aput_many_rejected_value(astore: PostgresStore, aconnection: MagicMock) -> None:
    with pytest.raises(ValueError, match=r"cannot keep a NUL character"):
        await astore._aput_many({"a": f'{{"v": "{NUL_ESCAPE}"}}'})
    assert aconnection.execute.await_count == 0


@psycopg_available
async def test__aupdate(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([("a", '{"x": 1}')])
    await astore._aupdate(["a"], build_plan({"a": '{"y": 2}'}, "merge", JsonCodec()))
    assert aconnection.execute.await_args.args[1]["value"] == '{"x": 1, "y": 2}'


@psycopg_available
async def test__aupdate_empty_plan(astore: PostgresStore, aconnection: MagicMock) -> None:
    await astore._aupdate(["a"], lambda _existing: {})
    assert not any("INSERT" in statement for statement in statements(aconnection))


@psycopg_available
async def test__adelete_many(astore: PostgresStore, aconnection: MagicMock) -> None:
    await astore._adelete_many(["a", "b"])
    lock, delete = aconnection.execute.await_args_list[-2:]
    assert (lock.args[1]["keys"], text(delete.args[0])) == (
        ["a", "b"],
        'DELETE FROM "store" WHERE key = ANY(%s)',
    )


@psycopg_available
async def test__aclear(astore: PostgresStore, aconnection: MagicMock) -> None:
    await astore._aclear()
    assert statements(aconnection)[-1] == 'DELETE FROM "store"'


@psycopg_available
async def test__aiter_batches(astore: PostgresStore, aconnection: MagicMock) -> None:
    async with astore._async_connection():
        pass
    aconnection.execute.side_effect = [acursor([("a", "1"), ("b", "2")]), acursor([("c", "3")])]
    assert [batch async for batch in astore._aiter_batches(2)] == [
        {"a": "1", "b": "2"},
        {"c": "3"},
    ]


@psycopg_available
async def test__aiter_batches_full_last_batch(
    astore: PostgresStore, aconnection: MagicMock
) -> None:
    async with astore._async_connection():
        pass
    aconnection.execute.side_effect = [acursor([("a", "1")]), acursor([])]
    assert [batch async for batch in astore._aiter_batches(1)] == [{"a": "1"}]


@psycopg_available
async def test__aiter_batches_closed_store(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([("a", "1")])
    batches = astore._aiter_batches(2)
    await anext(batches)
    await astore.aclose()
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        await anext(batches)


@psycopg_available
async def test__aiter_key_batches(astore: PostgresStore, aconnection: MagicMock) -> None:
    async with astore._async_connection():
        pass
    aconnection.execute.side_effect = [acursor([("a",), ("b",)]), acursor([])]
    assert [batch async for batch in astore._aiter_key_batches(2)] == [["a", "b"]]


@psycopg_available
async def test__aiter_key_batches_short_batch(
    astore: PostgresStore, aconnection: MagicMock
) -> None:
    aconnection.execute.return_value = acursor([("a",)])
    assert [batch async for batch in astore._aiter_key_batches(2)] == [["a"]]


@psycopg_available
async def test__aiter_key_batches_closed_store(
    astore: PostgresStore, aconnection: MagicMock
) -> None:
    aconnection.execute.return_value = acursor([("a",)])
    batches = astore._aiter_key_batches(2)
    await anext(batches)
    await astore.aclose()
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        await anext(batches)


@psycopg_available
async def test__afilter_candidates_json(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([("a", "{}")])
    assert [batch async for batch in astore._afilter_candidates({"a": 1})] == [{"a": "{}"}]
    assert "WHERE" in statements(aconnection)[-1]


@psycopg_available
async def test__afilter_candidates_pickle(connection: MagicMock, aconnection: MagicMock) -> None:
    connection.execute.return_value = cursor(PICKLE_COLUMNS)
    aconnection.execute.return_value = acursor([("a", b"x")])
    async with PostgresStore(URL, codec=PickleCodec()) as store:
        assert [batch async for batch in store._afilter_candidates({"a": 1})] == [{"a": b"x"}]
    assert "WHERE" not in statements(aconnection)[-1]


@psycopg_available
async def test__aselect_candidates_no_match(astore: PostgresStore) -> None:
    assert [batch async for batch in astore._aselect_candidates({"a": 1})] == []


@psycopg_available
async def test__aselect_candidates_closed_store(
    astore: PostgresStore, aconnection: MagicMock
) -> None:
    aconnection.execute.return_value = acursor([("a", "{}")])
    batches = astore._aselect_candidates({"a": 1})
    await anext(batches)
    await astore.aclose()
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        await anext(batches)


# --- lifecycle of the async connections ---


@psycopg_available
async def test__aclose(astore: PostgresStore, aconnection: MagicMock) -> None:
    async with astore._async_connection():
        pass
    await astore._aclose()
    assert (astore.closed, aconnection.close.await_count, len(astore._aclients)) == (
        False,
        1,
        0,
    )


@psycopg_available
async def test__check_close_with_an_async_connection(astore: PostgresStore) -> None:
    async with astore._async_connection():
        pass
    with pytest.raises(RuntimeError, match=r"An async client of PostgresStore is open"):
        astore._check_close()


@psycopg_available
def test__check_close_without_async_connection(store: PostgresStore) -> None:
    store._check_close()
    assert not store.closed


###########################################
#     Tests for the template helpers      #
###########################################


@psycopg_available
def test__query() -> None:
    query = PostgresStore(URL, table="Docs")._query(
        "SELECT {column} FROM {table}", column=psycopg.sql.SQL("key")
    )
    assert text(query) == 'SELECT key FROM "Docs"'


# --- schema ---


@psycopg_available
def test__init_schema_existing_table(store: PostgresStore, connection: MagicMock) -> None:
    store._init_schema()
    assert (len(statements(connection)), connection.transaction.call_count) == (1, 0)


@psycopg_available
@pytest.mark.parametrize(
    ("codec", "columns", "value_type"),
    [
        pytest.param(JsonCodec(), JSON_COLUMNS, "jsonb", id="json"),
        pytest.param(PickleCodec(), PICKLE_COLUMNS, "bytea", id="pickle"),
    ],
)
def test__init_schema_creates_the_table(
    connection: MagicMock, codec: Any, columns: list[Any], value_type: str
) -> None:
    connection.execute.side_effect = [
        cursor([]),  # SET
        cursor([]),  # The table does not exist.
        cursor([]),  # The lock.
        cursor([]),  # CREATE TABLE
        cursor(columns),
    ]
    with PostgresStore(URL, codec=codec):
        assert statements(connection)[3] == (
            'CREATE TABLE IF NOT EXISTS "store" '
            f"(key TEXT PRIMARY KEY, value {value_type} NOT NULL)"
        )


@psycopg_available
def test__init_schema_mismatch_hides_the_password(connection: MagicMock) -> None:
    connection.execute.return_value = cursor([("key", "text", True)])
    with pytest.raises(ValueError, match=r"does not match the codec") as info:
        PostgresStore("postgresql://u:s3cret@localhost/db").open()
    assert "s3cret" not in str(info.value)


@psycopg_available
def test__table_columns(store: PostgresStore, connection: MagicMock) -> None:
    assert store._table_columns() == JSON_COLUMNS
    assert connection.execute.call_args.args[1] == ('"store"',)


# --- statements ---


@psycopg_available
def test__fetch(store: PostgresStore, connection: MagicMock) -> None:
    connection.execute.return_value = cursor([(1,)])
    assert store._fetch("SELECT 1", ("a",)) == [(1,)]
    connection.execute.assert_called_once_with("SELECT 1", ("a",))


@psycopg_available
async def test__afetch(astore: PostgresStore, aconnection: MagicMock) -> None:
    aconnection.execute.return_value = acursor([(1,)])
    assert await astore._afetch("SELECT 1", ("a",)) == [(1,)]


@psycopg_available
def test__read_statement_one_key() -> None:
    query, params = built_store()._read_statement(["a"])
    assert (text(query).endswith("WHERE key = %s"), params) == (True, ("a",))


@psycopg_available
def test__read_statement_several_keys() -> None:
    query, params = built_store()._read_statement(["a", "b"])
    assert (text(query).endswith("WHERE key = ANY(%s)"), params) == (True, (["a", "b"],))


@psycopg_available
def test__write_statement_one_pair() -> None:
    query, params = built_store()._write_statement({"a": b"{}"})
    assert (text(query).startswith('INSERT INTO "store"'), params) == (
        True,
        {"space": SPACE, "table": '"store"', "key": "a", "value": "{}"},
    )


@psycopg_available
def test__write_statement_several_pairs() -> None:
    query, params = built_store()._write_statement({"a": "{}", "b": '{"x": 1e+22}'})
    assert ("unnest(%(keys)b::text[], %(values)b::text[])" in text(query), params) == (
        True,
        {
            "space": SPACE,
            "table": '"store"',
            "keys": ["a", "b"],
            "values": ["{}", '{"x": 10000000000000000000000.0}'],
        },
    )


@psycopg_available
def test__write_statement_many_pairs_lock_the_table() -> None:
    items = {str(i): "{}" for i in range(65)}
    query, params = built_store()._write_statement(items)
    assert (
        "pg_advisory_xact_lock_shared" in text(query),
        len(params["keys"]),
        len(params["values"]),
    ) == (False, 65, 65)


@psycopg_available
def test__write_statement_pickle_keeps_the_bytes() -> None:
    payload = NUL_ESCAPE.encode() + b"e+\xff"
    query, params = built_store(codec=PickleCodec())._write_statement({"a": payload, "b": b"x"})
    assert ("%(values)b::bytea[]" in text(query), params["values"]) == (True, [payload, b"x"])


@psycopg_available
def test__write_statement_does_not_modify_the_items() -> None:
    items = {"a": '{"x": 1e+22}'}
    built_store()._write_statement(items)
    assert items == {"a": '{"x": 1e+22}'}


@psycopg_available
@pytest.mark.parametrize(
    ("keys", "kind", "extra"),
    [
        pytest.param(None, "table", {}, id="every_key"),
        pytest.param(["a"], "key", {"key": "a"}, id="one"),
        pytest.param(["a", "b"], "keys", {"keys": ["a", "b"]}, id="two"),
        pytest.param(
            [str(i) for i in range(64)],
            "keys",
            {"keys": [str(i) for i in range(64)]},
            id="64",
        ),
        pytest.param([str(i) for i in range(65)], "table", {}, id="65"),
    ],
)
def test__lock_params(keys: list[str] | None, kind: str, extra: dict) -> None:
    assert PostgresStore(URL)._lock_params(keys) == (
        kind,
        {"space": SPACE, "table": '"store"', **extra},
    )


@psycopg_available
@pytest.mark.parametrize(
    ("keys", "fragments"),
    [
        pytest.param(None, ["SELECT 1 FROM (SELECT pg_advisory_xact_lock("], id="table"),
        pytest.param(["a"], ["pg_advisory_xact_lock_shared(", "hashtextextended("], id="key"),
        pytest.param(["a", "b"], ["pg_advisory_xact_lock_shared(", "ORDER BY id"], id="keys"),
    ],
)
def test__lock_statement(keys: list[str] | None, fragments: list[str]) -> None:
    query, _ = built_store()._lock_statement(keys)
    assert all(fragment in text(query) for fragment in fragments)


# --- transactions ---


@psycopg_available
def test__locked_transaction(store: PostgresStore, connection: MagicMock) -> None:
    with store._locked_transaction(["a"]) as used:
        assert used is connection
    assert [call[0] for call in connection.mock_calls[:3]] == [
        "transaction",
        "transaction().__enter__",
        "pipeline",
    ]


@psycopg_available
async def test__alocked_transaction(astore: PostgresStore, aconnection: MagicMock) -> None:
    async with astore._alocked_transaction(["a"]) as used:
        assert used is aconnection
    assert (aconnection.transaction.call_count, aconnection.pipeline.call_count) == (1, 1)


@psycopg_available
async def test__async_connection(astore: PostgresStore, aconnection: MagicMock) -> None:
    async with astore._async_connection() as used:
        assert used is aconnection


@psycopg_available
async def test__async_connection_closed_store() -> None:
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        async with PostgresStore(URL)._async_connection():
            pass


@psycopg_available
async def test__async_connection_closed_while_waiting(astore: PostgresStore) -> None:
    async def use() -> None:
        async with astore._async_connection():
            pass

    async with astore._async_connection():
        task = asyncio.ensure_future(use())
        await asyncio.sleep(0)
        # A sync close from another thread, which does not see the loop.
        astore._closed = True
    with pytest.raises(RuntimeError, match=r"PostgresStore is not open"):
        await task
    astore._closed = False


@psycopg_available
def test__create_async_connection() -> None:
    store = PostgresStore(URL)

    async def create() -> _AsyncConnection:
        return store._create_async_connection()

    assert asyncio.run(create())._connect == store._connect_async


@psycopg_available
async def test__connect_async(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = async_connection()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(f"{MODULE}.psycopg.AsyncConnection.connect", connect)
    assert await PostgresStore(URL, connect_timeout=3)._connect_async() is connection
    connect.assert_awaited_once_with(URL, autocommit=True, connect_timeout=3)
    connection.set_isolation_level.assert_awaited_once_with(psycopg.IsolationLevel.READ_COMMITTED)


@psycopg_available
async def test__connect_async_setup_failure_closes_the_connection(
    aconnection: MagicMock,
) -> None:
    aconnection.execute.side_effect = OSError("lost")
    with pytest.raises(OSError, match=r"lost"):
        await PostgresStore(URL)._connect_async()
    assert aconnection.close.await_count == 1


# --- repr ---


@psycopg_available
@pytest.mark.parametrize("operation", [repr, str])
@pytest.mark.parametrize(
    "conninfo",
    [
        "postgresql://admin:s3cret@localhost/db",
        "postgresql://localhost/db?user=admin&password=s3cret",
        "host=localhost user=admin password=s3cret",
        "postgresql://admin:s3@cret@localhost/db",
        "postgresql://admin:s3cret/x@localhost/db",
        "host=localhost password=a s3cret",
    ],
)
def test_repr_hides_the_credentials(operation: Callable[[Any], str], conninfo: str) -> None:
    secrets = ["s3cret"]
    result = operation(PostgresStore(conninfo, password=secrets[0]))
    assert "cret" not in result


@psycopg_available
def test_repr_runs_no_query(store: PostgresStore, connection: MagicMock) -> None:
    repr(store)
    assert connection.mock_calls == []


@psycopg_available
def test__get_repr_kwargs() -> None:
    secrets = ["s3cret", "other"]
    store = PostgresStore(f"postgresql://u:{secrets[0]}@localhost/db", password=secrets[1])
    assert store._get_repr_kwargs() == {
        "conninfo": "postgresql://localhost/db",
        "table": "store",
        "closed": True,
    }


@psycopg_available
def test__get_repr_kwargs_codec_and_open(connection: MagicMock) -> None:
    connection.execute.return_value = cursor(PICKLE_COLUMNS)
    codec = PickleCodec()
    with PostgresStore(URL, codec=codec, table="t") as store:
        assert store._get_repr_kwargs() == {
            "conninfo": URL,
            "table": "t",
            "closed": False,
            "codec": codec,
        }


#######################################
#     Tests for _AsyncConnection      #
#######################################


@psycopg_available
async def test_async_connection_exclusive_connects_once() -> None:
    connect = AsyncMock(return_value=async_connection())
    holder = _AsyncConnection(connect)
    for _ in range(2):
        async with holder.exclusive():
            pass
    assert connect.await_count == 1


@psycopg_available
async def test_async_connection_exclusive_one_user_at_a_time() -> None:
    holder = _AsyncConnection(AsyncMock(return_value=async_connection()))
    entered = asyncio.Event()

    async def use() -> None:
        async with holder.exclusive():
            entered.set()

    async with holder.exclusive():
        task = asyncio.ensure_future(use())
        await asyncio.sleep(0)
        waiting = not entered.is_set()
    await task
    assert (waiting, entered.is_set()) == (True, True)


@psycopg_available
async def test_async_connection_exclusive_replaces_a_closed_connection() -> None:
    first, second = async_connection(), async_connection()
    holder = _AsyncConnection(AsyncMock(side_effect=[first, second]))
    async with holder.exclusive():
        pass
    first.closed = True
    async with holder.exclusive() as used:
        assert used is second


@psycopg_available
@pytest.mark.parametrize("status", ["ACTIVE", "INTRANS", "INERROR", "UNKNOWN"])
async def test_async_connection_exclusive_discards_a_busy_connection(status: str) -> None:
    connection = async_connection()
    holder = _AsyncConnection(AsyncMock(return_value=connection))
    async with holder.exclusive():
        connection.info.transaction_status = psycopg.pq.TransactionStatus[status]
    assert (connection.close.await_count, holder._connection) == (1, None)


@psycopg_available
async def test_async_connection_exclusive_error_keeps_an_idle_connection() -> None:
    connection = async_connection()
    holder = _AsyncConnection(AsyncMock(return_value=connection))

    async def fail() -> None:
        async with holder.exclusive():
            msg = "conflict"
            raise KeyError(msg)

    with pytest.raises(KeyError, match=r"conflict"):
        await fail()
    assert (connection.close.await_count, holder._connection) == (0, connection)


@psycopg_available
async def test_async_connection_exclusive_connection_failure() -> None:
    connection = async_connection()
    holder = _AsyncConnection(AsyncMock(side_effect=[OSError("no server"), connection]))
    with pytest.raises(OSError, match=r"no server"):
        async with holder.exclusive():
            pass
    async with holder.exclusive() as used:
        assert used is connection


@psycopg_available
async def test_async_connection_aclose() -> None:
    connection = async_connection()
    holder = _AsyncConnection(AsyncMock(return_value=connection))
    async with holder.exclusive():
        pass
    await holder.aclose()
    await holder.aclose()
    assert (connection.close.await_count, holder._connection) == (1, None)


@psycopg_available
async def test_async_connection_abandon() -> None:
    connection = async_connection()
    holder = _AsyncConnection(AsyncMock(return_value=connection))
    async with holder.exclusive():
        pass
    holder.abandon()
    holder.abandon()
    assert (connection.pgconn.finish.call_count, holder._connection) == (1, None)


###############################
#     Tests for _pipeline     #
###############################


@psycopg_available
def test__pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.psycopg.Pipeline.is_supported", lambda: True)
    connection = MagicMock()
    assert _pipeline(connection) is connection.pipeline.return_value


@psycopg_available
def test__pipeline_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}.psycopg.Pipeline.is_supported", lambda: False)
    assert isinstance(_pipeline(MagicMock()), contextlib.nullcontext)


##################################
#     Tests for _check_keys      #
##################################


@pytest.mark.parametrize(
    "key",
    ["", "a", "é" * (MAX_KEY_BYTES // 2), "a" * MAX_KEY_BYTES, BACKSLASH + "0", "🎉"],
)
def test__check_keys(key: str) -> None:
    keys = [key]
    _check_keys(keys)
    assert keys == [key]


def test__check_keys_empty() -> None:
    keys: list[str] = []
    _check_keys(keys)
    assert keys == []


@pytest.mark.parametrize(
    ("key", "match"),
    [
        pytest.param(NUL, r"cannot contain a NUL character", id="nul"),
        pytest.param(f"a{NUL}b", r"cannot contain a NUL character", id="inner_nul"),
        pytest.param(SURROGATE, r"lone surrogate", id="surrogate"),
        pytest.param("a" * (MAX_KEY_BYTES + 1), r"has 2693 bytes", id="too_long"),
        pytest.param("é" * (MAX_KEY_BYTES // 2 + 1), r"has 2694 bytes", id="too_long_utf8"),
    ],
)
def test__check_keys_rejected(key: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _check_keys(["a", key])


#################################
#     Tests for _to_jsonb       #
#################################


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param("{}", "{}", id="empty"),
        pytest.param(b'{"a": "\xc3\xa9"}', '{"a": "é"}', id="bytes"),
        pytest.param('{"a": 1e-07}', '{"a": 1e-07}', id="negative_exponent"),
        pytest.param('{"a": 1e+16}', '{"a": 10000000000000000.0}', id="large"),
        pytest.param(
            '{"a": [-1.5e+22, 2e+16]}',
            '{"a": [-15000000000000000000000.0, 20000000000000000.0]}',
            id="several",
        ),
        pytest.param('{"1e+22": "2e+22"}', '{"1e+22": "2e+22"}', id="strings"),
        pytest.param(
            f'{{"a": "{BACKSLASH}"1e+22", "b": 1e+16}}',
            f'{{"a": "{BACKSLASH}"1e+22", "b": 10000000000000000.0}}',
            id="escaped_quote",
        ),
        pytest.param(
            f'{{"a": "{BACKSLASH}{NUL_ESCAPE}"}}',
            f'{{"a": "{BACKSLASH}{NUL_ESCAPE}"}}',
            id="escaped_backslash_before_u0000",
        ),
    ],
)
def test__to_jsonb(payload: str | bytes, expected: str) -> None:
    assert _to_jsonb(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(f'{{"a": "{NUL_ESCAPE}"}}', id="value"),
        pytest.param(f'{{"{NUL_ESCAPE}": 1}}', id="key"),
        pytest.param(f'{{"a": "x{BACKSLASH}{BACKSLASH}{NUL_ESCAPE}"}}', id="after_backslash"),
    ],
)
def test__to_jsonb_nul(payload: str) -> None:
    with pytest.raises(ValueError, match=r"cannot keep a NUL character"):
        _to_jsonb(payload)


#####################################
#     Tests for _expand_number      #
#####################################


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param("1e+16", "10000000000000000.0", id="integer_mantissa"),
        pytest.param("-1.25e+20", "-125000000000000000000.0", id="negative"),
        pytest.param('"1e+16"', '"1e+16"', id="string"),
    ],
)
def test__expand_number(document: str, expected: str) -> None:
    assert _expand_number(_JSON_STRING_OR_LARGE_NUMBER.fullmatch(document)) == expected


def test__expand_number_keeps_the_float() -> None:
    document = repr(1.7976931348623157e308)
    result = _expand_number(_JSON_STRING_OR_LARGE_NUMBER.fullmatch(document))
    assert float(result) == 1.7976931348623157e308


######################################
#     Tests for _parse_location      #
######################################


@psycopg_available
@pytest.mark.parametrize(
    ("conninfo", "expected"),
    [
        pytest.param(URL, ("localhost", "5432", "db"), id="uri"),
        pytest.param("host=h dbname=d", ("h", "", "d"), id="string"),
        pytest.param("", ("", "", ""), id="empty"),
        pytest.param("host=@abstract", ("@abstract", "", ""), id="abstract_socket"),
        pytest.param("host=a,b port=1,2", ("a,b", "1,2", ""), id="several_servers"),
    ],
)
def test__parse_location(conninfo: str, expected: tuple[str, str, str]) -> None:
    assert _parse_location(conninfo, {}) == expected


@psycopg_available
def test__parse_location_kwargs_take_precedence() -> None:
    kwargs = {"host": "other", "port": 1, "password": "s3cret"}
    assert _parse_location(URL, kwargs) == ("other", "1", "db")


@psycopg_available
@pytest.mark.parametrize(
    "conninfo",
    [
        pytest.param("host=h password=a b", id="unreadable"),
        pytest.param("postgresql://u:%zz@h/db", id="bad_escape"),
        pytest.param("postgresql://u:se@cret@h/db", id="at_in_password"),
        pytest.param("postgresql://u:se/cret@h/db", id="slash_in_password"),
        pytest.param("postgresql://u:12/cret@h/db", id="slash_after_digits"),
    ],
)
def test__parse_location_invalid(conninfo: str) -> None:
    assert _parse_location(conninfo, {}) is None


######################################
#     Tests for _check_conninfo      #
######################################


@psycopg_available
def test__check_conninfo() -> None:
    conninfo = "postgresql://u:p%40ss@localhost/db"
    _check_conninfo(conninfo)
    assert _parse_location(conninfo, {}) == ("localhost", "", "db")


@psycopg_available
@pytest.mark.parametrize(
    "conninfo",
    [
        "host=h password=a s3cret",
        "postgresql://u:s3cret@[h/db",
        "postgresql://u:s3@cret@h/db",
        "postgresql://u:1234/s3cret@h/db",
        "postgresx://u:s3cret@h/db",
    ],
)
def test__check_conninfo_invalid_hides_the_password(conninfo: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid PostgreSQL connection string") as info:
        _check_conninfo(conninfo)
    assert ("cret" in str(info.value), info.value.__suppress_context__) == (False, False)


#######################################
#     Tests for _redact_conninfo      #
#######################################


@psycopg_available
@pytest.mark.parametrize(
    ("conninfo", "expected"),
    [
        pytest.param("postgresql://u:p@localhost:5432/db", URL, id="uri"),
        pytest.param("host=localhost dbname=db password=p", "postgresql://localhost/db", id="dsn"),
        pytest.param("", "postgresql:///", id="empty"),
        pytest.param("postgresql://u:se@cret@h/db", HIDDEN, id="at_in_password"),
        pytest.param("dbname='postgresql://u:p@h/db'", HIDDEN, id="uri_as_dbname"),
        pytest.param("dbname='password=p'", HIDDEN, id="string_as_dbname"),
    ],
)
def test__redact_conninfo(conninfo: str, expected: str) -> None:
    assert _redact_conninfo(conninfo, {}) == expected


@psycopg_available
def test__redact_conninfo_kwargs() -> None:
    assert _redact_conninfo(URL, {"dbname": "other"}) == "postgresql://localhost:5432/other"


######################################
#     Tests for _conninfo_to_uri     #
######################################


@psycopg_available
@pytest.mark.parametrize(
    ("conninfo", "uri"),
    [
        pytest.param("dbname=db", "postgresql:///db", id="dbname"),
        pytest.param(
            "host=h port=1 dbname=d user=u password=p",
            "postgresql://u:p@h:1/d",
            id="all",
        ),
        pytest.param(
            "host=h dbname=d user=u password='p@s:s/w?d#'",
            "postgresql://u:p%40s%3As%2Fw%3Fd%23@h/d",
            id="special_password",
        ),
        pytest.param("host=/var/run/pg dbname=d", "postgresql://%2Fvar%2Frun%2Fpg/d", id="socket"),
        pytest.param("host=::1 dbname=d", "postgresql://[::1]/d", id="ipv6"),
        pytest.param(
            "host=a,b port=1,2 dbname=d",
            "postgresql:///d?host=a%2Cb&port=1%2C2",
            id="several_servers",
        ),
        pytest.param("host=h password=p", "postgresql://:p@h/", id="password_only"),
        pytest.param(
            "host=h options='-c a=b'",
            "postgresql://h/?options=-c%20a%3Db",
            id="option_with_space",
        ),
    ],
)
def test__conninfo_to_uri(conninfo: str, uri: str) -> None:
    assert _conninfo_to_uri(conninfo) == uri


@psycopg_available
@pytest.mark.parametrize(
    "conninfo",
    [
        "host=h dbname=d user=u password='p@s:s/w?d#%'",
        "host=/var/run/pg dbname='a b' user='a@b'",
        "host=::1 port=5432 dbname=d",
        "host=a,b port=1,2 dbname=d",
        "host=h password=p options='-c a=b'",
    ],
)
def test__conninfo_to_uri_keeps_the_options(conninfo: str) -> None:
    parse = psycopg.conninfo.conninfo_to_dict
    assert parse(_conninfo_to_uri(conninfo)) == parse(conninfo)


@psycopg_available
def test_open_checks_the_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    store = PostgresStore(URL)
    error = RuntimeError("the driver is missing")
    monkeypatch.setattr("persista.store.postgres.check_psycopg", MagicMock(side_effect=error))
    with pytest.raises(RuntimeError, match=r"the driver is missing"):
        store.open()
    assert store.closed


@psycopg_available
@pytest.mark.parametrize(
    "conninfo",
    [
        "redis://user:s3cret@localhost:1/0",
        "user:s3cret@localhost",
        "host=localhost password=s3cret bogus",
        "password=s3cret host='unterminated",
    ],
)
def test_to_uri_malformed_string_hides_the_password(conninfo: str) -> None:
    store = PostgresStore(conninfo)
    with pytest.raises(ValueError, match=r"Invalid PostgreSQL connection string") as info:
        store.to_uri()
    assert "s3cret" not in "".join(traceback.format_exception(info.value))


@psycopg_available
def test_to_uri_does_not_parse_a_uri_with_invalid_characters() -> None:
    uri = f"postgresql://user:s3cret@ho{chr(0x2100)}st/db"
    assert PostgresStore(uri).to_uri() == uri


@psycopg_available
def test_init_builds_no_query() -> None:
    assert not hasattr(PostgresStore(URL), "_select")


@psycopg_available
def test__build_queries() -> None:
    store = PostgresStore(URL, table="docs")
    store._build_queries()
    assert text(store._select) == 'SELECT key, value::text FROM "docs"'


@psycopg_available
def test__build_queries_pickle_codec() -> None:
    store = PostgresStore(URL, codec=PickleCodec())
    store._build_queries()
    assert text(store._select) == 'SELECT key, value FROM "store"'
