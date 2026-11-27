r"""Redis-specific tests for :class:`~persista.store.RedisStore`, with a
real server and no patching.

The ``BaseStore`` contract is tested by ``test_consistency.py`` and
``test_contract.py``, and the concurrent writers by
``test_redis_concurrency.py``. Only add a test here if it depends on
something specific to Redis: the connections, the credentials, the keys
of a namespace or the event loops of the async clients.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import pytest

from persista.cache import Cache
from persista.store import PickleCodec, RedisStore, store_from_uri
from persista.testing.fixtures import httpx_available, redis_available
from persista.utils.imports import is_httpx_available, is_redis_available
from tests.integration.store.redis_helpers import (
    REDIS_URL,
    delete_namespaces,
    redis_server_available,
)

if is_httpx_available():
    import httpx

    from persista.http.httpx import AsyncHttpClient

if is_redis_available():
    import redis

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

pytestmark = [redis_available, redis_server_available]

# The prefix of the namespaces of this module.
PREFIX = f"persista-redis-{uuid.uuid4().hex}"

NUM_WRITES = 50


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Generator[None, None, None]:
    r"""Remove the data of the tests from the server."""
    yield
    delete_namespaces(PREFIX)


@pytest.fixture
def namespace() -> str:
    r"""Return a namespace that no other test uses."""
    return f"{PREFIX}-{uuid.uuid4().hex}"


@pytest.fixture
def client_name() -> str:
    r"""Return a name for the connections of one test."""
    return f"persista-test-{uuid.uuid4().hex}"


@pytest.fixture
def store(namespace: str, client_name: str) -> Generator[RedisStore, None, None]:
    with RedisStore(REDIS_URL, namespace=namespace, client_name=client_name) as store:
        yield store


@pytest.fixture
def server() -> Generator[Any, None, None]:
    r"""Return a client of the server, outside of any store."""
    with redis.Redis.from_url(REDIS_URL) as client:
        yield client


def count_connections(server: Any, client_name: str, expected: int) -> int:
    r"""Return the number of connections of the server with a name.

    The server notices a closed connection a moment after the client, so
    this waits a little for the expected number.
    """
    for _ in range(200):
        count = sum(client["name"] == client_name for client in server.client_list())
        if count == expected:
            break
        threading.Event().wait(0.01)
    return count


def url_with_credentials(username: str, password: str) -> str:
    r"""Return the URL of the server with other credentials."""
    parts = urlsplit(REDIS_URL)
    host = parts.netloc.rpartition("@")[2]
    return urlunsplit(parts._replace(netloc=f"{username}:{password}@{host}"))


async def write_concurrently(store: RedisStore, prefix: str) -> None:
    r"""Write several keys at the same time."""
    await asyncio.gather(*(store.aset(f"{prefix}-{i}", {}) for i in range(NUM_WRITES)))


###############################
#     Tests for RedisStore    #
###############################


# --- connections ---


def test_open_unreachable_server_raises() -> None:
    store = RedisStore("redis://127.0.0.1:1/0", socket_connect_timeout=1)
    with pytest.raises(redis.ConnectionError, match=r"127.0.0.1:1"):
        store.open()
    assert store.closed


def test_open_unknown_user_raises_without_the_password() -> None:
    password = uuid.uuid4().hex
    store = RedisStore(url_with_credentials(f"nobody-{uuid.uuid4().hex}", password))
    with pytest.raises(redis.AuthenticationError, match=r"invalid") as exc_info:
        store.open()
    assert (store.closed, password in str(exc_info.value)) == (True, False)


def test_open_user_without_ping_permission(server: Any, namespace: str) -> None:
    user = f"persista-test-{uuid.uuid4().hex}"
    password = uuid.uuid4().hex
    server.acl_setuser(
        user,
        enabled=True,
        passwords=[f"+{password}"],
        categories=["+@all"],
        commands=["-ping"],
        keys=["*"],
    )
    try:
        url = url_with_credentials(user, password)
        with RedisStore(url, namespace=namespace) as store:
            store.set("1", {"a": 1})
            assert store.get("1") == {"a": 1}
    finally:
        server.acl_deluser(user)


def test_close_releases_the_connections(server: Any, namespace: str, client_name: str) -> None:
    with RedisStore(REDIS_URL, namespace=namespace, client_name=client_name) as store:
        store.set("1", {})
    assert count_connections(server, client_name, 0) == 0


async def test_aclose_releases_the_connections(
    store: RedisStore, server: Any, client_name: str
) -> None:
    await write_concurrently(store, "a")
    await store.aclose()
    assert count_connections(server, client_name, 0) == 0


def test_loop_shutdown_releases_the_async_connections(
    store: RedisStore, server: Any, client_name: str
) -> None:
    r"""Test that the connections of an async client are closed when its
    event loop shuts down, and that the sync client keeps its own."""
    asyncio.run(write_concurrently(store, "a"))
    assert count_connections(server, client_name, 1) == 1


async def test_aclose_while_calls_are_in_progress(
    store: RedisStore, server: Any, client_name: str
) -> None:
    r"""Test that closing a store while async calls use it lets them
    end, and releases every connection."""
    calls = [
        asyncio.ensure_future(store.aset("a", {str(i): i}, on_conflict="merge"))
        for i in range(NUM_WRITES)
    ]
    await asyncio.sleep(0)
    await store.aclose()
    results = await asyncio.gather(*calls, return_exceptions=True)
    assert (results, count_connections(server, client_name, 0)) == ([None] * NUM_WRITES, 0)


async def test_aclose_during_an_iteration(store: RedisStore) -> None:
    store.set_many({"1": {}, "2": {}})
    iterator = store.aiter_batches(batch_size=1)
    await anext(iterator)
    await store.aclose()
    with pytest.raises(RuntimeError, match=r"is not open"):
        await anext(iterator)


def test_too_many_concurrent_calls_raise(namespace: str) -> None:
    async def write() -> None:
        async with RedisStore(REDIS_URL, namespace=namespace, max_connections=2) as store:
            await write_concurrently(store, "a")

    with pytest.raises(redis.exceptions.MaxConnectionsError, match=r"Too many connections"):
        asyncio.run(write())


async def test_concurrent_calls_with_more_connections(namespace: str) -> None:
    async with RedisStore(REDIS_URL, namespace=namespace, max_connections=300) as store:
        await asyncio.gather(*(store.aset(str(i), {}) for i in range(300)))
        assert await store.acount() == 300


# --- event loops ---


def test_async_use_in_two_event_loops(store: RedisStore) -> None:
    r"""Test that a store used with ``asyncio.run``, without ``aclose``,
    can be used in another event loop (regression test: the client of
    the first loop was used again)."""
    asyncio.run(write_concurrently(store, "first"))
    asyncio.run(write_concurrently(store, "second"))
    assert store.count() == 2 * NUM_WRITES


def test_close_after_async_use_in_a_finished_loop(
    store: RedisStore, server: Any, client_name: str
) -> None:
    asyncio.run(store.aset("1", {}))
    store.close()
    assert count_connections(server, client_name, 0) == 0


async def test_close_in_the_loop_of_an_async_call_raises(store: RedisStore) -> None:
    await store.aset("1", {})
    with pytest.raises(RuntimeError, match=r"An async client of RedisStore is open"):
        store.close()
    assert await store.aget("1") == {}
    await store.aclose()


async def test_reopen_after_aclose(namespace: str) -> None:
    store = RedisStore(REDIS_URL, namespace=namespace)
    async with store:
        await store.aset("1", {"a": 1})
    async with store:
        assert await store.aget("1") == {"a": 1}


def test_two_event_loops_in_two_threads(store: RedisStore) -> None:
    r"""Test that two event loops that run at the same time in two
    threads share a store."""
    barrier = threading.Barrier(2)

    async def write(prefix: str) -> None:
        for i in range(NUM_WRITES):
            await store.aset("a", {f"{prefix}-{i}": i}, on_conflict="merge")
            # Both loops are running here, each with its client.
            barrier.wait(timeout=30)

    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda prefix: asyncio.run(write(prefix)), "ab"))
    assert len(store.get("a")) == 2 * NUM_WRITES


# --- namespaces ---


def test_key_layout(store: RedisStore, server: Any, namespace: str) -> None:
    store.set_many({"1": {"a": 1}, "__keys__": {}})
    assert (
        sorted(server.scan_iter(match=f"{namespace}:*")),
        server.smembers(f"{namespace}:keys"),
        server.get(f"{namespace}:v:1"),
    ) == (
        [f"{namespace}:{name}".encode() for name in ("keys", "v:1", "v:__keys__")],
        {b"1", b"__keys__"},
        b'{"a": 1}',
    )


@pytest.mark.parametrize(
    "suffix",
    [
        pytest.param(":other", id="starts_with_the_other"),
        pytest.param(":keys", id="keys"),
        pytest.param(":", id="colon"),
        pytest.param("2", id="longer"),
    ],
)
def test_namespaces_are_isolated(namespace: str, suffix: str) -> None:
    r"""Test that namespaces that start the same way share no key, even
    for keys that look like the Redis keys of the other namespace."""
    keys = ["", "1", "keys", "v:1", ":v:1", "other:v:1", "other:keys", "__keys__"]
    with (
        RedisStore(REDIS_URL, namespace=namespace) as first,
        RedisStore(REDIS_URL, namespace=namespace + suffix) as second,
    ):
        first.set_many({key: {"store": 1} for key in keys})
        second.set_many({key: {"store": 2} for key in keys})
        assert (first.get_many(keys), second.get_many(keys), first.count(), second.count()) == (
            [{"store": 1}] * len(keys),
            [{"store": 2}] * len(keys),
            len(keys),
            len(keys),
        )


@pytest.mark.parametrize(
    "clear",
    [
        pytest.param(lambda s: s.clear(), id="clear"),
        pytest.param(lambda s: asyncio.run(s.aclear()), id="aclear"),
    ],
)
def test_clear_does_not_touch_other_data(
    store: RedisStore, server: Any, namespace: str, clear: Callable[[RedisStore], Any]
) -> None:
    server.set(f"{namespace}:unrelated", "x")
    with RedisStore(REDIS_URL, namespace=f"{namespace}:other") as other:
        other.set("1", {})
        store.set("1", {})
        clear(store)
        assert (store.count(), other.get("1"), server.get(f"{namespace}:unrelated")) == (
            0,
            {},
            b"x",
        )


def test_clear_large_namespace(store: RedisStore, server: Any, namespace: str) -> None:
    store.set_many({str(i): {} for i in range(5000)})
    store.clear()
    assert list(server.scan_iter(match=f"{namespace}:*", count=1000)) == []


def test_iterate_large_namespace(store: RedisStore) -> None:
    store.set_many({str(i): {} for i in range(5000)})
    assert sum(len(batch) for batch in store.iter_batches(batch_size=128)) == 5000


# --- codec and client ---


async def test_pickle_codec_round_trips_python_types(namespace: str) -> None:
    async with RedisStore(REDIS_URL, codec=PickleCodec(), namespace=namespace) as store:
        await store.aset("1", {"coordinates": (1, 2), "tags": {"python"}})
        await store.aset("1", {"more": b"x"}, on_conflict="merge")
        assert await store.aget("1") == {
            "coordinates": (1, 2),
            "tags": {"python"},
            "more": b"x",
        }


@pytest.mark.parametrize("protocol", [2, 3])
async def test_protocols(namespace: str, protocol: int) -> None:
    async with RedisStore(REDIS_URL, namespace=namespace, protocol=protocol) as store:
        await store.aset_many({"1": {}, "2": {}}, on_conflict="skip")
        assert (
            sorted([key async for key in store.akeys()]),
            await store.acontains_many(["1", "3"]),
            store.contains_many(["1", "3"]),
            await store.acount(),
        ) == (["1", "2"], [True, False], [True, False], 2)


def test_client_returns_the_stored_bytes(store: RedisStore, namespace: str) -> None:
    store.set("1", {"a": 1})
    assert store.client.get(f"{namespace}:v:1") == b'{"a": 1}'


# --- URI ---


def test_from_uri_with_the_options_reads_the_data(namespace: str) -> None:
    codec = PickleCodec()
    with RedisStore(REDIS_URL, codec=codec, namespace=namespace) as store:
        store.set("1", {"tags": {"a"}})
        uri = store.to_uri()
    with RedisStore.from_uri(uri, codec=codec, namespace=namespace) as restored:
        assert restored.get("1") == {"tags": {"a"}}


def test_store_from_uri_uses_the_default_options() -> None:
    with store_from_uri(REDIS_URL) as restored:
        assert (type(restored), restored.namespace) == (RedisStore, "persista")


# --- secrets ---


def test_repr_and_logs_hide_the_password(namespace: str, caplog: pytest.LogCaptureFixture) -> None:
    r"""Test that the password of the URL does not appear in the
    ``repr`` of an open store, nor in the logs."""
    password = uuid.uuid4().hex
    # A user without password accepts any password.
    url = url_with_credentials("default", password)
    texts = []
    with caplog.at_level(logging.DEBUG):
        with contextlib.closing(RedisStore(url, namespace=namespace)) as store:
            store.open()
            store.set("1", {})
            texts.append(repr(store))
        texts.append(repr(store))
    assert [text for text in [*texts, *caplog.messages] if password in text] == []


# --- cache and HTTP cache ---


async def test_cache_aclose(namespace: str, server: Any, client_name: str) -> None:
    cache = Cache(RedisStore(REDIS_URL, namespace=namespace, client_name=client_name))
    async with cache:
        await cache.aset("a", 1)
    assert (cache.closed, count_connections(server, client_name, 0)) == (True, 0)


async def test_cache_close_in_the_loop_of_an_async_call_raises(namespace: str) -> None:
    cache = Cache(RedisStore(REDIS_URL, namespace=namespace))
    cache.open()
    await cache.aset("a", 1)
    with pytest.raises(RuntimeError, match=r"call `await store.aclose\(\)`"):
        cache.close()
    assert not cache.closed
    await cache.aclose()


def test_cache_close_after_async_use_in_a_finished_loop(namespace: str) -> None:
    with Cache(RedisStore(REDIS_URL, namespace=namespace)) as cache:
        asyncio.run(cache.aset("a", 1))
        asyncio.run(cache.aset("b", 2))
    assert cache.closed


@httpx_available
def test_http_cache_in_two_event_loops(namespace: str) -> None:
    r"""Test that the cache of an async HTTP client works in two event
    loops, and can then be closed without a loop."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    async def get(cache: Cache) -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await AsyncHttpClient(client, cache=cache).get("https://example.com")
            return response.json()

    with Cache(RedisStore(REDIS_URL, namespace=namespace)) as cache:
        results = [asyncio.run(get(cache)), asyncio.run(get(cache))]
    assert (results, len(requests), cache.closed) == ([{"ok": True}] * 2, 1, True)
