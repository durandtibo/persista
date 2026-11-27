from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import DuckDBStore, PickleCodec
from persista.store.duckdb import _get_database_lock

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

duckdb = pytest.importorskip("duckdb")


@pytest.fixture
def store() -> Generator[DuckDBStore, None, None]:
    with DuckDBStore() as store:
        yield store


@pytest.fixture
def path(tmp_path: Path) -> Path:
    r"""Return the path of a database that contains one value."""
    path = tmp_path / "data.duckdb"
    with DuckDBStore(path) as store:
        store.set("1", {"a": 1})
    return path


def create_table(path: Path, columns: str) -> None:
    r"""Create the ``store`` table of a database with some columns."""
    with duckdb.connect(path) as connection:
        connection.execute(f"CREATE TABLE store ({columns})")


#################################
#     Tests for DuckDBStore     #
#################################


# --- constructor ---


def test_init_defaults_to_in_memory() -> None:
    assert DuckDBStore()._database == ":memory:"


def test_init_options_are_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        DuckDBStore(":memory:", PickleCodec())


def test_init_accepts_duckdb_connect_kwargs() -> None:
    with DuckDBStore(config={"threads": 1}) as store:
        assert store.connection.execute("SELECT current_setting('threads')").fetchone() == (1,)


def test_init_does_not_create_directories(tmp_path: Path) -> None:
    DuckDBStore(tmp_path / "nested" / "data.duckdb")
    assert not (tmp_path / "nested").exists()


def test_init_makes_path_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert DuckDBStore("data.duckdb")._database == (tmp_path / "data.duckdb").resolve()


def test_init_read_only_in_memory_database() -> None:
    with pytest.raises(ValueError, match=r"read_only needs a database file"):
        DuckDBStore(read_only=True)


# --- open / close ---


def test__open() -> None:
    store = DuckDBStore()
    store._open()
    assert store._table_columns() == [("key", "VARCHAR", True), ("value", "JSON", False)]
    store._close()


def test_open_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dirs" / "data.duckdb"
    with DuckDBStore(path):
        assert path.is_file()


def test_reopen_in_memory_store_is_empty(store: DuckDBStore) -> None:
    store.set("1", {})
    store.close()
    store.open()
    assert store.count() == 0


def test_reopen_file_store_keeps_values(path: Path) -> None:
    with DuckDBStore(path) as store:
        assert store.get("1") == {"a": 1}


