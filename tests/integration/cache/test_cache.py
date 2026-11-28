r"""Check the cache with the real clock, real stores, several processes
and several threads."""

from __future__ import annotations

import asyncio
import math
import os
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from persista.cache import MISSING, Cache
from persista.store import (
    DuckDBStore,
    FileStore,
    InMemoryStore,
    LmdbStore,
    PickleCodec,
    PostgresStore,
    RedisStore,
    SQLiteStore,
)
from persista.testing.fixtures import duckdb_available, lmdb_available
from tests.integration.store.postgres_helpers import (
    drop_tables,
    get_postgres_conninfo,
    postgres_available,
)
from tests.integration.store.redis_helpers import (
    REDIS_URL,
    delete_namespaces,
    redis_server_available,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from persista.store import BaseStore, Codec

# The prefix of the PostgreSQL tables and Redis namespaces of this run.
PREFIX = f"cache_{uuid.uuid4().hex[:12]}_"


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Iterator[None]:
    r"""Remove the data of the servers once the tests have run."""
    yield
    drop_tables(PREFIX)
    delete_namespaces(PREFIX)


def redis_store(codec: Codec) -> RedisStore:
    r"""Return a Redis store with a new namespace."""
    return RedisStore(REDIS_URL, codec=codec, namespace=f"{PREFIX}{uuid.uuid4().hex}")


def postgres_store(codec: Codec) -> PostgresStore:
    r"""Return a PostgreSQL store with a new table."""
    return PostgresStore(get_postgres_conninfo(), codec=codec, table=f"{PREFIX}{uuid.uuid4().hex}")


STORES = [
    pytest.param(lambda codec: InMemoryStore(codec=codec), id="in_memory"),
    pytest.param(lambda codec: SQLiteStore(codec=codec), id="sqlite"),
    pytest.param(lambda codec: DuckDBStore(codec=codec), id="duckdb", marks=duckdb_available),
    pytest.param(lambda codec: FileStore(tempfile.mkdtemp(), codec=codec), id="file"),
    pytest.param(
        lambda codec: LmdbStore(tempfile.mkdtemp(), codec=codec),
        id="lmdb",
        marks=lmdb_available,
    ),
    pytest.param(redis_store, id="redis", marks=redis_server_available),
    pytest.param(postgres_store, id="postgres", marks=postgres_available),
]


@pytest.fixture(params=STORES)
def store_factory(request: pytest.FixtureRequest) -> Callable[[Codec], BaseStore]:
    return request.param


async def run_python(code: str, seed: str = "0") -> str:
    r"""Run some code in a new interpreter with a hash seed, and return
    its output."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        code,
        env={**os.environ, "PYTHONHASHSEED": seed},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, errors = await process.communicate()
    if process.returncode:
        raise RuntimeError(errors.decode())
    return output.decode().strip()


############################
#     Tests for Cache      #
############################


def test_cache_memoize(store_factory: Callable[[Codec], BaseStore]) -> None:
    """Test that a memoized function runs once per call on every store,
    and that calls with arguments of different types are apart."""
    calls = []
    with Cache(store_factory(PickleCodec())) as cache:

        @cache.memoize()
        def kind(items: object) -> tuple[str, int]:
            calls.append(items)
            return type(items).__name__, len(calls)

        results = [kind([1]), kind((1,)), kind(items=[1])]
    assert results == [("list", 1), ("tuple", 2), ("list", 1)]


async def test_cache_memoize_async(store_factory: Callable[[Codec], BaseStore]) -> None:
    """Test that a memoized async function runs once per call on every
    store."""
    calls = []
    async with Cache(store_factory(PickleCodec())) as cache:

        @cache.memoize()
        async def pair(x: int) -> tuple[int, int]:
            calls.append(x)
            return x, x

        results = [await pair(1), await pair(x=1)]
    assert (results, calls) == ([(1, 1), (1, 1)], [1])


@pytest.mark.parametrize("ttl", [None, math.inf, 60])
def test_cache_ttl_json_store(
    store_factory: Callable[[Codec], BaseStore], ttl: float | None
) -> None:
    """Test that every ttl that does not expire at once can be stored
    with the JSON codec."""
    with Cache(store_factory(None)) as cache:
        cache.set_many({"a": [1], "b": None}, ttl=ttl)
        assert cache.get_many(["a", "b", "c"]) == {"a": [1], "b": None}


def test_cache_expiry(store_factory: Callable[[Codec], BaseStore]) -> None:
    """Test that an entry expires with the real clock, and is deleted
    when it is read."""
    store = store_factory(None)
    with Cache(store) as cache:
        cache.set("a", 1, ttl=0.05)
        time.sleep(0.1)
        assert (store.count(), cache.get("a", MISSING), store.count()) == (1, MISSING, 0)


async def test_cache_expiry_async(store_factory: Callable[[Codec], BaseStore]) -> None:
    """Test that an entry expires with the real clock with the async
    methods."""

    async with Cache(store_factory(None)) as cache:
        await cache.aset("a", 1, ttl=0.05)
        await asyncio.sleep(0.1)
        assert await cache.aget_many(["a"]) == {}


async def test_cache_memoize_shared_between_processes(tmp_path: Path) -> None:
    """Test that processes with different hash seeds share the result of
    a call whose argument is a set."""
    log = tmp_path / "calls.log"
    code = f"""
from persista.cache import Cache
from persista.store import SQLiteStore

with Cache(SQLiteStore({str(tmp_path / "cache.db")!r})) as cache:

    @cache.memoize()
    def count(words):
        with open({str(log)!r}, "a") as file:
            file.write("called\\n")
        return len(words)

    print(count({{f"word-{{i}}" for i in range(50)}}))
"""
    # One after the other, so that the next processes find the result.
    outputs = [await run_python(code, seed) for seed in ("1", "2", "3")]
    assert (outputs, log.read_text()) == (["50", "50", "50"], "called\n")


###################################
#     Tests for default cache     #
###################################


async def test_import_creates_no_cache() -> None:
    """Test that importing the package creates no cache and no store."""
    code = """
import gc

from persista.cache import Cache
from persista.store import BaseStore

print(sum(isinstance(obj, (Cache, BaseStore)) for obj in gc.get_objects()))
"""
    assert await run_python(code) == "0"


async def test_get_cache_creates_default_cache() -> None:
    """Test that the first call of get_cache creates an open cache."""
    code = """
from persista.cache import get_cache

cache = get_cache()
print(cache.closed, cache.default_ttl, cache is get_cache())
"""
    assert await run_python(code) == "False 300 True"


async def test_get_cache_threads_share_one_default_cache() -> None:
    """Test that threads that call get_cache at the same time get the
    same cache."""
    code = """
import threading
from concurrent.futures import ThreadPoolExecutor

from persista.cache import get_cache

barrier = threading.Barrier(16)


def get():
    barrier.wait()
    return get_cache()


with ThreadPoolExecutor(16) as executor:
    caches = list(executor.map(lambda _: get(), range(16)))
print(len({id(cache) for cache in caches}))
"""
    assert await run_python(code) == "1"


def test_cache_memoize_threads() -> None:
    """Test that threads that call a memoized function with different
    arguments get their own results."""
    barrier = threading.Barrier(8)
    with Cache() as cache:

        @cache.memoize()
        def double(x: int) -> int:
            return 2 * x

        def call(x: int) -> list[int]:
            barrier.wait(timeout=10)
            return [double(x) for _ in range(50)]

        with ThreadPoolExecutor(8) as executor:
            results = list(executor.map(call, range(8)))
    assert results == [[2 * x] * 50 for x in range(8)]
