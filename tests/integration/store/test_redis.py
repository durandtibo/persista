r"""Redis-specific tests for :class:`RedisStore`/:class:`PickleRedisStore`.

The generic :class:`~persista.store.BaseStore` contract (get/set/filter/
delete/keys/... and their async twins) is already exercised exhaustively,
identically across every backend including these two, by
``tests/integration/store/test_consistency.py``. Do not re-add tests here
for behavior that test file already covers -- only add a test here if it
depends on something specific to Redis: connection lifecycle/reconnection,
URI round-tripping, or the JSON-vs-pickle serialization difference between
:class:`RedisStore` and :class:`PickleRedisStore`.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import pytest

from persista.testing.fixtures import redis_available
from persista.utils.imports import is_redis_available
from tests.integration.store.redis_helpers import REDIS_URL, redis_server_available

if TYPE_CHECKING:
    from persista.store import BaseRedisStore

if is_redis_available():
    from persista.store import PickleRedisStore, RedisStore

pytestmark = [redis_available, redis_server_available]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=(["json", "pickle"] if is_redis_available() else []),
)
def store_cls(request: pytest.FixtureRequest) -> type[BaseRedisStore]:
    return {"json": RedisStore, "pickle": PickleRedisStore}[request.param]


@pytest.fixture
def store(store_cls: type[BaseRedisStore]) -> Generator[BaseRedisStore, None, None]:
    with store_cls(REDIS_URL) as store:
        # RedisStore/PickleRedisStore have no namespace prefix, so a shared
        # server must be cleared before/after each test to keep tests
        # isolated.
        store.delete_many(list(store.keys()))
        yield store
        store.delete_many(list(store.keys()))


@pytest.fixture(scope="module")
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


###############################
#     Tests for RedisStore    #
###############################


# --- constructor ---


def test_init_defaults(store: BaseRedisStore) -> None:
    assert store.count() == 0


def test_init_accepts_redis_from_url_kwargs(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL, socket_timeout=5.0) as store:
        store.delete_many(list(store.keys()))
        assert store.count() == 0


# --- repr/str ---


def test_repr(store: BaseRedisStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


def test_repr_after_close_does_not_raise(store: BaseRedisStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- context manager: reconnection lifecycle ---


def test_context_manager_multiple_open_close(store_cls: type[BaseRedisStore]) -> None:
    """Reopening a store after close reconnects to the same Redis server,
    so previously written data is still there."""
    redis_store = store_cls(REDIS_URL)
    try:
        with redis_store as store:
            store.delete_many(list(store.keys()))
        for i in range(3):
            with redis_store as store:
                store.set(str(i), {"text": "hello"})
                assert store.get(str(i)) == {"text": "hello"}
    finally:
        with redis_store as store:
            store.delete_many(list(store.keys()))


async def test_async_context_manager_multiple_open_close(
    store_cls: type[BaseRedisStore],
) -> None:
    redis_store = store_cls(REDIS_URL)
    try:
        async with redis_store as store:
            await store.adelete_many([key async for key in store.akeys()])
        for i in range(3):
            async with redis_store as store:
                await store.aset(str(i), {"text": "hello"})
                assert await store.aget(str(i)) == {"text": "hello"}
    finally:
        async with redis_store as store:
            await store.adelete_many([key async for key in store.akeys()])


# --- to_uri / from_uri ---


def test_to_uri_from_uri_round_trips_data(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL) as store:
        store.delete_many(list(store.keys()))
        store.set("1", {"text": "hello", "author": "Alice"})
        uri = store.to_uri()
        try:
            with store_cls.from_uri(uri) as reloaded:
                assert reloaded.get("1") == {"text": "hello", "author": "Alice"}
        finally:
            store.delete_many(list(store.keys()))


async def test_to_uri_from_uri_async_round_trip(
    store_cls: type[BaseRedisStore], items: dict[str, dict[str, Any]]
) -> None:
    async with store_cls(REDIS_URL) as async_store:
        await async_store.aset_many(items)
        uri = async_store.to_uri()
        try:
            async with store_cls.from_uri(uri) as reloaded:
                assert await reloaded.acount() == len(items)
        finally:
            await async_store.adelete_many([key async for key in async_store.akeys()])


##########################################################
#     PickleRedisStore-specific serialization behavior    #
##########################################################

# RedisStore stores values as JSON, PickleRedisStore as pickle -- this is
# the one place their behavior actually diverges, since JSON has no native
# tuple/set type.


async def test_pickle_store_round_trips_tuples_and_sets(store: BaseRedisStore) -> None:
    if not isinstance(store, PickleRedisStore):
        pytest.skip("Only meaningful for PickleRedisStore")
    await store.aset("1", {"coordinates": (1, 2, 3), "tags": {"python", "redis"}})
    assert await store.aget("1") == {"coordinates": (1, 2, 3), "tags": {"python", "redis"}}


async def test_json_store_normalizes_tuples_and_rejects_sets(store: BaseRedisStore) -> None:
    if isinstance(store, PickleRedisStore):
        pytest.skip("Only meaningful for RedisStore")
    await store.aset("1", {"coordinates": (1, 2, 3)})
    # JSON has no tuple type, so it comes back as a list.
    assert await store.aget("1") == {"coordinates": [1, 2, 3]}
    with pytest.raises(TypeError, match="not JSON serializable"):
        await store.aset("2", {"tags": {"python", "redis"}})
