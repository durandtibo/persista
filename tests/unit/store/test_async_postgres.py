from __future__ import annotations

import contextlib
import logging
import re
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import pytest

from persista.store import AsyncPostgresStore, AsyncTypedPostgresStore
from persista.utils.imports import is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Self

    from persista.store import AsyncBasePostgresStore


if is_psycopg_available():
    from psycopg.types.json import Jsonb

psycopg = pytest.importorskip("psycopg")

logger = logging.getLogger(__name__)

MODULE = "persista.store.async_postgres"


# ---------------------------------------------------------------------------
# Fake psycopg async connection
#
# Mirrors the FakeConnection in tests/unit/store/test_postgres.py, but with
# an async surface matching psycopg.AsyncConnection/AsyncCursor -- just
# enough of the protocol (and the handful of SQL shapes
# AsyncBasePostgresStore/AsyncPostgresStore/AsyncTypedPostgresStore actually
# generate) to exercise real store behavior end-to-end without a live
# server. Real server behavior is covered separately in
# tests/integration/store/test_async_postgres.py.
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
_COUNT_RE = re.compile(r'^SELECT COUNT\(\*\) FROM "(\w+)"$')
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

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[tuple[Any, ...]]:
        return _aiter(self._rows)

    async def execute(self, query: Any, params: Any = None) -> FakeCursor:
        self._rows = self.conn.dispatch_read(_sql_text(query), params or ())
        return self

    async def executemany(self, query: Any, seq: Any) -> None:
        text = _sql_text(query)
        for row in seq:
            self.conn.dispatch_insert(text, row)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    async def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


async def _aiter(rows: list[tuple[Any, ...]]) -> AsyncIterator[tuple[Any, ...]]:
    for row in rows:
        yield row


class FakeConnection:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, tuple[Any, ...]]] = {}
        # Wired up by `_connect()` right after the store is constructed, so
        # filter-condition evaluation can reuse the store's own
        # `_row_to_value` instead of duplicating its schema/extra logic.
        self.store: AsyncBasePostgresStore | None = None
        self.closed = False

    def cursor(self, name: str | None = None) -> FakeCursor:  # noqa: ARG002
        return FakeCursor(self)

    async def execute(self, query: Any, params: Any = None) -> None:
        self.dispatch_write(_sql_text(query), params or ())

    async def close(self) -> None:
        self.closed = True

    def transaction(self) -> contextlib.AbstractAsyncContextManager[None]:
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


