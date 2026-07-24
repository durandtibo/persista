from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from persista.store import PostgresStore, TypedPostgresStore
from persista.utils.imports import is_psycopg_available

if TYPE_CHECKING:
    from typing import Self

    from persista.store import BasePostgresStore


if is_psycopg_available():
    from psycopg.types.json import Jsonb

psycopg = pytest.importorskip("psycopg")

logger = logging.getLogger(__name__)

MODULE = "persista.store.postgres"


# ---------------------------------------------------------------------------
# Fake psycopg connection
#
# Unlike SQLiteStore (":memory:") or RedisStore (fakeredis), there is no
# lightweight in-process stand-in for a real Postgres server. This fake
# mimics just enough of psycopg's connection/cursor protocol -- and the
# handful of SQL shapes BasePostgresStore/PostgresStore/TypedPostgresStore
# actually generate -- to exercise real store behavior end-to-end without a
# live server, the same role fakeredis plays for RedisStore. Real server
# behavior (actual SQL execution, encoding, transactions) is covered
# separately in tests/integration/store/test_postgres.py.
# ---------------------------------------------------------------------------


def _sql_text(query: Any) -> str:
    text = query.as_string(None) if hasattr(query, "as_string") else str(query)
    return " ".join(text.split())


def _unwrap(value: Any) -> Any:
    return value.obj if isinstance(value, Jsonb) else value


