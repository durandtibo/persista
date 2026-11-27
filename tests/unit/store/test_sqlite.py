from __future__ import annotations

import asyncio
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import PickleCodec, SQLiteStore, sqlite as sqlite_module
from persista.store.sqlite import _is_memory_database, _is_shared_cache, _read_only_uri

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

SHARED_MEMORY = "file::memory:?cache=shared"


@pytest.fixture
def store() -> Generator[SQLiteStore, None, None]:
    with SQLiteStore() as store:
        yield store


@pytest.fixture
def path(tmp_path: Path) -> Path:
    r"""Return the path of a database that contains one value."""
    path = tmp_path / "data.sqlite"
    with SQLiteStore(path) as store:
        store.set("1", {"a": 1})
    return path


def create_table(path: Path, columns: str) -> None:
    r"""Create the ``store`` table of a database with some columns."""
    connection = sqlite3.connect(path)
    connection.execute(f"CREATE TABLE store ({columns})")
    connection.close()


#################################
#     Tests for SQLiteStore     #
#################################


# --- constructor ---


def test_init_defaults_to_in_memory() -> None:
    with SQLiteStore() as store:
        assert store._database == ":memory:"


def test_init_options_are_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        SQLiteStore(":memory:", PickleCodec())


def test_init_accepts_sqlite_connect_kwargs() -> None:
    with SQLiteStore(timeout=1.0) as store:
        assert store.count() == 0


@pytest.mark.parametrize("name", ["isolation_level", "autocommit"])
def test_init_rejects_transaction_kwargs(name: str) -> None:
    with pytest.raises(ValueError, match=r"manages its transactions"):
        SQLiteStore(**{name: None})


def test_init_does_not_create_directories(tmp_path: Path) -> None:
    SQLiteStore(tmp_path / "nested" / "data.sqlite")
    assert not (tmp_path / "nested").exists()


def test_init_makes_path_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert SQLiteStore("data.sqlite")._database == (tmp_path / "data.sqlite").resolve()


def test_init_keeps_sqlite_uri() -> None:
    assert SQLiteStore(SHARED_MEMORY, uri=True)._database == SHARED_MEMORY


@pytest.mark.parametrize(
    "database", [":memory:", SHARED_MEMORY, "file:name?mode=memory", "file::memory:"]
)
def test_init_read_only_in_memory_database(database: str) -> None:
    with pytest.raises(ValueError, match=r"read_only needs a database file"):
        SQLiteStore(database, read_only=True, uri=True)


def test_init_shared_cache_uses_shared_lock() -> None:
    store = SQLiteStore(SHARED_MEMORY, uri=True)
    assert store._lock is store._guard is sqlite_module._SHARED_CACHE_LOCK


def test_init_read_only_shared_cache_uses_shared_lock(tmp_path: Path) -> None:
    database = f"{(tmp_path / 'a.db').as_uri()}?cache=shared"
    assert SQLiteStore(database, read_only=True)._lock is sqlite_module._SHARED_CACHE_LOCK


@pytest.mark.parametrize(
    "factory",
    [
        pytest.param(SQLiteStore, id="memory"),
        pytest.param(lambda: SQLiteStore("file::memory:", uri=True), id="private_uri"),
    ],
)
def test_init_private_database_uses_own_lock(factory: Any) -> None:
    assert factory()._lock is not sqlite_module._SHARED_CACHE_LOCK


# --- open / close ---


def test__open() -> None:
    store = SQLiteStore()
    store._open()
    assert store._table_columns() == [("key", "TEXT", True), ("value", "JSON", False)]
    store._close()


def test_open_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dirs" / "data.sqlite"
    with SQLiteStore(path):
        assert path.is_file()


def test_open_uses_autocommit(store: SQLiteStore) -> None:
    assert store.connection.isolation_level is None


def test_reopen_in_memory_store_is_empty(store: SQLiteStore) -> None:
    store.set("1", {})
    store.close()
    store.open()
    assert store.count() == 0