async def _connect(
    store_cls: type[AsyncBasePostgresStore], table: str = "store", **kwargs: Any
) -> Any:
    """Construct a store against a fresh :class:`FakeConnection`."""
    conn = FakeConnection()

    async def _fake_connect(*_args: Any, **_kwargs: Any) -> FakeConnection:
        return conn

    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", side_effect=_fake_connect):
        store = store_cls("postgresql://x", table=table, **kwargs)
        await store._ensure_schema()
    conn.store = store
    return store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=[AsyncPostgresStore, AsyncTypedPostgresStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[AsyncBasePostgresStore]:
    return request.param


@pytest.fixture
async def store(store_cls: type[AsyncBasePostgresStore]) -> AsyncBasePostgresStore:
    return await _connect(store_cls)


@pytest.fixture
async def typed_store_no_schema() -> AsyncTypedPostgresStore:
    """Store with no schema (everything in `extra`)."""
    return await _connect(AsyncTypedPostgresStore)


@pytest.fixture
async def typed_store() -> AsyncTypedPostgresStore:
    """Store with a typed schema."""
    return await _connect(
        AsyncTypedPostgresStore,
        value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"},
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


###################################################################
#     Tests for AsyncPostgresStore/AsyncTypedPostgresStore        #
###################################################################


# --- constructor ---


async def test_invalid_table_name_raises_before_connect(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    with patch(f"{MODULE}.psycopg.AsyncConnection.connect") as mock_connect:
        with pytest.raises(ValueError, match="Invalid table name"):
            store_cls("postgresql://x", table="bad; DROP TABLE store;--")
        mock_connect.assert_not_called()


async def test_valid_table_name_calls_connect(store_cls: type[AsyncBasePostgresStore]) -> None:
    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = AsyncMock()
        store = store_cls("postgresql://x", table="mytable")
        await store._ensure_schema()
        mock_connect.assert_called_once_with("postgresql://x", autocommit=True)


async def test_init_creates_table(store: AsyncBasePostgresStore) -> None:
    assert await store.count() == 0


async def test_init_accepts_psycopg_connect_kwargs(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    store = await _connect(store_cls, connect_timeout=5)
    assert await store.count() == 0


async def test_two_stores_different_tables_are_isolated(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    conn = FakeConnection()

    async def _fake_connect(*_args: Any, **_kwargs: Any) -> FakeConnection:
        return conn

    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", side_effect=_fake_connect):
        store_a = store_cls("postgresql://x", table="store_a")
        store_b = store_cls("postgresql://x", table="store_b")
        await store_a._ensure_schema()
        await store_b._ensure_schema()
    conn.store = store_a
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
    await store.close()
    assert store._conn.closed


async def test_close_without_ever_connecting_is_safe(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    """A store that never ran a query never established a connection
    (see the class docstring), so ``close()`` must tolerate ``_conn``
    still being ``None``."""
    store = store_cls("postgresql://x", table="store")
    assert store._conn is None
    await store.close()
    assert store.closed


async def test_close_is_idempotent(store: AsyncBasePostgresStore) -> None:
    await store.close()
    await store.close()  # should not raise


async def test_close_returns_none(store: AsyncBasePostgresStore) -> None:
    assert await store.close() is None


# --- closed ---


async def test_closed_false_before_close(store: AsyncBasePostgresStore) -> None:
    assert not store.closed


async def test_closed_true_after_close(store: AsyncBasePostgresStore) -> None:
    await store.close()
    assert store.closed


# --- context manager ---


async def test_context_manager_returns_self(
    store: AsyncBasePostgresStore, store_cls: type[AsyncBasePostgresStore]
) -> None:
    assert isinstance(store, store_cls)


async def test_context_manager_closes_on_normal_exit(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    store = await _connect(store_cls)
    async with store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1
    assert store._conn.closed


async def test_context_manager_reopens_closed_store(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    """Reopening a closed store via ``__aenter__`` must reset its
    connection state so the next query reconnects and recreates the
    schema, rather than reusing the closed connection."""
    store = await _connect(store_cls)
    await store.close()
    assert store.closed

    async with store:
        assert not store.closed
        assert store._conn is None
        conn = FakeConnection()

        async def _fake_connect(*_args: Any, **_kwargs: Any) -> FakeConnection:
            return conn

        with patch(f"{MODULE}.psycopg.AsyncConnection.connect", side_effect=_fake_connect):
            assert await store.count() == 0


async def test_context_manager_closes_on_exception(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    store = await _connect(store_cls)
    msg = "boom"
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)
    assert store._conn.closed


async def test_context_manager_usable_for_reads_and_writes(
    store_cls: type[AsyncBasePostgresStore],
) -> None:
    store = await _connect(store_cls)
    async with store:
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


async def test_init_schema_with_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match=r"reserved key column name"):
        AsyncTypedPostgresStore("postgresql://x", value_schema={"_KEY_": "TEXT"})


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


##############################################################
#     AsyncPostgresStore-specific SQL-building behavior      #
##############################################################

# The tests above exercise the store through the FakeConnection, which
# validates end-to-end behavior but not the exact SQL text generated. The
# tests below inspect the SQL fragments each internal method builds
# directly, as a regression guard on their shape.


@pytest.fixture
async def plain_store() -> AsyncPostgresStore:
    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = AsyncMock()
        store = AsyncPostgresStore("postgresql://x", table="store")
        await store._ensure_schema()
    store._conn.reset_mock()
    return store


async def test_plain_create_table_sql(plain_store: AsyncPostgresStore) -> None:
    stmt = plain_store._create_table_sql().as_string(None)
    assert "store" in stmt
    assert "value JSONB NOT NULL" in stmt


async def test_plain_row_to_value_is_passthrough(plain_store: AsyncPostgresStore) -> None:
    value = {"title": "Intro to Python", "author": "Alice"}
    assert plain_store._row_to_value(("1", value)) == value


async def test_plain_build_filter_condition(plain_store: AsyncPostgresStore) -> None:
    cond = plain_store._build_filter_condition("author").as_string(None)
    assert "value->>" in cond
    assert "'author'" in cond


async def test_plain_build_filter_condition_invalid_field_name(
    plain_store: AsyncPostgresStore,
) -> None:
    with pytest.raises(ValueError, match="Invalid filter field name"):
        plain_store._build_filter_condition("bad; DROP TABLE")


##############################################################
#     AsyncTypedPostgresStore-specific SQL-building behavior #
##############################################################


@pytest.fixture
async def typed_sql_store() -> AsyncTypedPostgresStore:
    with patch(f"{MODULE}.psycopg.AsyncConnection.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = AsyncMock()
        store = AsyncTypedPostgresStore(
            "postgresql://x", table="store", value_schema={"author": "TEXT", "year": "INTEGER"}
        )
        await store._ensure_schema()
    store._conn.reset_mock()
    return store


async def test_typed_create_table_sql(typed_sql_store: AsyncTypedPostgresStore) -> None:
    stmt = typed_sql_store._create_table_sql().as_string(None)
    assert "store" in stmt
    assert "author" in stmt
    assert "TEXT" in stmt
    assert "year" in stmt
    assert "INTEGER" in stmt
    assert "extra" in stmt


async def test_typed_build_filter_condition_schema_field(
    typed_sql_store: AsyncTypedPostgresStore,
) -> None:
    cond = typed_sql_store._build_filter_condition("author").as_string(None)
    assert "author" in cond
    assert "extra->>" not in cond


async def test_typed_build_filter_condition_extra_field(
    typed_sql_store: AsyncTypedPostgresStore,
) -> None:
    cond = typed_sql_store._build_filter_condition("publisher").as_string(None)
    assert "extra->>" in cond
    assert "'publisher'" in cond


async def test_typed_build_filter_condition_extra_field_invalid_name(
    typed_sql_store: AsyncTypedPostgresStore,
) -> None:
    with pytest.raises(ValueError, match="Invalid filter field name"):
        typed_sql_store._build_filter_condition("bad; DROP TABLE")


async def test_typed_build_insert(typed_sql_store: AsyncTypedPostgresStore) -> None:
    stmt = typed_sql_store._build_insert().as_string(None)
    assert "INSERT INTO" in stmt
    assert "ON CONFLICT" in stmt
    assert "_KEY_" in stmt
    assert "author" in stmt
    assert "year" in stmt
    assert "extra" in stmt
    assert "DO UPDATE SET" in stmt


async def test_typed_round_trip_all_known_fields(typed_sql_store: AsyncTypedPostgresStore) -> None:
    value = {"author": "Alice", "year": 2022}
    row = typed_sql_store._value_to_row("1", value)
    assert row == ("1", "Alice", 2022, None)
    assert typed_sql_store._row_to_value(row) == value


async def test_typed_round_trip_split_schema_and_extra(
    typed_sql_store: AsyncTypedPostgresStore,
) -> None:
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


async def test_typed_round_trip_empty_value(typed_sql_store: AsyncTypedPostgresStore) -> None:
    value: dict[str, object] = {}
    row = typed_sql_store._value_to_row("1", value)
    assert row == ("1", None, None, None)
    assert typed_sql_store._row_to_value(row) == {}
