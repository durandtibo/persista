r"""Tests of the SQL stores against their real databases: the data seen
by the sync and async methods, iteration, and the databases that a store
must not touch."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from persista.store import DuckDBStore, SQLiteStore
from persista.testing.fixtures import duckdb_available
from persista.utils.imports import is_duckdb_available

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from persista.store import BaseStore

if is_duckdb_available():
    import duckdb

STORES = [
    pytest.param(SQLiteStore, id="sqlite"),
    pytest.param(DuckDBStore, id="duckdb", marks=duckdb_available),
]


@pytest.fixture(params=["memory", "file"])
def database(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    r"""Return an in-memory database, or the path of a database file."""
    return ":memory:" if request.param == "memory" else str(tmp_path / "data.db")


@pytest.fixture(params=STORES)
def store(request: pytest.FixtureRequest, database: str) -> Generator[BaseStore, None, None]:
    with request.param(database) as store:
        yield store


def create_sqlite_table(path: Path, columns: str) -> None:
    r"""Create the ``store`` table of a SQLite database."""
    connection = sqlite3.connect(path)
    connection.execute(f"CREATE TABLE store ({columns})")
    connection.close()


def create_duckdb_table(path: Path, columns: str) -> None:
    r"""Create the ``store`` table of a DuckDB database."""
    with duckdb.connect(path) as connection:
        connection.execute(f"CREATE TABLE store ({columns})")


################################
#     Tests for SQL stores     #
################################


async def test_aget_reads_the_value_of_set(store: BaseStore) -> None:
    r"""Test that the async methods see the data of the sync methods."""
    store.set("a", {"v": 1})
    assert await store.aget("a") == {"v": 1}


async def test_get_reads_the_value_of_aset(store: BaseStore) -> None:
    r"""Test that the sync methods see the data of the async methods."""
    await store.aset("a", {"v": 1})
    assert store.get("a") == {"v": 1}


@pytest.mark.parametrize("batch_size", [1, 3])
def test_iteration_with_deletion_of_yielded_keys(store: BaseStore, batch_size: int) -> None:
    r"""Test that deleting the yielded keys does not skip other keys."""
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    for batch in store.iter_batches(batch_size=batch_size):
        visited.extend(batch)
        store.delete_many(list(batch))
    assert sorted(visited) == [str(i) for i in range(10)]


async def test_async_iteration_with_deletion_of_yielded_keys(store: BaseStore) -> None:
    r"""Test that deleting the yielded keys during an async iteration
    does not skip other keys."""
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    async for batch in store.aiter_batches(batch_size=3):
        visited.extend(batch)
        await store.adelete_many(list(batch))
    assert sorted(visited) == [str(i) for i in range(10)]


@pytest.mark.parametrize(
    ("cls", "create_table", "columns"),
    [
        pytest.param(
            SQLiteStore,
            create_sqlite_table,
            "key TEXT PRIMARY KEY, title TEXT",
            id="sqlite",
        ),
        pytest.param(
            SQLiteStore,
            create_sqlite_table,
            "id TEXT PRIMARY KEY, extra JSON",
            id="sqlite_record",
        ),
        pytest.param(
            DuckDBStore,
            create_duckdb_table,
            "key VARCHAR PRIMARY KEY, title VARCHAR",
            id="duckdb",
            marks=duckdb_available,
        ),
        pytest.param(
            DuckDBStore,
            create_duckdb_table,
            "id VARCHAR PRIMARY KEY, extra JSON",
            id="duckdb_record",
            marks=duckdb_available,
        ),
    ],
)
def test_set_does_not_write_into_a_typed_table(
    tmp_path: Path,
    cls: type[BaseStore],
    create_table: Callable[[Path, str], None],
    columns: str,
) -> None:
    r"""Test that a table of a typed store of an earlier version is not
    written."""
    path = tmp_path / "data.db"
    create_table(path, columns)
    with pytest.raises(ValueError, match=r"does not match the codec"), cls(path) as store:
        store.set("a", {"title": "b"})