def test_reopen_file_store_keeps_values(path: Path) -> None:
    with SQLiteStore(path) as store:
        assert store.get("1") == {"a": 1}


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param("key TEXT PRIMARY KEY, title TEXT, extra JSON", id="typed_table"),
        pytest.param("key TEXT PRIMARY KEY, value TEXT, extra JSON", id="typed_value_field"),
        pytest.param("id TEXT PRIMARY KEY, extra JSON", id="typed_record_table"),
        pytest.param("key TEXT PRIMARY KEY, value BLOB NOT NULL", id="pickle_table"),
        pytest.param("key TEXT, value JSON", id="no_primary_key"),
    ],
)
def test_open_table_with_other_layout(tmp_path: Path, columns: str) -> None:
    path = tmp_path / "data.sqlite"
    create_table(path, columns)
    store = SQLiteStore(path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert store.closed


def test_open_failure_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    create_table(path, "x TEXT")
    store = SQLiteStore(path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert store._conn is None


async def test_aopen_table_with_other_layout(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    create_table(path, "x TEXT")
    store = SQLiteStore(path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        await store.aopen()
    assert store.closed


def test_set_does_not_write_into_typed_table(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    create_table(path, "key TEXT PRIMARY KEY, title TEXT")
    with (
        pytest.raises(ValueError, match=r"does not match the codec"),
        SQLiteStore(path) as store,
    ):
        store.set("1", {"title": "a"})
    connection = sqlite3.connect(path)
    assert connection.execute("SELECT * FROM store").fetchall() == []
    connection.close()


def test_open_pickle_table_with_json_codec(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    with SQLiteStore(path, codec=PickleCodec()):
        pass
    with pytest.raises(ValueError, match=r"does not match the codec 'json'"):
        SQLiteStore(path).open()


def test_open_pickle_table_of_earlier_version(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    create_table(path, "key TEXT PRIMARY KEY, value BLOB NOT NULL")
    with SQLiteStore(path, codec=PickleCodec()) as store:
        assert store.count() == 0


def test__close(store: SQLiteStore) -> None:
    connection = store.connection
    store._close()
    with pytest.raises(sqlite3.ProgrammingError, match=r"closed database"):
        connection.execute("SELECT 1")


def test__close_without_open() -> None:
    store = SQLiteStore()
    store._close()
    assert store._conn is None


# --- read-only ---


def test_read_only_reads_existing_values(path: Path) -> None:
    with SQLiteStore(path, read_only=True) as store:
        assert store.get("1") == {"a": 1}


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.set("2", {}), id="set"),
        pytest.param(lambda s: s.set("2", {}, on_conflict="raise"), id="update"),
        pytest.param(lambda s: s.delete("1"), id="delete"),
        pytest.param(lambda s: s.clear(), id="clear"),
    ],
)
def test_read_only_rejects_writes(path: Path, write: Any) -> None:
    with (
        SQLiteStore(path, read_only=True) as store,
        pytest.raises(sqlite3.OperationalError, match=r"readonly database"),
    ):
        write(store)


def test_read_only_does_not_create_file(tmp_path: Path) -> None:
    with pytest.raises(sqlite3.OperationalError, match=r"unable to open database file"):
        SQLiteStore(tmp_path / "data.sqlite", read_only=True).open()
    assert list(tmp_path.iterdir()) == []


def test_read_only_does_not_create_directory(tmp_path: Path) -> None:
    with pytest.raises(sqlite3.OperationalError, match=r"unable to open database file"):
        SQLiteStore(tmp_path / "nested" / "data.sqlite", read_only=True).open()
    assert list(tmp_path.iterdir()) == []


def test_read_only_database_without_table(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    path.touch()
    with pytest.raises(ValueError, match=r"has no table 'store'"):
        SQLiteStore(path, read_only=True).open()


def test_read_only_path_with_uri_characters(tmp_path: Path) -> None:
    path = tmp_path / "a #%41.sqlite"
    with SQLiteStore(path) as store:
        store.set("1", {})
    with SQLiteStore(path, read_only=True) as store:
        assert store.count() == 1


@pytest.mark.parametrize("mode", ["", "?mode=rwc"])
def test_read_only_sqlite_uri_rejects_writes(path: Path, mode: str) -> None:
    with (
        SQLiteStore(f"{path.as_uri()}{mode}", uri=True, read_only=True) as store,
        pytest.raises(sqlite3.OperationalError, match=r"readonly database"),
    ):
        store.clear()


def test_read_only_sqlite_uri_does_not_create_file(tmp_path: Path) -> None:
    store = SQLiteStore(f"{(tmp_path / 'a.db').as_uri()}?mode=rwc", uri=True, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"unable to open database file"):
        store.open()
    assert list(tmp_path.iterdir()) == []


# --- URIs ---


def test_uri_of_memory_database_gives_a_private_database(store: SQLiteStore) -> None:
    store.set("1", {})
    with SQLiteStore.from_uri(store.to_uri()) as other:
        assert other.count() == 0


def test_uri_of_sqlite_uri_reconnects() -> None:
    with SQLiteStore("file:uri_test?mode=memory&cache=shared", uri=True) as store:
        store.set("1", {})
        with SQLiteStore.from_uri(store.to_uri()) as other:
            assert other.count() == 1


def test_uri_of_path_reconnects(path: Path) -> None:
    with SQLiteStore.from_uri(SQLiteStore(path).to_uri()) as store:
        assert store.get("1") == {"a": 1}


@pytest.mark.parametrize(
    ("database", "expected"),
    [(SHARED_MEMORY, {"uri": True}), (":memory:", {}), ("/data/store.db", {})],
)
def test__uri_kwargs(database: str, expected: dict[str, bool]) -> None:
    assert SQLiteStore._uri_kwargs(database) == expected


# --- connection ---


def test_connection_executes_sql(store: SQLiteStore) -> None:
    store.set("a", {})
    assert store.connection.execute("SELECT COUNT(*) FROM store").fetchone()[0] == 1


def test_connection_before_open_raises() -> None:
    with pytest.raises(RuntimeError, match=r"SQLiteStore is not open"):
        _ = SQLiteStore().connection


# --- one connection (sync and async) ---


@pytest.mark.parametrize("database", ["memory", "file"])
async def test_value_set_is_read_by_aget(database: str, tmp_path: Path) -> None:
    path = ":memory:" if database == "memory" else tmp_path / "data.sqlite"
    async with SQLiteStore(path) as store:
        store.set("1", {"a": 1})
        assert await store.aget("1") == {"a": 1}


async def test_value_aset_is_read_by_get() -> None:
    async with SQLiteStore() as store:
        await store.aset("1", {"a": 1})
        assert store.get("1") == {"a": 1}


async def test_async_methods_use_the_connection_of_the_store() -> None:
    statements: list[str] = []
    async with SQLiteStore() as store:
        store.connection.set_trace_callback(statements.append)
        await store.aget("1")
        assert statements == ["SELECT key, value FROM store WHERE key = '1'"]


def test_contended_async_writes_in_two_event_loops() -> None:
    async def write(store: SQLiteStore, field: str) -> None:
        await asyncio.gather(
            *(store.aset("1", {f"{field}{i}": i}, on_conflict="merge") for i in range(3))
        )

    with SQLiteStore() as store:
        asyncio.run(write(store, "a"))
        asyncio.run(write(store, "b"))
        assert len(store.get("1")) == 6


# --- transactions ---


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "merge"])
def test_update_locks_out_other_writers_before_reading(path: Path, on_conflict: str) -> None:
    with SQLiteStore(path) as store, SQLiteStore(path, timeout=0) as other:

        def plan(_existing: dict) -> dict:
            other.set("2", {}, on_conflict=on_conflict)
            return {}

        with pytest.raises(sqlite3.OperationalError, match=r"database is locked"):
            store._update(["2"], plan)
        assert other.count() == 1


def test_write_waits_at_most_the_timeout(path: Path) -> None:
    with SQLiteStore(path, timeout=0.01) as store, SQLiteStore(path) as other:
        other.connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match=r"database is locked"):
            store.set("2", {}, on_conflict="raise")
        other.connection.execute("ROLLBACK")
        assert store.count() == 1


def test_write_inside_open_transaction_of_the_connection_raises(store: SQLiteStore) -> None:
    store.connection.execute("BEGIN")
    with pytest.raises(sqlite3.OperationalError, match=r"within a transaction"):
        store.set_many({"1": {}, "2": {}})


def test__fetch(store: SQLiteStore) -> None:
    assert store._fetch("SELECT ?, ?", [1, "a"]) == [(1, "a")]


def test__execute_commits(path: Path) -> None:
    with SQLiteStore(path) as store:
        store._execute("DELETE FROM store WHERE key = ?", ["1"])
    with SQLiteStore(path) as store:
        assert store.count() == 0


def test__executemany(store: SQLiteStore) -> None:
    store._executemany("INSERT INTO store VALUES (?, ?)", [("1", "{}"), ("2", "{}")])
    assert store.count() == 2


def test__transaction_commits(store: SQLiteStore) -> None:
    with store._transaction():
        store._execute("INSERT INTO store VALUES ('1', '{}')")
    assert (store.count(), store.connection.in_transaction) == (1, False)


@pytest.mark.parametrize("error", [ValueError, KeyboardInterrupt])
def test__transaction_rolls_back(store: SQLiteStore, error: type[BaseException]) -> None:
    def fail() -> None:
        with store._transaction():
            store._execute("INSERT INTO store VALUES ('1', '{}')")
            msg = "stop"
            raise error(msg)

    with pytest.raises(error, match=r"stop"):
        fail()
    assert (store.count(), store.connection.in_transaction) == (0, False)


def test__transaction_already_ended(store: SQLiteStore) -> None:
    def fail() -> None:
        with store._transaction():
            store._execute("ROLLBACK")
            msg = "stop"
            raise ValueError(msg)

    with pytest.raises(ValueError, match=r"stop"):
        fail()


def test__transaction_commit_failure_rolls_back(path: Path) -> None:
    with SQLiteStore(path, timeout=0) as store:
        reader = sqlite3.connect(path, isolation_level=None)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM store").fetchall()
        # The reader keeps a shared lock, so the commit cannot happen.
        with pytest.raises(sqlite3.OperationalError, match=r"database is locked"):
            store.set_many({"2": {}, "3": {}})
        reader.close()
        assert (store.count(), store.connection.in_transaction) == (1, False)


# --- schema and filter ---


def test__table_columns(store: SQLiteStore) -> None:
    assert store._table_columns() == [("key", "TEXT", True), ("value", "JSON", False)]


def test__table_columns_no_table(store: SQLiteStore) -> None:
    store.connection.execute("DROP TABLE store")
    assert store._table_columns() == []


def test__filter_expr(store: SQLiteStore) -> None:
    assert store._filter_expr("author") == "json_extract(value, '$.author')"


def test__filter_expr_invalid_field(store: SQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        store._filter_expr("a') OR 1 --")


@pytest.mark.parametrize(
    ("value", "keys"),
    [
        pytest.param("1", ["str"], id="str"),
        pytest.param(1, ["bool", "int"], id="int_matches_true"),
        pytest.param(None, ["absent", "null"], id="none"),
    ],
)
def test_filter_items_matches_in_sql(store: SQLiteStore, value: Any, keys: list[str]) -> None:
    store.set_many(
        {"int": {"v": 1}, "str": {"v": "1"}, "bool": {"v": True}, "null": {"v": None}, "absent": {}}
    )
    assert sorted(store.filter_items(v=value)) == keys


def test_filter_list_value_raises(store: SQLiteStore) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match=r"type 'list' is not supported"):
        store.filter(v=[1])


# --- filter: expression index ---

_INDEX_SQL = "CREATE INDEX IF NOT EXISTS store_author ON store(json_extract(value, '$.author'))"


def query_plans(connection: sqlite3.Connection, queries: list[str]) -> list[str]:
    """Return the detail of the query plan of each query."""
    return [connection.execute(f"EXPLAIN QUERY PLAN {query}").fetchone()[3] for query in queries]


@pytest.mark.parametrize(
    "field_filters",
    [{"author": "Alice"}, {"author": None}, {"author": "Alice", "year": 2022}],
)
def test_filter_uses_expression_index(field_filters: dict[str, Any]) -> None:
    queries: list[str] = []
    with SQLiteStore() as store:
        store.connection.execute(_INDEX_SQL)
        store.connection.set_trace_callback(queries.append)
        store.filter(**field_filters)
        store.connection.set_trace_callback(None)
        assert query_plans(store.connection, queries) == [
            "SEARCH store USING INDEX store_author (<expr>=?)"
        ]


def test_filter_scans_the_table_without_expression_index() -> None:
    queries: list[str] = []
    with SQLiteStore() as store:
        store.connection.set_trace_callback(queries.append)
        store.filter(author="Alice")
        store.connection.set_trace_callback(None)
        assert query_plans(store.connection, queries) == ["SCAN store"]


async def test_afilter_uses_expression_index() -> None:
    queries: list[str] = []
    async with SQLiteStore() as store:
        store.connection.execute(_INDEX_SQL)
        store.connection.set_trace_callback(queries.append)
        await store.afilter(author="Alice")
        store.connection.set_trace_callback(None)
        assert query_plans(store.connection, queries) == [
            "SEARCH store USING INDEX store_author (<expr>=?)"
        ]


def test_filter_returns_the_same_values_with_expression_index(
    store: SQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    expected = store.filter(author="Alice")
    store.connection.execute(_INDEX_SQL)
    assert store.filter(author="Alice") == expected


def test_expression_index_is_kept_in_the_database_file(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    with SQLiteStore(path) as store:
        store.connection.execute(_INDEX_SQL)
    queries: list[str] = []
    with SQLiteStore(path) as store:
        store.connection.set_trace_callback(queries.append)
        store.filter(author="Alice")
        store.connection.set_trace_callback(None)
        assert query_plans(store.connection, queries) == [
            "SEARCH store USING INDEX store_author (<expr>=?)"
        ]


# --- repr ---


def test_repr(store: SQLiteStore) -> None:
    assert repr(store) == (
        "SQLiteStore(\n  (database): :memory:\n  (closed): False\n  (count): 0\n)"
    )


def test_str_closed() -> None:
    assert str(SQLiteStore()) == "SQLiteStore(\n  (database): :memory:\n  (closed): True\n)"


#########################################
#     Tests for _is_memory_database     #
#########################################


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        (":memory:", True),
        ("file::memory:", True),
        (SHARED_MEMORY, True),
        ("file:name?cache=shared&mode=memory", True),
        ("file:data.db", False),
        ("file:data.db?mode=ro", False),
        ("/data/mode=memory.db", False),
        ("data.db", False),
    ],
)
def test__is_memory_database(database: str, expected: bool) -> None:
    assert _is_memory_database(database) is expected


######################################
#     Tests for _is_shared_cache     #
######################################


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        (SHARED_MEMORY, True),
        ("file:data.db?mode=rw&cache=shared", True),
        ("file:data.db?cache=private", False),
        ("file:cache=shared", False),
        (":memory:", False),
    ],
)
def test__is_shared_cache(database: str, expected: bool) -> None:
    assert _is_shared_cache(database) is expected


####################################
#     Tests for _read_only_uri     #
####################################


def test__read_only_uri_path(tmp_path: Path) -> None:
    path = tmp_path / "a ?#%.db"
    assert _read_only_uri(path) == f"{tmp_path.as_uri()}/a%20%3F%23%25.db?mode=ro"


@pytest.mark.parametrize(
    ("database", "expected"),
    [
        ("file:data.db", "file:data.db?mode=ro"),
        ("file:data.db?mode=rwc", "file:data.db?mode=ro"),
        ("file:data.db?vfs=unix&mode=rw", "file:data.db?vfs=unix&mode=ro"),
        ("file:data.db?vfs=unix#part", "file:data.db?vfs=unix&mode=ro"),
    ],
)
def test__read_only_uri_sqlite_uri(database: str, expected: str) -> None:
    assert _read_only_uri(database) == expected
