r"""Benchmarks for the reads and writes of the stores that need no
server.

Run them with:

    inv test.benchmark
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from persista.store import InMemoryStore, JsonFileStore, SQLiteStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest_benchmark.fixture import BenchmarkFixture

    from persista.store import BaseStore

ITEMS: dict[str, dict[str, Any]] = {
    str(i): {"title": f"Document {i}", "year": 2000 + i % 25} for i in range(100)
}


@pytest.fixture(params=["in_memory", "sqlite", "json_file"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[BaseStore, None, None]:
    factories = {
        "in_memory": InMemoryStore,
        "sqlite": lambda: SQLiteStore(tmp_path / "data.sqlite"),
        "json_file": lambda: JsonFileStore(tmp_path / "data"),
    }
    with factories[request.param]() as store:
        store.set_many(ITEMS)
        yield store


def test_set_many_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    benchmark(store.set_many, ITEMS)


def test_get_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert benchmark(store.get, "42") == ITEMS["42"]


def test_get_many_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert len(benchmark(store.get_many, list(ITEMS))) == 100


def test_filter_benchmark(benchmark: BenchmarkFixture, store: BaseStore) -> None:
    assert len(benchmark(lambda: list(store.filter(year=2010)))) == 4
