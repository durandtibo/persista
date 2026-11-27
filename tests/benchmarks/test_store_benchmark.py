r"""Benchmarks for the reads and writes of the stores that need no
server.

Run them with:

    inv test.benchmark
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import (
    DuckDBStore,
    InMemoryStore,
    JsonFileStore,
    LmdbStore,
    SQLiteStore,
)
from persista.testing.fixtures import duckdb_available, lmdb_available

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest_benchmark.fixture import BenchmarkFixture

    from persista.store import BaseStore

ITEMS: dict[str, dict[str, Any]] = {
    str(i): {"title": f"Document {i}", "year": 2000 + i % 25} for i in range(100)
}

LARGE_VALUE: dict[str, Any] = {
    "rows": [{"id": i, "title": f"Document {i}", "score": i / 7} for i in range(1_000)]
}

NUM_ROWS = 100_000


def create_store(name: str, path: Path) -> BaseStore:
    r"""Create a store of the given backend.

    Args:
        name: The name of the backend.
        path: The directory where a persistent backend writes its data.

    Returns:
        A new store, not opened.
    """
    factories = {
        "in_memory": InMemoryStore,
        "sqlite": lambda: SQLiteStore(path / "data.sqlite"),
        "duckdb": lambda: DuckDBStore(path / "data.duckdb"),
        "lmdb": lambda: LmdbStore(path / "lmdb", map_size=2**28),
        "json_file": lambda: JsonFileStore(path / "data"),
    }
    return factories[name]()


@pytest.fixture(
    params=[
        "in_memory",
        "sqlite",
        pytest.param("duckdb", marks=duckdb_available),
        pytest.param("lmdb", marks=lmdb_available),
        "json_file",
    ]
)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[BaseStore, None, None]:
    with create_store(request.param, tmp_path) as store:
        store.set_many(ITEMS)
        yield store


@pytest.fixture(
    scope="module",
    params=[
        "in_memory",
        "sqlite",
        pytest.param("duckdb", marks=duckdb_available),
    ],
)
def large_store(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Generator[BaseStore, None, None]:
    with create_store(request.param, tmp_path_factory.mktemp(request.param)) as store:
        items = (
            (str(i), {"title": f"Document {i}", "author": f"author-{i % 1000}", "year": i % 25})
            for i in range(NUM_ROWS)
        )
        store.set_batches(items, batch_size=10_000)
        yield store


async def aget_all(store: BaseStore, keys: list[str]) -> list[dict[str, Any] | None]:
    r"""Read the keys one after the other with ``aget``.

    Args:
        store: The store to read.
        keys: The keys to read.

    Returns:
        The value of each key.
    """
    return [await store.aget(key) for key in keys]


def test_set_many_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    benchmark(store.set_many, ITEMS)


def test_get_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert benchmark(store.get, "42") == ITEMS["42"]


def test_aget_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    keys = list(ITEMS)
    with asyncio.Runner() as runner:
        assert len(benchmark(lambda: runner.run(aget_all(store, keys)))) == 100


def test_get_many_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert len(benchmark(store.get_many, list(ITEMS))) == 100


def test_filter_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert len(benchmark(lambda: list(store.filter(year=2010)))) == 4


@pytest.mark.timeout(600)
def test_filter_large_benchmark(benchmark: BenchmarkFixture, large_store: BaseStore) -> None:
    assert len(benchmark(lambda: list(large_store.filter(author="author-42")))) == 100


@pytest.mark.parametrize("name", ["in_memory", "sqlite"])
def test_get_large_value_benchmark(benchmark: BenchmarkFixture, name: str, tmp_path: Path) -> None:
    with create_store(name, tmp_path) as store:
        store.set("key", LARGE_VALUE)
        assert benchmark(store.get, "key") == LARGE_VALUE


@pytest.mark.parametrize("name", ["in_memory", "sqlite"])
def test_set_large_value_benchmark(benchmark: BenchmarkFixture, name: str, tmp_path: Path) -> None:
    with create_store(name, tmp_path) as store:
        benchmark(store.set, "key", LARGE_VALUE)