@pytest.mark.parametrize(
    "columns",
    [
        pytest.param("key VARCHAR PRIMARY KEY, title VARCHAR, extra JSON", id="typed_table"),
        pytest.param("key VARCHAR PRIMARY KEY, value VARCHAR, extra JSON", id="typed_value_field"),
        pytest.param("id VARCHAR PRIMARY KEY, extra JSON", id="typed_record_table"),
        pytest.param("key VARCHAR PRIMARY KEY, value BLOB NOT NULL", id="pickle_table"),
        pytest.param("key VARCHAR, value JSON", id="no_primary_key"),
    ],
)
def test_open_table_with_other_layout(tmp_path: Path, columns: str) -> None:
    path = tmp_path / "data.duckdb"
    create_table(path, columns)
    store = DuckDBStore(path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert store.closed


def test_open_failure_closes_connection(tmp_path: Path) -> None:
    path = tmp_path / "data.duckdb"
    create_table(path, "x VARCHAR")
    store = DuckDBStore(path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert store._conn is None


def test_open_not_a_database_leaves_store_closed(tmp_path: Path) -> None:
    path = tmp_path / "data.duckdb"
    path.write_text("not a database" * 1000)
    store = DuckDBStore(path)
    with pytest.raises(duckdb.Error, match=r"not a valid DuckDB database file"):
        store.open()
    assert store.closed


def test_set_does_not_write_into_typed_table(tmp_path: Path) -> None:
    path = tmp_path / "data.duckdb"
    create_table(path, "key VARCHAR PRIMARY KEY, title VARCHAR")
    with (
        pytest.raises(ValueError, match=r"does not match the codec"),
        DuckDBStore(path) as store,
    ):
        store.set("1", {"title": "a"})
    with duckdb.connect(path) as connection:
        assert connection.execute("SELECT * FROM store").fetchall() == []


def test_open_pickle_table_with_json_codec(tmp_path: Path) -> None:
    path = tmp_path / "data.duckdb"
    with DuckDBStore(path, codec=PickleCodec()):
        pass
    with pytest.raises(ValueError, match=r"does not match the codec 'json'"):
        DuckDBStore(path).open()


def test__close(store: DuckDBStore) -> None:
    connection = store.connection
    store._close()
    with pytest.raises(duckdb.ConnectionException, match=r"already closed"):
        connection.execute("SELECT 1")


def test__close_without_open() -> None:
    store = DuckDBStore()
    store._close()
    assert store._conn is None


# --- read-only ---


def test_read_only_reads_existing_values(path: Path) -> None:
    with DuckDBStore(path, read_only=True) as store:
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
        DuckDBStore(path, read_only=True) as store,
        pytest.raises(duckdb.Error, match=r"read-only"),
    ):
        write(store)


@pytest.mark.parametrize("name", ["data.duckdb", "nested/data.duckdb"])
def test_read_only_does_not_create_file_or_directory(tmp_path: Path, name: str) -> None:
    with pytest.raises(duckdb.IOException, match=r"database does not exist"):
        DuckDBStore(tmp_path / name, read_only=True).open()
    assert list(tmp_path.iterdir()) == []


def test_read_only_database_without_table(tmp_path: Path) -> None:
    path = tmp_path / "data.duckdb"
    duckdb.connect(path).close()
    with pytest.raises(ValueError, match=r"has no table 'store'"):
        DuckDBStore(path, read_only=True).open()


# --- URIs ---


@pytest.mark.parametrize(
    ("codec", "uri"),
    [(None, "duckdb:%3Amemory%3A"), (PickleCodec(), "duckdb+pickle:%3Amemory%3A")],
)
def test_to_uri(codec: PickleCodec | None, uri: str) -> None:
    assert DuckDBStore(codec=codec).to_uri() == uri


def test_from_uri_pickle_codec() -> None:
    assert isinstance(DuckDBStore.from_uri("duckdb+pickle::memory:")._codec, PickleCodec)


def test_from_uri_passes_kwargs() -> None:
    store = DuckDBStore.from_uri("duckdb::memory:", config={"threads": 1})
    assert store._kwargs == {"config": {"threads": 1}}


def test_uri_of_path_reconnects(path: Path) -> None:
    with DuckDBStore.from_uri(DuckDBStore(path).to_uri(), read_only=True) as store:
        assert store.get("1") == {"a": 1}


# --- connection ---


def test_connection_executes_sql(store: DuckDBStore) -> None:
    store.set("a", {})
    assert store.connection.execute("SELECT COUNT(*) FROM store").fetchone()[0] == 1


def test_connection_before_open_raises() -> None:
    with pytest.raises(RuntimeError, match=r"DuckDBStore is not open"):
        _ = DuckDBStore().connection


# --- primitives on DuckDB ---


@pytest.mark.parametrize("codec", [None, PickleCodec()])
def test__put_many_and_get_many(codec: PickleCodec | None) -> None:
    with DuckDBStore(codec=codec) as store:
        store.set_many({"1": {"a": 1}, "2": {"a": 2}})
        assert store.get_many(["2", "missing", "1"]) == [{"a": 2}, None, {"a": 1}]


@pytest.mark.parametrize("codec", [None, PickleCodec()])
def test__update(codec: PickleCodec | None) -> None:
    with DuckDBStore(codec=codec) as store:
        store.set("1", {"a": 1})
        store.set_many({"1": {"b": 1}, "2": {"b": 2}}, on_conflict="merge")
        assert store.get_many(["1", "2"]) == [{"a": 1, "b": 1}, {"b": 2}]


def test__delete_many(store: DuckDBStore) -> None:
    store.set_many({"1": {}, "2": {}, "3": {}})
    store.delete_many(["1", "missing", "3"])
    assert list(store.keys()) == ["2"]


def test__contains_many(store: DuckDBStore) -> None:
    store.set_many({"1": {}, "2": {}})
    assert store.contains_many(["2", "missing", "1"]) == [True, False, True]


def test__clear(store: DuckDBStore) -> None:
    store.set_many({"1": {}, "2": {}})
    store.clear()
    assert store.count() == 0


def test__iter_batches(store: DuckDBStore) -> None:
    store.set_many({"b": {}, "a": {}, "": {}})
    assert [list(batch) for batch in store._iter_batches(2)] == [["", "a"], ["b"]]


def test__iter_batches_delete_of_yielded_keys(store: DuckDBStore) -> None:
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    for batch in store.iter_batches(batch_size=3):
        visited.extend(batch)
        store.delete_many(list(batch))
    assert visited == [str(i) for i in range(10)]


def test__iter_key_batches(store: DuckDBStore) -> None:
    store.set_many({"b": {}, "a": {}, "": {}})
    assert list(store._iter_key_batches(2)) == [["", "a"], ["b"]]


def test__get_many_many_keys(store: DuckDBStore) -> None:
    store.set_many({str(i): {} for i in range(1000)})
    assert len(store._get_many([str(i) for i in range(1000)])) == 1000


# --- transactions ---


def test__fetch(store: DuckDBStore) -> None:
    assert store._fetch("SELECT ?, ?", [1, "a"]) == [(1, "a")]


def test__execute_commits(path: Path) -> None:
    with DuckDBStore(path) as store:
        store._execute("DELETE FROM store WHERE key = ?", ["1"])
    with DuckDBStore(path) as store:
        assert store.count() == 0


def test__executemany(store: DuckDBStore) -> None:
    store._executemany("INSERT INTO store VALUES (?, ?)", [("1", "{}"), ("2", "{}")])
    assert store.count() == 2


def test__transaction_commits(path: Path) -> None:
    with DuckDBStore(path) as store:
        with store._transaction():
            store._execute("DELETE FROM store")
        assert store.connection.cursor().execute("SELECT COUNT(*) FROM store").fetchone() == (0,)


@pytest.mark.parametrize("error", [ValueError, KeyboardInterrupt])
def test__transaction_rolls_back(store: DuckDBStore, error: type[BaseException]) -> None:
    def fail() -> None:
        with store._transaction():
            store._execute("INSERT INTO store VALUES ('1', '{}')")
            msg = "stop"
            raise error(msg)

    with pytest.raises(error, match=r"stop"):
        fail()
    assert store.count() == 0


def test__transaction_already_ended_keeps_first_error(store: DuckDBStore) -> None:
    def fail() -> None:
        with store._transaction():
            store.connection.rollback()
            msg = "stop"
            raise ValueError(msg)

    with pytest.raises(ValueError, match=r"stop"):
        fail()


def test_set_many_error_writes_nothing(store: DuckDBStore) -> None:
    # The value column is NOT NULL.
    with pytest.raises(duckdb.ConstraintException, match=r"NOT NULL constraint failed"):
        store._put_many({"1": "{}", "2": None})
    assert store.count() == 0


def test_write_inside_open_transaction_of_the_connection_raises(store: DuckDBStore) -> None:
    store.connection.begin()
    with pytest.raises(duckdb.TransactionException, match=r"within a transaction"):
        store.set_many({"1": {}, "2": {}})


# --- write lock ---


def test_write_lock_in_memory() -> None:
    with DuckDBStore() as first, DuckDBStore() as second:
        assert first._write_lock is not second._write_lock


def test_write_lock_same_file(path: Path) -> None:
    with DuckDBStore(path) as first, DuckDBStore(path) as second:
        assert first._write_lock is second._write_lock


def test_write_lock_other_files(tmp_path: Path) -> None:
    with DuckDBStore(tmp_path / "a") as first, DuckDBStore(tmp_path / "b") as second:
        assert first._write_lock is not second._write_lock


def test_update_holds_the_write_lock(path: Path) -> None:
    acquired: list[bool] = []
    with DuckDBStore(path) as store, ThreadPoolExecutor(1) as executor:
        lock = store._write_lock

        def plan(_existing: dict) -> dict:
            # Another thread cannot take the lock during the update.
            acquired.append(executor.submit(lock.acquire, blocking=False).result(timeout=10))
            return {}

        store._update(["1"], plan)
    assert acquired == [False]


# --- schema and filter ---


def test__table_columns(store: DuckDBStore) -> None:
    assert store._table_columns() == [("key", "VARCHAR", True), ("value", "JSON", False)]


def test__table_columns_no_table(store: DuckDBStore) -> None:
    store.connection.execute("DROP TABLE store")
    assert store._table_columns() == []


def test__table_columns_ignores_other_schema(store: DuckDBStore) -> None:
    store.connection.execute("DROP TABLE store")
    store.connection.execute("CREATE SCHEMA other")
    store.connection.execute("CREATE TABLE other.store (x INTEGER)")
    assert store._table_columns() == []


def test__filter_expr(store: DuckDBStore) -> None:
    assert store._filter_expr("author") == "json_extract_string(value, '$.author')"


def test__filter_expr_invalid_field(store: DuckDBStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid filter field name"):
        store._filter_expr("a') OR 1 --")


@pytest.mark.parametrize(
    ("value", "keys"),
    [
        pytest.param("1", ["int", "str"], id="str_matches_int"),
        pytest.param(1, ["int", "str"], id="int_matches_str"),
        pytest.param(None, ["absent", "null"], id="none"),
    ],
)
def test_filter_items_matches_in_sql(store: DuckDBStore, value: Any, keys: list[str]) -> None:
    store.set_many({"int": {"v": 1}, "str": {"v": "1"}, "null": {"v": None}, "absent": {}})
    assert sorted(store.filter_items(v=value)) == keys


async def test_afilter(store: DuckDBStore) -> None:
    store.set_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.afilter(a=2) == [{"a": 2}]


# --- repr ---


def test_repr(store: DuckDBStore) -> None:
    assert repr(store) == (
        "DuckDBStore(\n  (database): :memory:\n  (closed): False\n  (count): 0\n)"
    )


########################################
#     Tests for _get_database_lock     #
########################################


def test__get_database_lock_same_file(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.touch()
    link = tmp_path / "link"
    link.symlink_to(path)
    assert _get_database_lock(path) is _get_database_lock(link)


def test__get_database_lock_other_files(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.touch()
    second.touch()
    assert _get_database_lock(first) is not _get_database_lock(second)


def test__get_database_lock_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"data"):
        _get_database_lock(tmp_path / "data")