_CREATE_RE = re.compile(r'^CREATE TABLE IF NOT EXISTS "(\w+)"')
_INSERT_RE = re.compile(r'^INSERT INTO "(\w+)"')
_DELETE_ANY_RE = re.compile(r'^DELETE FROM "(\w+)" WHERE "[^"]+" = ANY\(%s\)$')
_DELETE_ONE_RE = re.compile(r'^DELETE FROM "(\w+)" WHERE "[^"]+" = %s$')
_DELETE_ALL_RE = re.compile(r'^DELETE FROM "(\w+)"$')
_COUNT_RE = re.compile(r'^SELECT COUNT\(\*\) FROM "(\w+)"$')
_EXISTS_RE = re.compile(r'^SELECT 1 FROM "(\w+)" WHERE "([^"]+)" = %s LIMIT 1$')
_COL_ANY_RE = re.compile(r'^SELECT "([^"]+)" FROM "(\w+)" WHERE "[^"]+" = ANY\(%s\)$')
_COL_ALL_RE = re.compile(r'^SELECT "([^"]+)" FROM "(\w+)"$')
_STAR_RE = re.compile(r'^SELECT \* FROM "(\w+)"(?: WHERE (.+))?$')
_TEXT_COND_RE = re.compile(r"^(?:value|extra)->>'([^']+)' = %s::text$")
_COL_COND_RE = re.compile(r'^"([^"]+)" = %s$')


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self.itersize = 32
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def __iter__(self) -> Iterator[tuple[Any, ...]]:
        return iter(self._rows)

    def execute(self, query: Any, params: Any = None) -> FakeCursor:
        self._rows = self.conn.dispatch_read(_sql_text(query), params or ())
        return self

    def executemany(self, query: Any, seq: Any) -> None:
        text = _sql_text(query)
        for row in seq:
            self.conn.dispatch_insert(text, row)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class FakeConnection:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, tuple[Any, ...]]] = {}
        # Wired up by `_connect()` right after the store is constructed, so
        # filter-condition evaluation can reuse the store's own
        # `_row_to_value` instead of duplicating its schema/extra logic.
        self.store: BasePostgresStore | None = None
        self.closed = False

    def cursor(self, name: str | None = None) -> FakeCursor:  # noqa: ARG002
        return FakeCursor(self)

    def execute(self, query: Any, params: Any = None) -> None:
        self.dispatch_write(_sql_text(query), params or ())

    def close(self) -> None:
        self.closed = True

    def transaction(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()

    # -- dispatch --

    def dispatch_write(self, text: str, params: tuple[Any, ...]) -> None:
        if m := _CREATE_RE.match(text):
            self.tables.setdefault(m.group(1), {})
            return
        if m := _DELETE_ANY_RE.match(text):
            table = self.tables.setdefault(m.group(1), {})
            for key in params[0]:
                table.pop(key, None)
            return
        if m := _DELETE_ONE_RE.match(text):
            table = self.tables.setdefault(m.group(1), {})
            table.pop(params[0], None)
            return
        if m := _DELETE_ALL_RE.match(text):
            self.tables[m.group(1)] = {}
            return
        msg = f"Unsupported write query in FakeConnection: {text!r}"
        raise AssertionError(msg)

    def dispatch_insert(self, text: str, row: tuple[Any, ...]) -> None:
        m = _INSERT_RE.match(text)
        if not m:
            msg = f"Unsupported insert query in FakeConnection: {text!r}"
            raise AssertionError(msg)
        table = self.tables.setdefault(m.group(1), {})
        table[row[0]] = tuple(_unwrap(v) for v in row)

    def dispatch_read(self, text: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        if m := _COUNT_RE.match(text):
            return [(len(self.tables.get(m.group(1), {})),)]
        if m := _EXISTS_RE.match(text):
            table = self.tables.get(m.group(1), {})
            return [(1,)] if params[0] in table else []
        if m := _COL_ANY_RE.match(text):
            table = self.tables.get(m.group(2), {})
            return [(key,) for key in params[0] if key in table]
        if m := _COL_ALL_RE.match(text):
            table = self.tables.get(m.group(2), {})
            return [(key,) for key in table]
        if m := _STAR_RE.match(text):
            table = self.tables.get(m.group(1), {})
            where = m.group(2)
            if where is None:
                return list(table.values())
            assert self.store is not None
            key_col = self.store._key_column
            single_col_match = _COL_COND_RE.match(where)
            if single_col_match and single_col_match.group(1) == key_col:
                row = table.get(params[0])
                return [row] if row is not None else []
            if re.match(rf'^"{re.escape(key_col)}" = ANY\(%s\)$', where):
                return [table[key] for key in params[0] if key in table]
            return self._filter(table, where, params)
        msg = f"Unsupported read query in FakeConnection: {text!r}"
        raise AssertionError(msg)

    def _filter(
        self, table: dict[str, tuple[Any, ...]], where: str, params: tuple[Any, ...]
    ) -> list[tuple[Any, ...]]:
        fields: list[str] = []
        is_text: list[bool] = []
        for cond in (c.strip() for c in where.split(" AND ")):
            if m := _TEXT_COND_RE.match(cond):
                fields.append(m.group(1))
                is_text.append(True)
            elif m := _COL_COND_RE.match(cond):
                fields.append(m.group(1))
                is_text.append(False)
            else:
                msg = f"Unsupported filter condition in FakeConnection: {cond!r}"
                raise AssertionError(msg)
        assert self.store is not None
        matches = []
        for row in table.values():
            value = self.store._row_to_value(row)
            if all(
                (str(value.get(field)) == str(param) if text_cast else value.get(field) == param)
                for field, text_cast, param in zip(fields, is_text, params, strict=True)
            ):
                matches.append(row)
        return matches


def _connect(store_cls: type[BasePostgresStore], table: str = "store", **kwargs: Any) -> Any:
    """Construct a store against a fresh :class:`FakeConnection`.

    Also pre-populates the store's lazy async connection slot with an
    :class:`_AsyncConnAdapter` wrapping the *same* fake connection (and
    therefore the same in-memory tables), so ``store._ensure_aconn()``
    returns it immediately without ever calling the real
    ``psycopg.AsyncConnection.connect`` -- sync and async operations
    against the returned store share one consistent view of the data,
    mirroring how a real Postgres server would behave.
    """
    conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        store = store_cls("postgresql://x", table=table, **kwargs)
    conn.store = store
    store._aconn = _AsyncConnAdapter(conn)
    return store


# ---------------------------------------------------------------------------
# Async adapter over FakeConnection
#
# BasePostgresStore's async methods go through psycopg.AsyncConnection, not
# psycopg.Connection. Rather than duplicate FakeConnection's dispatch logic
# for a second, async-flavored fake, these adapters wrap the exact same
# FakeConnection/FakeCursor instance with an async-compatible surface, so a
# single store's sync and async operations observe the same table state.
# ---------------------------------------------------------------------------


class _AsyncCursorAdapter:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def __aiter__(self) -> Any:
        return _aiter(self._cursor._rows)

    async def execute(self, query: Any, params: Any = None) -> _AsyncCursorAdapter:
        self._cursor.execute(query, params)
        return self

    async def executemany(self, query: Any, seq: Any) -> None:
        self._cursor.executemany(query, seq)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._cursor.fetchall()

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._cursor.fetchone()

    @property
    def itersize(self) -> int:
        return self._cursor.itersize

    @itersize.setter
    def itersize(self, value: int) -> None:
        self._cursor.itersize = value


async def _aiter(rows: list[tuple[Any, ...]]) -> Any:
    for row in rows:
        yield row


class _AsyncNullContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _AsyncConnAdapter:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def cursor(self, name: str | None = None) -> _AsyncCursorAdapter:
        return _AsyncCursorAdapter(self._conn.cursor(name))

    async def execute(self, query: Any, params: Any = None) -> None:
        self._conn.execute(query, params)

    async def close(self) -> None:
        self._conn.close()

    def transaction(self) -> _AsyncNullContext:
        return _AsyncNullContext()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=[PostgresStore, TypedPostgresStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[BasePostgresStore]:
    return request.param


@pytest.fixture
def store(store_cls: type[BasePostgresStore]) -> BasePostgresStore:
    return _connect(store_cls)


@pytest.fixture
def typed_store_no_schema() -> TypedPostgresStore:
    """Store with no schema (everything in `extra`)."""
    return _connect(TypedPostgresStore)


@pytest.fixture
def typed_store() -> TypedPostgresStore:
    """Store with a typed schema."""
    return _connect(
        TypedPostgresStore, value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"}
    )


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


#####################################################
#     Tests for PostgresStore/TypedPostgresStore     #
#####################################################


# --- constructor ---


def test_invalid_table_name_raises_before_connect(store_cls: type[BasePostgresStore]) -> None:
    with patch(f"{MODULE}.psycopg.connect") as mock_connect:
        with pytest.raises(ValueError, match="Invalid table name"):
            store_cls("postgresql://x", table="bad; DROP TABLE store;--")
        mock_connect.assert_not_called()


def test_valid_table_name_calls_connect(store_cls: type[BasePostgresStore]) -> None:
    with patch(f"{MODULE}.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        store_cls("postgresql://x", table="mytable")
        mock_connect.assert_called_once_with("postgresql://x", autocommit=True)


def test_init_creates_table(store: BasePostgresStore) -> None:
    assert store.count() == 0


def test_init_accepts_psycopg_connect_kwargs(store_cls: type[BasePostgresStore]) -> None:
    store = _connect(store_cls, connect_timeout=5)
    assert store.count() == 0


def test_two_stores_different_tables_are_isolated(store_cls: type[BasePostgresStore]) -> None:
    conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        store_a = store_cls("postgresql://x", table="store_a")
        store_b = store_cls("postgresql://x", table="store_b")
    conn.store = store_a
    store_a.set("1", {"text": "a"})
    assert store_b.get("1") is None
    assert store_b.count() == 0


# --- to_uri/from_uri ---


def test_to_uri_returns_conninfo_unchanged(store: BasePostgresStore) -> None:
    assert store.to_uri() == store._conninfo


def test_from_uri_constructs_with_same_conninfo(store_cls: type[BasePostgresStore]) -> None:
    conninfo = "postgresql://user:pass@localhost/dbname"
    conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        new_store = store_cls.from_uri(conninfo)
    conn.store = new_store
    assert new_store._conninfo == conninfo
    new_store.set("1", {"text": "a"})
    assert new_store.get("1") == {"text": "a"}


def test_from_uri_ignores_read_only(store_cls: type[BasePostgresStore]) -> None:
    conninfo = "postgresql://user:pass@localhost/dbname"
    conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        new_store = store_cls.from_uri(conninfo, read_only=True)
    conn.store = new_store
    assert new_store._conninfo == conninfo
    new_store.set("1", {"text": "a"})
    assert new_store.get("1") == {"text": "a"}


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


def test_get_many_duplicate_keys_returns_value_for_each_occurrence(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "1"])
    assert result == [items["1"], items["1"]]


def test_get_propagates_connection_error(store: BasePostgresStore) -> None:
    with (
        patch.object(
            store._conn, "cursor", side_effect=psycopg.OperationalError("connection lost")
        ),
        pytest.raises(psycopg.OperationalError, match="connection lost"),
    ):
        store.get("1")


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


# --- clear ---


def test_clear_removes_all_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.clear()
    assert store.count() == 0
    assert list(store.keys()) == []


def test_clear_empty_store_is_no_op(store: BasePostgresStore) -> None:
    store.clear()
    assert store.count() == 0


def test_clear_returns_none(store: BasePostgresStore) -> None:
    assert store.clear() is None


def test_clear_then_set_works(store: BasePostgresStore) -> None:
    store.set("1", {"text": "hello"})
    store.clear()
    store.set("2", {"text": "world"})
    assert store.count() == 1
    assert store.get("2") == {"text": "world"}


# --- contains ---


def test_contains_true_when_key_present(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains("1")


def test_contains_false_when_key_missing(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert not store.contains("99")


def test_contains_false_when_store_empty(store: BasePostgresStore) -> None:
    assert not store.contains("1")


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
    assert store._conn.closed


def test_close_is_idempotent(store: BasePostgresStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BasePostgresStore) -> None:
    assert store.close() is None


async def test_close_from_running_event_loop_raises(store: BasePostgresStore) -> None:
    assert store._aconn is not None
    with pytest.raises(RuntimeError, match="inside a running event loop"):
        store.close()


# --- closed ---


def test_closed_false_before_close(store: BasePostgresStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: BasePostgresStore) -> None:
    store.close()
    assert store.closed


# --- context manager ---


def test_context_manager_returns_self(
    store: BasePostgresStore, store_cls: type[BasePostgresStore]
) -> None:
    assert isinstance(store, store_cls)


def test_context_manager_closes_on_normal_exit(store_cls: type[BasePostgresStore]) -> None:
    with _connect(store_cls) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
    assert store._conn.closed


def test_context_manager_closes_on_exception(store_cls: type[BasePostgresStore]) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), _connect(store_cls) as store:
        raise ValueError(msg)
    assert store._conn.closed


def test_context_manager_usable_for_reads_and_writes(store_cls: type[BasePostgresStore]) -> None:
    with _connect(store_cls) as store:
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


def test_context_manager_reopens_closed_store(store_cls: type[BasePostgresStore]) -> None:
    """Reopening a closed store via ``__enter__`` must reconnect rather
    than reusing the closed connection."""
    store = _connect(store_cls)
    store.close()
    assert store.closed

    new_conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=new_conn), store:
        assert not store.closed
        assert store._conn is new_conn
        store.set("1", {"text": "hello"})
        assert store.count() == 1


async def test_async_context_manager_reopens_closed_store(
    store_cls: type[BasePostgresStore],
) -> None:
    """Reopening a closed store via ``__aenter__`` must reconnect rather
    than reusing the closed connection."""
    store = _connect(store_cls)
    await store.aclose()
    assert store.closed

    new_conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=new_conn):
        async with store:
            assert not store.closed
            assert store._conn is new_conn
            store.set("1", {"text": "hello"})
            assert store.count() == 1


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


def test_init_schema_with_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match=r"reserved key column name"):
        TypedPostgresStore("postgresql://x", value_schema={"_KEY_": "TEXT"})


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


##############################################################
#     PostgresStore-specific SQL-building behavior             #
##############################################################

# The tests above exercise the store through the FakeConnection, which
# validates end-to-end behavior but not the exact SQL text generated. The
# tests below inspect the SQL fragments each internal method builds
# directly, as a regression guard on their shape.


@pytest.fixture
def plain_store() -> PostgresStore:
    with patch(f"{MODULE}.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        store = PostgresStore("postgresql://x", table="store")
    store._conn.reset_mock()
    return store


def test_plain_create_table_sql(plain_store: PostgresStore) -> None:
    stmt = plain_store._create_table_sql().as_string(None)
    assert "store" in stmt
    assert "value JSONB NOT NULL" in stmt


def test_plain_row_to_value_is_passthrough(plain_store: PostgresStore) -> None:
    value = {"title": "Intro to Python", "author": "Alice"}
    assert plain_store._row_to_value(("1", value)) == value


def test_plain_build_filter_condition(plain_store: PostgresStore) -> None:
    cond = plain_store._build_filter_condition("author").as_string(None)
    assert "value->>" in cond
    assert "'author'" in cond


def test_plain_build_filter_condition_invalid_field_name(plain_store: PostgresStore) -> None:
    with pytest.raises(ValueError, match="Invalid filter field name"):
        plain_store._build_filter_condition("bad; DROP TABLE")


##############################################################
#     TypedPostgresStore-specific SQL-building behavior        #
##############################################################


@pytest.fixture
def typed_sql_store() -> TypedPostgresStore:
    with patch(f"{MODULE}.psycopg.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        store = TypedPostgresStore(
            "postgresql://x", table="store", value_schema={"author": "TEXT", "year": "INTEGER"}
        )
    store._conn.reset_mock()
    return store


def test_typed_create_table_sql(typed_sql_store: TypedPostgresStore) -> None:
    stmt = typed_sql_store._create_table_sql().as_string(None)
    assert "store" in stmt
    assert "author" in stmt
    assert "TEXT" in stmt
    assert "year" in stmt
    assert "INTEGER" in stmt
    assert "extra" in stmt


def test_typed_build_filter_condition_schema_field(typed_sql_store: TypedPostgresStore) -> None:
    cond = typed_sql_store._build_filter_condition("author").as_string(None)
    assert "author" in cond
    assert "extra->>" not in cond


def test_typed_build_filter_condition_extra_field(typed_sql_store: TypedPostgresStore) -> None:
    cond = typed_sql_store._build_filter_condition("publisher").as_string(None)
    assert "extra->>" in cond
    assert "'publisher'" in cond


def test_typed_build_filter_condition_extra_field_invalid_name(
    typed_sql_store: TypedPostgresStore,
) -> None:
    with pytest.raises(ValueError, match="Invalid filter field name"):
        typed_sql_store._build_filter_condition("bad; DROP TABLE")


def test_typed_build_insert(typed_sql_store: TypedPostgresStore) -> None:
    stmt = typed_sql_store._build_insert().as_string(None)
    assert "INSERT INTO" in stmt
    assert "ON CONFLICT" in stmt
    assert "_KEY_" in stmt
    assert "author" in stmt
    assert "year" in stmt
    assert "extra" in stmt
    assert "DO UPDATE SET" in stmt


def test_typed_round_trip_all_known_fields(typed_sql_store: TypedPostgresStore) -> None:
    value = {"author": "Alice", "year": 2022}
    row = typed_sql_store._value_to_row("1", value)
    assert row == ("1", "Alice", 2022, None)
    assert typed_sql_store._row_to_value(row) == value


def test_typed_round_trip_split_schema_and_extra(typed_sql_store: TypedPostgresStore) -> None:
    value = {"author": "Alice", "title": "Intro to Python"}
    row = typed_sql_store._value_to_row("1", value)
    # The overflow column is wrapped in Jsonb for outbound adaptation; a
    # real SELECT decodes it back to a plain dict, which is what
    # _row_to_value expects (it is never fed a Jsonb-wrapped row directly).
    assert row[:3] == ("1", "Alice", None)
    assert isinstance(row[3], Jsonb)
    assert row[3].obj == {"title": "Intro to Python"}
    decoded_row = (*row[:3], row[3].obj)
    assert typed_sql_store._row_to_value(decoded_row) == value


def test_typed_round_trip_empty_value(typed_sql_store: TypedPostgresStore) -> None:
    value: dict[str, object] = {}
    row = typed_sql_store._value_to_row("1", value)
    assert row == ("1", None, None, None)
    assert typed_sql_store._row_to_value(row) == {}


# ---------------------------------------------------------------------------
# Async methods
#
# BasePostgresStore holds both a sync psycopg.Connection (eager) and a
# lazily-opened psycopg.AsyncConnection; the fixtures above pre-populate the
# latter with an _AsyncConnAdapter wrapping the same FakeConnection (see
# _connect()), so store.a*() methods below observe the exact same in-memory
# table state as their sync counterparts tested above.
# ---------------------------------------------------------------------------


# --- aget / aset ---


async def test_postgres_store_aget_aset_round_trip(store: BasePostgresStore) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}
    assert await store.aget("missing") is None


# --- aset_many / afilter ---


async def test_postgres_store_aset_many_and_afilter(store: BasePostgresStore) -> None:
    await store.aset_many(
        {
            "1": {"author": "Alice", "category": "Programming"},
            "2": {"author": "Bob", "category": "History"},
        }
    )
    assert len(await store.afilter(author="Alice")) == 1
    assert len(await store.afilter(category="History")) == 1


# --- aset (conflict variants) ---


async def test_postgres_store_aset_on_conflict_raise(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.aset("1", {"text": "updated"}, on_conflict="raise")
    assert await store.aget("1") == {"text": "original"}


async def test_postgres_store_aset_on_conflict_merge(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original", "author": "Alice"})
    await store.aset("1", {"text": "updated"}, on_conflict="merge")
    assert await store.aget("1") == {"text": "updated", "author": "Alice"}


async def test_postgres_store_aset_on_conflict_invalid_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.aset("1", {"text": "hello"}, on_conflict="bogus")


async def test_postgres_store_aset_many_on_conflict_invalid_raises(
    store: BasePostgresStore,
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.aset_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- adelete / acount ---


async def test_postgres_store_adelete_acount(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acount() == 1


# --- adelete_many ---


async def test_postgres_store_adelete_many(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    await store.adelete_many(["1", "3"])
    assert await store.acount() == 1
    assert await store.aget("2") is not None


# --- aclear ---


async def test_postgres_store_aclear(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.aclear()
    assert await store.acount() == 0


# --- acontains ---


async def test_postgres_store_acontains(store: BasePostgresStore) -> None:
    await store.aset("1", {"a": 1})
    assert await store.acontains("1")
    assert not await store.acontains("99")


# --- acontains_many ---


async def test_postgres_store_acontains_many(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


# --- akeys / aiter_batches ---


async def test_postgres_store_akeys_aiter_batches(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3


async def test_postgres_store_aiter_batches_zero_batch_size_raises(
    store: BasePostgresStore,
) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.aiter_batches(batch_size=0):
            pass


# --- close ---


async def test_postgres_store_aclose_without_ever_connecting_is_safe(
    store_cls: type[BasePostgresStore],
) -> None:
    """A store whose async connection was never used has ``_aconn is
    None`` (the sync connection is still opened eagerly, per the class
    docstring); ``aclose()`` must tolerate that."""
    with patch(f"{MODULE}.psycopg.connect", return_value=FakeConnection()):
        store = store_cls("postgresql://x", table="store")
    assert store._aconn is None
    await store.aclose()
    assert store.closed


async def test_postgres_store_aclose_is_idempotent(store: BasePostgresStore) -> None:
    await store.aget("1")  # forces the lazy async connection to be used
    await store.aclose()
    await store.aclose()
    assert store.closed


async def test_postgres_store_aclose_returns_none(store: BasePostgresStore) -> None:
    assert await store.aclose() is None


# --- context manager ---


async def test_postgres_store_async_context_manager(store_cls: type[BasePostgresStore]) -> None:
    store = _connect(store_cls)
    async with store as astore:
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
    assert store._conn.closed


# ---------------------------------------------------------------------------
# Additional coverage: async branches not exercised above.
# ---------------------------------------------------------------------------


# --- constructor ---


async def test_ensure_aconn_opens_connection_lazily(
    store_cls: type[BasePostgresStore],
) -> None:
    """The lazy async connection is opened on first async use; the
    ``store`` fixture pre-populates it via ``_connect()``, so exercise
    the real opening path (lines 100-103 of ``_ensure_aconn``) directly
    here."""
    conn = FakeConnection()
    aconn_fake = FakeConnection()
    aconn = _AsyncConnAdapter(aconn_fake)
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        store = store_cls("postgresql://x", table="store")
    aconn_fake.store = store
    assert store._aconn is None
    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", new=AsyncMock(return_value=aconn)):
        await store.aget("missing")
    assert store._aconn is aconn


# --- aget_many ---


async def test_postgres_store_aget_many_empty(store: BasePostgresStore) -> None:
    assert await store.aget_many([]) == []


async def test_postgres_store_aget_many(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.aget_many(["1", "missing", "2"])
    assert result[0] == {"a": 1}
    assert result[1] is None
    assert result[2] == {"a": 2}


# --- aset_many ---


async def test_postgres_store_aset_many_empty_items(store: BasePostgresStore) -> None:
    assert await store.aset_many({}) is None


# --- aset (conflict variants) ---


async def test_postgres_store_aset_on_conflict_skip(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.aget("1") == {"text": "original"}
    assert await store.aget("2") == {"text": "new"}


# --- aset_many (conflict variants) ---


async def test_postgres_store_aset_many_merge_with_new_key(store: BasePostgresStore) -> None:
    """Exercises the non-conflicting-key branch of ``aset_many`` when
    ``on_conflict != 'overwrite'`` (a key not already present is written
    directly, without going through ``aget``)."""
    await store.aset("1", {"text": "original"})
    await store.aset_many(
        {"1": {"text": "updated"}, "2": {"text": "brand new"}}, on_conflict="merge"
    )
    assert await store.aget("1") == {"text": "updated"}
    assert await store.aget("2") == {"text": "brand new"}


async def test_postgres_store_aset_many_skip_all_writes_nothing(
    store: BasePostgresStore,
) -> None:
    """When every key conflicts and ``on_conflict='skip'``, ``to_write``
    ends up empty, exercising the ``if items:`` false branch of
    ``_aset_many``."""
    await store.aset("1", {"text": "original"})
    await store.aset_many({"1": {"text": "updated"}}, on_conflict="skip")
    assert await store.aget("1") == {"text": "original"}


# --- afilter ---


async def test_postgres_store_afilter_no_filters(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.afilter()
    assert len(result) == 2


async def test_postgres_store_afilter_multiple_fields(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.afilter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_postgres_store_afilter_rejects_malicious_field_name(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        await store.afilter(**{"bad; DROP TABLE store;--": "x"})


# --- adelete_many ---


async def test_postgres_store_adelete_many_empty(store: BasePostgresStore) -> None:
    assert await store.adelete_many([]) is None


# --- acontains_many ---


async def test_postgres_store_acontains_many_empty(store: BasePostgresStore) -> None:
    assert await store.acontains_many([]) == ([], [])


# --- aiter_batches ---


async def test_postgres_store_aiter_batches_exact_multiple(
    store: BasePostgresStore,
) -> None:
    """When the item count is an exact multiple of ``batch_size``, the
    trailing ``if batch:`` check at the end of ``aiter_batches`` is
    false, exercising that branch."""
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 2


# --- avalues ---


async def test_postgres_store_avalues(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = [v async for v in store.avalues(batch_size=2)]
    assert sorted(v["a"] for v in values) == [1, 2, 3]


# --- aset_batches ---


async def test_postgres_store_aset_batches(store: BasePostgresStore) -> None:
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert await store.acount() == 2


# ---------------------------------------------------------------------------
# async + typed schema
# ---------------------------------------------------------------------------


# --- aget ---


async def test_typed_postgres_store_aget_round_trips_typed_schema_fields(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    assert await typed_store.aget("1") == items["1"]


# --- aset ---


async def test_typed_postgres_store_aset_on_conflict_merge_with_typed_schema(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice", "year": 2022})
    await typed_store.aset("1", {"category": "Programming"}, on_conflict="merge")
    assert await typed_store.aget("1") == {
        "author": "Alice",
        "year": 2022,
        "category": "Programming",
    }


# --- afilter ---


async def test_typed_postgres_store_afilter_single_typed_field(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(author="Alice")
    assert {item["title"] for item in result} == {"Intro to Python", "Advanced Python"}


async def test_typed_postgres_store_afilter_integer_typed_column(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(year=2022)
    assert {item["title"] for item in result} == {"Intro to Python"}


# --- aiter_batches ---


async def test_typed_postgres_store_aiter_batches_with_typed_schema(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in typed_store.aiter_batches(batch_size=2):
        result.update(batch)
    assert result == items


# --- avalues ---


async def test_typed_postgres_store_avalues_with_typed_schema(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    values = [v async for v in typed_store.avalues(batch_size=2)]
    assert sorted(v["title"] for v in values) == sorted(item["title"] for item in items.values())


# --- aset (conflict variants) ---


async def test_typed_postgres_store_aset_on_conflict_raise_with_typed_schema(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    with pytest.raises(KeyError, match=r"1"):
        await typed_store.aset("1", {"author": "Bob"}, on_conflict="raise")
    assert await typed_store.aget("1") == {"author": "Alice"}


async def test_typed_postgres_store_aset_on_conflict_skip_with_typed_schema(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    await typed_store.aset("1", {"author": "Bob"}, on_conflict="skip")
    assert await typed_store.aget("1") == {"author": "Alice"}


async def test_typed_postgres_store_aset_on_conflict_overwrite_with_typed_schema(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    await typed_store.aset("1", {"author": "Bob"}, on_conflict="overwrite")
    assert await typed_store.aget("1") == {"author": "Bob"}


# --- afilter (extra fields) ---


async def test_typed_postgres_store_afilter_multiple_typed_fields(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(author="Alice", category="Programming")
    assert {item["title"] for item in result} == {"Intro to Python", "Advanced Python"}


async def test_typed_postgres_store_afilter_extra_field(typed_store: TypedPostgresStore) -> None:
    await typed_store.aset_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Packt"},
        }
    )
    result = await typed_store.afilter(publisher="O'Reilly")
    assert result == [{"author": "Alice", "publisher": "O'Reilly"}]


async def test_typed_postgres_store_afilter_mixed_schema_and_extra_fields(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Packt"},
        }
    )
    result = await typed_store.afilter(author="Alice", publisher="O'Reilly")
    assert result == [{"author": "Alice", "publisher": "O'Reilly"}]


async def test_typed_postgres_store_afilter_integer_typed_column_no_match(
    typed_store: TypedPostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    assert await typed_store.afilter(year=9999) == []


# ---------------------------------------------------------------------------
# Additional async parity coverage (mirrors sync tests above one-for-one).
# ---------------------------------------------------------------------------


# --- constructor ---


async def test_two_stores_different_tables_are_isolated_async(
    store_cls: type[BasePostgresStore],
) -> None:
    conn = FakeConnection()
    with patch(f"{MODULE}.psycopg.connect", return_value=conn):
        store_a = store_cls("postgresql://x", table="store_a")
        store_b = store_cls("postgresql://x", table="store_b")
    conn.store = store_a
    store_a._aconn = _AsyncConnAdapter(conn)
    store_b._aconn = _AsyncConnAdapter(conn)
    await store_a.aset("1", {"text": "a"})
    assert await store_b.aget("1") is None
    assert await store_b.acount() == 0


# --- aset ---


async def test_aset_default_overwrites_existing(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset("1", {"text": "updated"})
    assert await store.acount() == 1
    assert await store.aget("1") == {"text": "updated"}


async def test_aset_on_conflict_overwrite(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.aget("1") == {"text": "updated"}


async def test_aset_on_conflict_new_key_is_unaffected(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "hello"}, on_conflict="raise")
    assert await store.aget("1") == {"text": "hello"}


# --- aset_many ---


async def test_aset_many_increases_count(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert await store.acount() == len(items)


async def test_aset_many_empty_is_no_op(store: BasePostgresStore) -> None:
    await store.aset_many({})
    assert await store.acount() == 0


async def test_aset_many_default_overwrites_existing(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"text": "original"}})
    await store.aset_many({"1": {"text": "updated"}})
    assert await store.acount() == 1
    assert await store.aget("1") == {"text": "updated"}


async def test_aset_many_on_conflict_raise(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.aset_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.aget("1") == {"text": "original"}
    assert await store.aget("3") is None


async def test_aset_many_on_conflict_overwrite(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"text": "original"}})
    await store.aset_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.aget("1") == {"text": "updated"}
    assert await store.aget("2") == {"text": "new"}


async def test_aset_many_on_conflict_merge(store: BasePostgresStore) -> None:
    await store.aset_many({"1": {"text": "original", "author": "Alice"}})
    await store.aset_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.aget("1") == {"text": "updated", "author": "Alice"}


# --- aset_batches ---


async def test_aset_batches_empty_is_no_op(store: BasePostgresStore) -> None:
    await store.aset_batches([])
    assert await store.acount() == 0


async def test_aset_batches_writes_all_pairs(store: BasePostgresStore) -> None:
    await store.aset_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.acount() == 3
    assert await store.aget("2") == {"v": 2}


async def test_aset_batches_consumes_a_generator(store: BasePostgresStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    await store.aset_batches(gen(), batch_size=2)
    assert await store.acount() == 5


async def test_aset_batches_on_conflict_skip(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.aget("1") == {"text": "original"}
    assert await store.aget("2") == {"text": "new"}


# --- acount ---


async def test_acount_empty_store(store: BasePostgresStore) -> None:
    assert await store.acount() == 0


async def test_acount_after_set_many(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert await store.acount() == len(items)


# --- aget_many ---


async def test_aget_many_returns_correct_length(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert len(await store.aget_many(["1", "2", "99"])) == 3


async def test_aget_many_preserves_order(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.aget_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


# --- afilter ---


async def test_afilter_single_field(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.afilter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_afilter_no_match_returns_empty(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert await store.afilter(author="Charlie") == []


async def test_afilter_preserves_full_value(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.afilter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


async def test_afilter_empty_store_returns_empty(store: BasePostgresStore) -> None:
    assert await store.afilter(author="Alice") == []


async def test_afilter_integer_field_value(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.afilter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


async def test_afilter_integer_value_no_match_returns_empty(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert await store.afilter(year=9999) == []


# --- adelete ---


async def test_adelete_removes_value(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    await store.adelete("1")
    assert await store.acount() == len(items) - 1
    assert await store.aget("1") is None


async def test_adelete_nonexistent_is_silent(store: BasePostgresStore) -> None:
    await store.adelete("nonexistent")


# --- adelete_many ---


async def test_adelete_many_preserves_other_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    await store.adelete_many(["1", "3"])
    assert await store.aget("2") is not None
    assert await store.aget("4") is not None


async def test_adelete_many_empty_list_is_no_op(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    await store.adelete_many([])
    assert await store.acount() == len(items)


async def test_adelete_many_nonexistent_keys_are_silent(store: BasePostgresStore) -> None:
    await store.adelete_many(["99", "100"])


async def test_adelete_many_single_key(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    await store.adelete_many(["2"])
    assert await store.acount() == len(items) - 1
    assert await store.aget("2") is None


# --- aclear ---


async def test_aclear_removes_all_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    await store.aclear()
    assert await store.acount() == 0
    assert [key async for key in store.akeys()] == []


async def test_aclear_empty_store_is_no_op(store: BasePostgresStore) -> None:
    await store.aclear()
    assert await store.acount() == 0


async def test_aclear_returns_none(store: BasePostgresStore) -> None:
    assert await store.aclear() is None


async def test_aclear_then_set_works(store: BasePostgresStore) -> None:
    await store.aset("1", {"text": "hello"})
    await store.aclear()
    await store.aset("2", {"text": "world"})
    assert await store.acount() == 1
    assert await store.aget("2") == {"text": "world"}


# --- acontains ---


async def test_acontains_true_when_key_present(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    assert await store.acontains("1")


async def test_acontains_false_when_store_empty(store: BasePostgresStore) -> None:
    assert not await store.acontains("1")


# --- acontains_many ---


async def test_acontains_many_all_found(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    found, missing = await store.acontains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


async def test_acontains_many_all_missing(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    found, missing = await store.acontains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


async def test_acontains_many_empty_store_returns_all_missing(store: BasePostgresStore) -> None:
    found, missing = await store.acontains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


async def test_acontains_many_returns_tuple_of_two_lists(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.acontains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- akeys ---


async def test_akeys_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert [key async for key in store.akeys()] == []


# --- avalues ---


async def test_avalues_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert [v async for v in store.avalues()] == []


async def test_avalues_returns_all_values(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = [v async for v in store.avalues()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- aiter_batches ---


async def test_aiter_batches_empty_store_yields_nothing(store: BasePostgresStore) -> None:
    assert [batch async for batch in store.aiter_batches()] == []


async def test_aiter_batches_default_batch_size(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_aiter_batches_yields_correct_batch_sizes(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sorted(len(b) for b in batches) == [2, 2]


async def test_aiter_batches_last_batch_may_be_smaller(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches(batch_size=3)]
    assert sorted(len(b) for b in batches) == [1, 3]


async def test_aiter_batches_batch_size_larger_than_store(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches(batch_size=100)]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_aiter_batches_batch_size_one(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches(batch_size=1)]
    assert sorted(len(b) for b in batches) == [1, 1, 1, 1]


async def test_aiter_batches_returns_all_key_value_pairs(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.aiter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_aiter_batches_batches_are_dicts(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert all(isinstance(batch, dict) for batch in batches)


async def test_aiter_batches_negative_batch_size_raises(store: BasePostgresStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.aiter_batches(batch_size=-1):
            pass


async def test_aiter_batches_does_not_mutate_store(
    store: BasePostgresStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    async for _ in store.aiter_batches(batch_size=2):
        pass
    assert await store.acount() == len(items)


# --- close/aclose ---


async def test_aclose_closes_underlying_connection(store: BasePostgresStore) -> None:
    await store.aget("1")  # forces the lazy async connection to be used
    await store.aclose()
    assert store._conn.closed


async def test_closed_false_before_close_async(store: BasePostgresStore) -> None:
    assert not store.closed


async def test_closed_true_after_aclose(store: BasePostgresStore) -> None:
    await store.aclose()
    assert store.closed


# --- context manager ---


async def test_async_context_manager_closes_on_normal_exit(
    store_cls: type[BasePostgresStore],
) -> None:
    async with _connect(store_cls) as store:
        await store.aset("1", {"text": "hello"})
        assert await store.acount() == 1
    assert store._conn.closed


async def test_async_context_manager_closes_on_exception(
    store_cls: type[BasePostgresStore],
) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"):
        async with _connect(store_cls) as store:
            raise ValueError(msg)
    assert store._conn.closed


# ---------------------------------------------------------------------------
# async + typed schema parity
# ---------------------------------------------------------------------------


async def test_typed_postgres_store_ainit_no_schema_stores_everything_in_extra(
    typed_store_no_schema: TypedPostgresStore,
) -> None:
    await typed_store_no_schema.aset("1", {"title": "Intro to Python", "author": "Alice"})
    assert await typed_store_no_schema.aget("1") == {
        "title": "Intro to Python",
        "author": "Alice",
    }


async def test_typed_postgres_store_avalue_field_named_key_does_not_collide_with_primary_key(
    typed_store_no_schema: TypedPostgresStore,
) -> None:
    await typed_store_no_schema.aset("1", {"key": "not-the-primary-key"})
    assert await typed_store_no_schema.aget("1") == {"key": "not-the-primary-key"}
    assert await typed_store_no_schema.afilter(key="not-the-primary-key") == [
        {"key": "not-the-primary-key"}
    ]


async def test_typed_postgres_store_aget_round_trips_extra_field(
    typed_store: TypedPostgresStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice", "publisher": "O'Reilly"})
    assert (await typed_store.aget("1"))["publisher"] == "O'Reilly"
