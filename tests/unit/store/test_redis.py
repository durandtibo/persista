from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from persista.store import JsonCodec, PickleCodec, RedisStore
from persista.store.plan import build_plan
from persista.store.redis import (
    _check_url,
    _decode_keys,
    _encode_key,
    _encode_keys,
    _encode_members,
    _LoopClient,
    _present,
    _redact_url,
)
from persista.testing.fixtures import redis_available, redis_not_available
from persista.utils.imports import is_redis_available

if is_redis_available():
    import fakeredis
    import redis

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

MODULE = "persista.store.redis"

URL = "redis://localhost:6379/0"

SURROGATE = chr(0xD800)

PAYLOADS = {"1": b'{"a": 1}', "2": b'{"a": 2}', "3": b'{"a": 3}'}

# The Redis keys of a store that contains PAYLOADS.
REDIS_KEYS = [b"persista:keys", b"persista:v:1", b"persista:v:2", b"persista:v:3"]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Any:
    r"""Replace the Redis server of the sync and async clients by a fake
    one, and return it."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        f"{MODULE}.redis.Redis.from_url",
        lambda _url, **_kwargs: fakeredis.FakeRedis(server=server),
    )
    monkeypatch.setattr(
        f"{MODULE}.aredis.Redis.from_url",
        lambda _url, **_kwargs: fakeredis.FakeAsyncRedis(server=server),
    )
    return server


@pytest.fixture
def raw(server: Any) -> Any:
    r"""Return a client of the fake server, outside of any store."""
    return fakeredis.FakeRedis(server=server)


@pytest.fixture
def store(server: Any) -> Generator[RedisStore, None, None]:
    del server  # The store connects to the fake server.
    with RedisStore() as store:
        yield store


@pytest.fixture
def filled_store(store: RedisStore) -> RedisStore:
    store._put_many(PAYLOADS)
    return store


def scan(client: Any) -> list[bytes]:
    r"""Return the sorted keys of a Redis database."""
    return sorted(client.keys())


###############################
#     Tests for RedisStore    #
###############################


@redis_not_available
def test_init_without_redis() -> None:
    with pytest.raises(RuntimeError, match=r"'redis' package is required"):
        RedisStore()


# --- constructor ---


@redis_available
def test_init_defaults() -> None:
    store = RedisStore()
    assert (store.to_uri(), store.namespace, store.closed) == (URL, "persista", True)


@redis_available
def test_init_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    from_url = MagicMock()
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", from_url)
    RedisStore()
    from_url.assert_not_called()


@redis_available
def test_init_namespace() -> None:
    assert RedisStore(namespace="app:cache").namespace == "app:cache"


@redis_available
def test_init_options_are_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        RedisStore(URL, JsonCodec())


@redis_available
@pytest.mark.parametrize("namespace", ["", "a:v", "a:v:b", SURROGATE])
def test_init_invalid_namespace(namespace: str) -> None:
    with pytest.raises(ValueError, match=r"[Nn]amespace"):
        RedisStore(namespace=namespace)


@redis_available
def test_init_namespace_not_a_str() -> None:
    with pytest.raises(TypeError, match=r"A namespace must be a str"):
        RedisStore(namespace=None)


@redis_available
@pytest.mark.parametrize(
    ("url", "kwargs"),
    [
        pytest.param(URL, {"decode_responses": True}, id="argument"),
        pytest.param(URL, {"decode_responses": False}, id="argument_false"),
        pytest.param(f"{URL}?decode_responses=true", {}, id="url"),
    ],
)
def test_init_rejects_decode_responses(url: str, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"does not accept decode_responses"):
        RedisStore(url, **kwargs)


@redis_available
def test__open_passes_the_url_and_the_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from_url = MagicMock()
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", from_url)
    RedisStore(URL, socket_timeout=5.0).open()
    from_url.assert_called_once_with(URL, socket_timeout=5.0)


@redis_available
async def test__async_client_passes_the_url_and_the_options(
    server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from_url = MagicMock(return_value=fakeredis.FakeAsyncRedis(server=server))
    monkeypatch.setattr(f"{MODULE}.aredis.Redis.from_url", from_url)
    async with RedisStore(URL, socket_timeout=5.0) as store:
        await store.acount()
    from_url.assert_called_once_with(URL, socket_timeout=5.0)


# --- open / close ---


@redis_available
def test__open_pings_the_server(server: Any) -> None:
    server.connected = False
    store = RedisStore()
    with pytest.raises(redis.ConnectionError, match=r"."):
        store.open()
    assert store.closed


@redis_available
def test__open_user_without_ping_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.ping.side_effect = redis.exceptions.NoPermissionError("no permission")
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", lambda _url: client)
    with RedisStore() as store:
        assert store.client is client


@redis_available
def test__open_failure_closes_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.ping.side_effect = redis.AuthenticationError("invalid password")
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", lambda _url: client)
    with pytest.raises(redis.AuthenticationError, match=r"invalid password"):
        RedisStore().open()
    client.close.assert_called_once_with()


@redis_available
def test__open_invalid_url_hides_the_password() -> None:
    store = RedisStore("redis://user:pa55/word@localhost:6379/0")
    with pytest.raises(ValueError, match=r"Invalid Redis URL") as exc_info:
        store.open()
    assert "pa55" not in str(exc_info.value)


@redis_available
def test__close(store: RedisStore) -> None:
    store._close()
    with pytest.raises(RuntimeError, match=r"RedisStore is not open"):
        _ = store.client


@redis_available
def test__close_without_open(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        RedisStore()._close()
    assert caplog.messages == []


@redis_available
@pytest.mark.usefixtures("server")
def test__close_does_not_log_the_password(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG), RedisStore("redis://user:secret@localhost:6379/0"):
        pass
    assert [message for message in caplog.messages if "Redis" in message] == [
        "Closing Redis connection at redis://localhost:6379/0"
    ]


@redis_available
@pytest.mark.usefixtures("server")
def test_reopen_keeps_values() -> None:
    store = RedisStore()
    with store:
        store.set("1", {"a": 1})
    with store:
        assert store.get("1") == {"a": 1}


@redis_available
def test_client_not_open() -> None:
    with pytest.raises(RuntimeError, match=r"RedisStore is not open"):
        _ = RedisStore().client


@redis_available
def test_client_returns_bytes(filled_store: RedisStore) -> None:
    assert filled_store.client.scard("persista:keys") == 3


# --- namespace ---


@redis_available
@pytest.mark.usefixtures("filled_store")
def test_key_layout(raw: Any) -> None:
    assert scan(raw) == REDIS_KEYS


@redis_available
@pytest.mark.usefixtures("filled_store")
def test_key_layout_members(raw: Any) -> None:
    assert raw.smembers("persista:keys") == {b"1", b"2", b"3"}


@redis_available
def test_former_keys_set_name_is_a_key(store: RedisStore) -> None:
    store.set("__keys__", {"a": 1})
    assert (store.get("__keys__"), list(store.keys())) == ({"a": 1}, ["__keys__"])


@redis_available
@pytest.mark.usefixtures("filled_store")
def test_namespaces_do_not_share_keys() -> None:
    with RedisStore(namespace="persista:other") as other:
        assert (other.get("1"), other.count()) == (None, 0)


@redis_available
def test_clear_keeps_other_namespaces_and_keys(filled_store: RedisStore, raw: Any) -> None:
    raw.set("persista:unrelated", "x")
    with RedisStore(namespace="other") as other:
        other.set("1", {})
        filled_store.clear()
    assert scan(raw) == [b"other:keys", b"other:v:1", b"persista:unrelated"]


# --- keys ---


@redis_available
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s, k: s.get(k), id="get"),
        pytest.param(lambda s, k: s.get_many(["1", k]), id="get_many"),
        pytest.param(lambda s, k: s.contains(k), id="contains"),
        pytest.param(lambda s, k: s.set(k, {}), id="set"),
        pytest.param(lambda s, k: s.set_many({"new": {}, k: {}}), id="set_many"),
        pytest.param(
            lambda s, k: s.set_many({"new": {}, k: {}}, on_conflict="skip"), id="set_many_skip"
        ),
        pytest.param(lambda s, k: s.delete(k), id="delete"),
        pytest.param(lambda s, k: s.delete_many(["1", k]), id="delete_many"),
    ],
)
def test_surrogate_key_raises_and_changes_nothing(
    filled_store: RedisStore, raw: Any, operation: Callable[[RedisStore, str], Any]
) -> None:
    with pytest.raises(ValueError, match=r"A key of RedisStore must be valid Unicode"):
        operation(filled_store, SURROGATE)
    assert scan(raw) == REDIS_KEYS


@redis_available
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s, k: s.aget(k), id="aget"),
        pytest.param(lambda s, k: s.aget_many(["1", k]), id="aget_many"),
        pytest.param(lambda s, k: s.acontains(k), id="acontains"),
        pytest.param(lambda s, k: s.aset(k, {}), id="aset"),
        pytest.param(lambda s, k: s.aset_many({"new": {}, k: {}}), id="aset_many"),
        pytest.param(
            lambda s, k: s.aset_many({"new": {}, k: {}}, on_conflict="skip"), id="aset_many_skip"
        ),
        pytest.param(lambda s, k: s.adelete(k), id="adelete"),
        pytest.param(lambda s, k: s.adelete_many(["1", k]), id="adelete_many"),
    ],
)
async def test_surrogate_key_raises_and_changes_nothing_async(
    filled_store: RedisStore, raw: Any, operation: Callable[[RedisStore, str], Any]
) -> None:
    with pytest.raises(ValueError, match=r"A key of RedisStore must be valid Unicode"):
        await operation(filled_store, SURROGATE)
    assert scan(raw) == REDIS_KEYS
    await filled_store.aclose()


# --- primitives ---


@redis_available
@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param(["1"], {"1": b'{"a": 1}'}, id="one"),
        pytest.param(["4"], {}, id="one_missing"),
        pytest.param(["1", "4", "3", "1"], {"1": b'{"a": 1}', "3": b'{"a": 3}'}, id="many"),
        pytest.param(["4", "5"], {}, id="many_missing"),
    ],
)
def test__get_many(filled_store: RedisStore, keys: list[str], expected: dict) -> None:
    assert filled_store._get_many(keys) == expected


@redis_available
@pytest.mark.parametrize("payload", ['{"a": "é"}', '{"a": "é"}'.encode()])
def test__put_many(store: RedisStore, payload: str | bytes) -> None:
    store._put_many({"1": payload})
    assert store.client.get("persista:v:1") == '{"a": "é"}'.encode()


@redis_available
def test__put_many_removes_a_time_to_live(filled_store: RedisStore) -> None:
    filled_store.client.expire("persista:v:1", 100)
    filled_store._put_many({"1": b"{}"})
    assert filled_store.client.ttl("persista:v:1") == -1


@redis_available
def test__update(filled_store: RedisStore) -> None:
    filled_store._update(["1", "4"], lambda _: {"4": b"{}"})
    assert filled_store._get_many(["1", "4"]) == {"1": b'{"a": 1}', "4": b"{}"}


@redis_available
def test__update_adds_the_keys_to_the_set(store: RedisStore) -> None:
    store._update(["1"], lambda _: {"1": b"{}"})
    assert store.client.smembers("persista:keys") == {b"1"}


@redis_available
def test__update_gives_the_existing_payloads_to_the_plan(filled_store: RedisStore) -> None:
    plan = MagicMock(return_value={})
    filled_store._update(["2", "4"], plan)
    plan.assert_called_once_with({"2": b'{"a": 2}'})


@redis_available
def test__update_empty_plan_writes_nothing(store: RedisStore, raw: Any) -> None:
    store._update(["1"], lambda _: {})
    assert scan(raw) == []


@redis_available
def test__update_plan_raises_writes_nothing(filled_store: RedisStore) -> None:
    plan = build_plan({"1": "{}", "4": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store._update(["1", "4"], plan)
    assert filled_store._get_many(["1", "4"]) == {"1": b'{"a": 1}'}


@redis_available
@pytest.mark.parametrize(
    ("change", "second_existing"),
    [
        pytest.param(lambda c: c.set("persista:v:1", b"new"), {"1": b"new"}, id="overwrite"),
        pytest.param(lambda c: c.delete("persista:v:1"), {}, id="delete"),
    ],
)
def test__update_calls_the_plan_again_after_a_concurrent_write(
    filled_store: RedisStore, raw: Any, change: Callable[[Any], Any], second_existing: dict
) -> None:
    calls = []

    def plan(existing: dict) -> dict:
        calls.append(existing)
        if len(calls) == 1:
            change(raw)
        return {"1": b"planned"}

    filled_store._update(["1"], plan)
    assert (calls, raw.get("persista:v:1")) == (
        [{"1": b'{"a": 1}'}, second_existing],
        b"planned",
    )


@redis_available
def test__update_detects_the_creation_of_a_missing_key(store: RedisStore, raw: Any) -> None:
    def plan(existing: dict) -> dict:
        if existing:
            return {}
        raw.set("persista:v:1", b"other")
        return {"1": b"planned"}

    store._update(["1"], plan)
    assert raw.get("persista:v:1") == b"other"


@redis_available
def test__delete_many(filled_store: RedisStore, raw: Any) -> None:
    filled_store._delete_many(["1", "3", "4", "1"])
    assert (scan(raw), raw.smembers("persista:keys")) == (
        [b"persista:keys", b"persista:v:2"],
        {b"2"},
    )


@redis_available
def test__clear(filled_store: RedisStore, raw: Any) -> None:
    filled_store._clear()
    assert scan(raw) == []


@redis_available
def test__clear_empty_store(store: RedisStore, raw: Any) -> None:
    store._clear()
    assert scan(raw) == []


@redis_available
def test__clear_several_batches(
    filled_store: RedisStore, raw: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(f"{MODULE}._DELETE_BATCH_SIZE", 2)
    filled_store._clear()
    assert scan(raw) == []


@redis_available
def test__clear_keeps_a_key_created_during_the_call(
    filled_store: RedisStore, raw: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = filled_store._snapshot_keys

    def snapshot_then_write() -> list[bytes]:
        keys = snapshot()
        filled_store._put_many({"4": b"{}"})
        return keys

    monkeypatch.setattr(filled_store, "_snapshot_keys", snapshot_then_write)
    filled_store._clear()
    assert (scan(raw), raw.smembers("persista:keys")) == (
        [b"persista:keys", b"persista:v:4"],
        {b"4"},
    )


@redis_available
def test__count(filled_store: RedisStore) -> None:
    assert filled_store._count() == 3


@redis_available
def test__contains_many(filled_store: RedisStore) -> None:
    assert filled_store._contains_many(["1", "4", "3", "1"]) == {"1", "3"}


# --- iteration ---


@redis_available
@pytest.mark.parametrize(("batch_size", "sizes"), [(1, [1, 1, 1]), (2, [2, 1]), (10, [3])])
def test__iter_batches_sizes(filled_store: RedisStore, batch_size: int, sizes: list[int]) -> None:
    assert [len(batch) for batch in filled_store._iter_batches(batch_size)] == sizes


@redis_available
def test__iter_batches_payloads(filled_store: RedisStore) -> None:
    assert list(filled_store._iter_batches(10)) == [PAYLOADS]


@redis_available
def test__iter_key_batches(filled_store: RedisStore) -> None:
    assert sorted(key for batch in filled_store._iter_key_batches(2) for key in batch) == [
        "1",
        "2",
        "3",
    ]


@redis_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_empty_store(store: RedisStore, method: str) -> None:
    assert list(getattr(store, method)(2)) == []


@redis_available
def test_iteration_skips_keys_deleted_since_the_snapshot(filled_store: RedisStore) -> None:
    iterator = filled_store._iter_batches(1)
    first = next(iterator)
    filled_store._clear()
    assert (len(first), list(iterator)) == (1, [])


@redis_available
@pytest.mark.parametrize("method", ["_iter_batches", "_iter_key_batches"])
def test_iteration_does_not_yield_keys_written_after_the_snapshot(
    filled_store: RedisStore, method: str
) -> None:
    iterator = getattr(filled_store, method)(1)
    next(iterator)
    filled_store._put_many({"4": b"{}"})
    assert len(list(iterator)) == 2


@redis_available
def test__snapshot_keys(filled_store: RedisStore) -> None:
    assert sorted(filled_store._snapshot_keys()) == [b"1", b"2", b"3"]


# --- async primitives ---


@redis_available
@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param(["1"], {"1": b'{"a": 1}'}, id="one"),
        pytest.param(["4"], {}, id="one_missing"),
        pytest.param(["1", "4", "3", "1"], {"1": b'{"a": 1}', "3": b'{"a": 3}'}, id="many"),
    ],
)
async def test__aget_many(filled_store: RedisStore, keys: list[str], expected: dict) -> None:
    assert await filled_store._aget_many(keys) == expected
    await filled_store.aclose()


@redis_available
async def test__aput_many(store: RedisStore, raw: Any) -> None:
    await store._aput_many(PAYLOADS)
    assert scan(raw) == REDIS_KEYS
    await store.aclose()


@redis_available
async def test__aupdate(filled_store: RedisStore) -> None:
    await filled_store._aupdate(["1", "4"], lambda _: {"4": b"{}"})
    assert filled_store._get_many(["1", "4"]) == {"1": b'{"a": 1}', "4": b"{}"}
    await filled_store.aclose()


@redis_available
async def test__aupdate_gives_the_existing_payloads_to_the_plan(filled_store: RedisStore) -> None:
    plan = MagicMock(return_value={})
    await filled_store._aupdate(["2", "4"], plan)
    plan.assert_called_once_with({"2": b'{"a": 2}'})
    await filled_store.aclose()


@redis_available
async def test__aupdate_plan_raises_writes_nothing(filled_store: RedisStore) -> None:
    plan = build_plan({"1": "{}", "4": "{}"}, "raise", JsonCodec())
    with pytest.raises(KeyError, match=r"already exist"):
        await filled_store._aupdate(["1", "4"], plan)
    assert filled_store._get_many(["1", "4"]) == {"1": b'{"a": 1}'}
    await filled_store.aclose()


@redis_available
@pytest.mark.parametrize(
    ("change", "second_existing"),
    [
        pytest.param(lambda c: c.set("persista:v:1", b"new"), {"1": b"new"}, id="overwrite"),
        pytest.param(lambda c: c.delete("persista:v:1"), {}, id="delete"),
    ],
)
async def test__aupdate_calls_the_plan_again_after_a_concurrent_write(
    filled_store: RedisStore, raw: Any, change: Callable[[Any], Any], second_existing: dict
) -> None:
    calls = []

    def plan(existing: dict) -> dict:
        calls.append(existing)
        if len(calls) == 1:
            change(raw)
        return {"1": b"planned"}

    await filled_store._aupdate(["1"], plan)
    assert (calls, raw.get("persista:v:1")) == (
        [{"1": b'{"a": 1}'}, second_existing],
        b"planned",
    )
    await filled_store.aclose()


@redis_available
async def test__adelete_many(filled_store: RedisStore, raw: Any) -> None:
    await filled_store._adelete_many(["1", "3", "4"])
    assert (scan(raw), raw.smembers("persista:keys")) == (
        [b"persista:keys", b"persista:v:2"],
        {b"2"},
    )
    await filled_store.aclose()


@redis_available
async def test__aclear(filled_store: RedisStore, raw: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{MODULE}._DELETE_BATCH_SIZE", 2)
    raw.set("other:v:1", "x")
    await filled_store._aclear()
    assert scan(raw) == [b"other:v:1"]
    await filled_store.aclose()


@redis_available
async def test__aclear_empty_store(store: RedisStore, raw: Any) -> None:
    await store._aclear()
    assert scan(raw) == []
    await store.aclose()


@redis_available
async def test__acount(filled_store: RedisStore) -> None:
    assert await filled_store._acount() == 3
    await filled_store.aclose()


@redis_available
async def test__acontains_many(filled_store: RedisStore) -> None:
    assert await filled_store._acontains_many(["1", "4", "3", "1"]) == {"1", "3"}
    await filled_store.aclose()


@redis_available
@pytest.mark.parametrize(("batch_size", "sizes"), [(1, [1, 1, 1]), (2, [2, 1]), (10, [3])])
async def test__aiter_batches_sizes(
    filled_store: RedisStore, batch_size: int, sizes: list[int]
) -> None:
    assert [len(batch) async for batch in filled_store._aiter_batches(batch_size)] == sizes
    await filled_store.aclose()


@redis_available
async def test__aiter_batches_payloads(filled_store: RedisStore) -> None:
    assert [batch async for batch in filled_store._aiter_batches(10)] == [PAYLOADS]
    await filled_store.aclose()


@redis_available
@pytest.mark.parametrize("method", ["_aiter_batches", "_aiter_key_batches"])
async def test_async_iteration_empty_store(store: RedisStore, method: str) -> None:
    assert [batch async for batch in getattr(store, method)(2)] == []
    await store.aclose()


@redis_available
async def test_async_iteration_skips_keys_deleted_since_the_snapshot(
    filled_store: RedisStore,
) -> None:
    iterator = filled_store._aiter_batches(1)
    first = await anext(iterator)
    filled_store._clear()
    assert (len(first), [batch async for batch in iterator]) == (1, [])
    await filled_store.aclose()


@redis_available
@pytest.mark.parametrize("method", ["_aiter_batches", "_aiter_key_batches"])
async def test_async_iteration_does_not_yield_keys_written_after_the_snapshot(
    filled_store: RedisStore, method: str
) -> None:
    iterator = getattr(filled_store, method)(1)
    await anext(iterator)
    filled_store._put_many({"4": b"{}"})
    assert len([batch async for batch in iterator]) == 2
    await filled_store.aclose()


@redis_available
@pytest.mark.parametrize("method", ["_aiter_batches", "_aiter_key_batches"])
@pytest.mark.parametrize("batch_size", [1, 10])
async def test_async_iteration_closed_store(
    filled_store: RedisStore, method: str, batch_size: int
) -> None:
    iterator = getattr(filled_store, method)(batch_size)
    await anext(iterator)
    await filled_store.aclose()
    with pytest.raises(RuntimeError, match=r"is not open"):
        await anext(iterator)


@redis_available
async def test__afilter_candidates(filled_store: RedisStore) -> None:
    assert [batch async for batch in filled_store._afilter_candidates({"a": 1})] == [PAYLOADS]
    await filled_store.aclose()


@redis_available
async def test__aiter_key_batches(filled_store: RedisStore) -> None:
    keys = [key async for batch in filled_store._aiter_key_batches(2) for key in batch]
    assert sorted(keys) == ["1", "2", "3"]
    await filled_store.aclose()


@redis_available
async def test__asnapshot_keys(filled_store: RedisStore) -> None:
    assert sorted(await filled_store._asnapshot_keys()) == [b"1", b"2", b"3"]
    await filled_store.aclose()


@redis_available
async def test_async_calls_do_not_use_threads(
    store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "_run_in_thread", MagicMock(side_effect=AssertionError("thread")))
    await store.aset("1", {"a": 1}, on_conflict="merge")
    await store.aset("2", {})
    await store.acontains("1")
    await store.afilter()
    await store.acount()
    await store.adelete("1")
    await store.aclear()
    assert [key async for key in store.akeys()] == []
    await store._aclose()


# --- async client ---


@redis_available
async def test__async_client_is_reused_in_a_loop(store: RedisStore) -> None:
    assert await store._async_client() is await store._async_client()
    await store.aclose()


@redis_available
@pytest.mark.usefixtures("server")
async def test__async_client_closed_store() -> None:
    with pytest.raises(RuntimeError, match=r"RedisStore is not open"):
        await RedisStore()._async_client()


@redis_available
async def test__async_client_being_closed(store: RedisStore) -> None:
    entry = await store._async_client()
    entry.closing = True
    with pytest.raises(RuntimeError, match=r"it is being closed"):
        await store._async_client()
    entry.closing = False
    await store.aclose()


@redis_available
def test_each_event_loop_has_its_own_client(store: RedisStore) -> None:
    async def client() -> Any:
        return (await store._async_client()).client

    assert asyncio.run(client()) is not asyncio.run(client())


@redis_available
def test_use_in_two_event_loops(store: RedisStore) -> None:
    asyncio.run(store.aset("1", {}))
    asyncio.run(store.aset("2", {}))
    assert asyncio.run(store.acount()) == 2


@redis_available
def test_loop_shutdown_closes_the_client(server: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = fakeredis.FakeAsyncRedis(server=server)
    closed = []

    async def aclose() -> None:
        closed.append(True)

    monkeypatch.setattr(client, "aclose", aclose)
    monkeypatch.setattr(f"{MODULE}.aredis.Redis.from_url", lambda _url: client)
    with RedisStore() as store:
        asyncio.run(store.acount())
        assert (closed, store._aclients) == ([True], {})


@redis_available
async def test_close_with_an_open_async_client_raises(store: RedisStore) -> None:
    await store.aset("1", {})
    with pytest.raises(RuntimeError, match=r"call `await store.aclose\(\)`"):
        store.close()
    assert await store.aget("1") == {}
    await store.aclose()


@redis_available
@pytest.mark.usefixtures("server")
async def test_sync_context_manager_with_an_async_call_raises() -> None:
    store = RedisStore()
    with pytest.raises(RuntimeError, match=r"An async client of RedisStore is open"), store:
        await store.acount()
    await store.aclose()


@redis_available
def test_close_after_the_event_loop_shut_down(store: RedisStore) -> None:
    asyncio.run(store.acount())
    store.close()
    assert store.closed


@redis_available
def test_close_with_the_client_of_a_stopped_loop_raises(store: RedisStore) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.acount())
        with pytest.raises(RuntimeError, match=r"An async client of RedisStore is open"):
            store.close()
        loop.run_until_complete(store.aclose())
    finally:
        loop.close()
    assert store.closed


@redis_available
def test_aclose_with_the_client_of_another_loop_raises(store: RedisStore) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.acount())
        with pytest.raises(RuntimeError, match=r"An async client of RedisStore is open"):
            asyncio.run(store.aclose())
        assert not store.closed
        loop.run_until_complete(store.aclose())
    finally:
        loop.close()


@redis_available
async def test_aclose(store: RedisStore) -> None:
    await store.acount()
    await store.aclose()
    assert (store.closed, store._aclients) == (True, {})


@redis_available
async def test_aclose_without_async_call(store: RedisStore) -> None:
    await store.aclose()
    assert store.closed


@redis_available
async def test_aclose_twice(store: RedisStore) -> None:
    await store.acount()
    await asyncio.gather(store.aclose(), store.aclose())
    assert store.closed


@redis_available
async def test_aclose_then_reopen(store: RedisStore) -> None:
    await store.aset("1", {})
    await store.aclose()
    async with store:
        assert await store.aget("1") == {}


@redis_available
async def test_aclose_waits_for_the_calls_that_use_the_client(store: RedisStore) -> None:
    entry = await store._async_client()
    with entry:
        task = asyncio.ensure_future(store.aclose())
        await asyncio.sleep(0)
        waiting = not task.done() and not store.closed
    await task
    assert (waiting, store.closed) == (True, True)


@redis_available
async def test_concurrent_aclose_close_the_client_once(
    store: RedisStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await store._async_client()
    aclose = AsyncMock()
    monkeypatch.setattr(entry.client, "aclose", aclose)
    with entry:
        tasks = [asyncio.ensure_future(store.aclose()) for _ in range(2)]
        await asyncio.sleep(0)
    await asyncio.gather(*tasks)
    assert (aclose.await_count, store.closed) == (1, True)


@redis_available
async def test_aclose_cancelled_keeps_the_client_usable(store: RedisStore) -> None:
    with await store._async_client():
        task = asyncio.ensure_future(store.aclose())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError, match=r"^$"):
            await task
    assert await store.acount() == 0
    await store.aclose()


@redis_available
async def test__aclose_keeps_the_store_open(store: RedisStore) -> None:
    await store.acount()
    await store._aclose()
    assert (store.closed, store._aclients) == (False, {})


@redis_available
async def test__close_with_loop(store: RedisStore) -> None:
    client = AsyncMock()
    loop = asyncio.get_running_loop()
    store._aclients[loop] = MagicMock()
    guard = store._close_with_loop(client, loop)
    await anext(guard)
    await guard.aclose()
    assert (store._aclients, client.aclose.await_count) == ({}, 1)


@redis_available
def test__forget_closed_loops(store: RedisStore, caplog: pytest.LogCaptureFixture) -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    store._aclients[loop] = MagicMock()
    with caplog.at_level(logging.WARNING):
        store._forget_closed_loops()
    assert (store._aclients, len(caplog.messages)) == ({}, 1)


@redis_available
def test__forget_closed_loops_keeps_open_loops(store: RedisStore) -> None:
    loop = asyncio.new_event_loop()
    entry = MagicMock()
    store._aclients[loop] = entry
    try:
        store._forget_closed_loops()
        assert store._aclients == {loop: entry}
    finally:
        store._aclients.clear()
        loop.close()


@redis_available
def test_close_after_a_loop_closed_without_shutdown(store: RedisStore) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(store.acount())
    finally:
        loop.close()
    store.close()
    assert store.closed


# --- URI ---


@redis_available
def test_to_uri() -> None:
    uri = "redis://user:secret@localhost:6379/1"
    assert RedisStore(uri, namespace="app", codec=PickleCodec()).to_uri() == uri


@redis_available
@pytest.mark.parametrize("read_only", [True, False])
def test_from_uri(read_only: bool) -> None:
    store = RedisStore.from_uri(URL, read_only=read_only)
    assert (store.to_uri(), store.namespace, store.closed) == (URL, "persista", True)


@redis_available
def test_from_uri_passes_the_codec_and_the_namespace() -> None:
    codec = PickleCodec()
    store = RedisStore.from_uri(URL, codec=codec, namespace="app")
    assert (store._codec, store.namespace) == (codec, "app")


@redis_available
def test_from_uri_passes_the_connection_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from_url = MagicMock()
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", from_url)
    RedisStore.from_uri(URL, socket_timeout=5.0).open()
    from_url.assert_called_once_with(URL, socket_timeout=5.0)


# --- repr ---


@redis_available
@pytest.mark.parametrize("operation", [repr, str])
def test_repr_hides_the_credentials(operation: Callable[[Any], str]) -> None:
    secrets = ["admin", "s3cret", "other", "third"]
    store = RedisStore(
        f"redis://{secrets[0]}:{secrets[1]}@localhost:6379/0?password={secrets[2]}",
        password=secrets[3],
    )
    text = operation(store)
    assert not any(secret in text for secret in secrets)


@redis_available
def test_repr_runs_no_command(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    monkeypatch.setattr(f"{MODULE}.redis.Redis.from_url", lambda _url: client)
    with RedisStore() as store:
        client.reset_mock()
        repr(store)
        assert client.mock_calls == []


@redis_available
def test__get_repr_kwargs() -> None:
    store = RedisStore("redis://:secret@localhost:6379/0", socket_timeout=1.0)
    assert store._get_repr_kwargs() == {
        "url": "redis://localhost:6379/0",
        "namespace": "persista",
        "closed": True,
    }


@redis_available
@pytest.mark.usefixtures("server")
def test__get_repr_kwargs_codec_and_open() -> None:
    codec = PickleCodec()
    with RedisStore(codec=codec, namespace="app") as store:
        assert store._get_repr_kwargs() == {
            "url": URL,
            "namespace": "app",
            "closed": False,
            "codec": codec,
        }


# --- template helpers ---


@redis_available
def test__value_names() -> None:
    assert RedisStore(namespace="é")._value_names([b"1", b""]) == [
        "é:v:1".encode(),
        "é:v:".encode(),
    ]


@redis_available
def test__encode_rows() -> None:
    assert RedisStore()._encode_rows({"é": "{}", "2": b"x"}) == {"é".encode(): "{}", b"2": b"x"}


@redis_available
def test__encode_rows_surrogate() -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        RedisStore()._encode_rows({SURROGATE: "{}"})


@redis_available
def test__queue_put() -> None:
    pipe = MagicMock()
    RedisStore()._queue_put(pipe, {b"1": "{}", b"2": b"x"})
    assert pipe.mock_calls == [
        ("mset", ({b"persista:v:1": b"{}", b"persista:v:2": b"x"},), {}),
        ("sadd", (b"persista:keys", b"1", b"2"), {}),
    ]


@redis_available
def test__queue_put_empty() -> None:
    pipe = MagicMock()
    RedisStore()._queue_put(pipe, {})
    assert pipe.mock_calls == []


@redis_available
def test__queue_delete() -> None:
    pipe = MagicMock()
    RedisStore()._queue_delete(pipe, iter([b"1", b"2"]))
    assert pipe.mock_calls == [
        ("delete", (b"persista:v:1", b"persista:v:2"), {}),
        ("srem", (b"persista:keys", b"1", b"2"), {}),
    ]


#################################
#     Tests for _LoopClient     #
#################################


def test__loop_client_enter_gives_the_client() -> None:
    client = MagicMock()
    with _LoopClient(client, MagicMock()) as entered:
        assert entered is client


def test__loop_client_not_closing() -> None:
    assert not _LoopClient(MagicMock(), MagicMock()).closing


async def test__loop_client_wait_until_idle_without_call() -> None:
    entry = _LoopClient(MagicMock(), MagicMock())
    await asyncio.wait_for(entry.wait_until_idle(), timeout=1)
    assert entry._calls == 0


async def test__loop_client_wait_until_idle_waits_for_every_call() -> None:
    entry = _LoopClient(MagicMock(), MagicMock())
    entry.__enter__()
    entry.__enter__()
    task = asyncio.ensure_future(entry.wait_until_idle())
    await asyncio.sleep(0)
    entry.__exit__()
    await asyncio.sleep(0)
    waiting = not task.done()
    entry.__exit__()
    await asyncio.wait_for(task, timeout=1)
    assert waiting


async def test__loop_client_wait_until_idle_after_a_previous_idle_time() -> None:
    entry = _LoopClient(MagicMock(), MagicMock())
    with entry:
        pass
    entry.__enter__()
    task = asyncio.ensure_future(entry.wait_until_idle())
    await asyncio.sleep(0)
    waiting = not task.done()
    entry.__exit__()
    await asyncio.wait_for(task, timeout=1)
    assert waiting


def test__loop_client_exit_after_an_error() -> None:
    entry = _LoopClient(MagicMock(), MagicMock())
    entry.__enter__()
    entry.__exit__(ValueError, ValueError("failed"), None)
    assert entry._calls == 0


#################################
#     Tests for _encode_key     #
#################################


@pytest.mark.parametrize(("key", "encoded"), [("", b""), ("a", b"a"), ("é", "é".encode())])
def test__encode_key(key: str, encoded: bytes) -> None:
    assert _encode_key(key) == encoded


def test__encode_key_surrogate() -> None:
    with pytest.raises(ValueError, match=r"valid Unicode, but it has a lone surrogate"):
        _encode_key(SURROGATE)


##################################
#     Tests for _encode_keys     #
##################################


@pytest.mark.parametrize(
    ("keys", "encoded"), [([], []), (["a", "é", "a"], [b"a", "é".encode(), b"a"])]
)
def test__encode_keys(keys: list[str], encoded: list[bytes]) -> None:
    assert _encode_keys(keys) == encoded


def test__encode_keys_surrogate() -> None:
    with pytest.raises(ValueError, match=r"valid Unicode, but it has a lone surrogate"):
        _encode_keys(["a", SURROGATE])


#####################################
#     Tests for _encode_members     #
#####################################


@pytest.mark.parametrize(
    ("members", "expected"),
    [([], []), ([b"a", b"b"], [b"a", b"b"]), (["é"], ["é".encode()])],
)
def test__encode_members(members: list, expected: list[bytes]) -> None:
    assert _encode_members(members) == expected


##################################
#     Tests for _decode_keys     #
##################################


@pytest.mark.parametrize(("raw_keys", "keys"), [([], []), ([b"a", "é".encode()], ["a", "é"])])
def test__decode_keys(raw_keys: list[bytes], keys: list[str]) -> None:
    assert _decode_keys(raw_keys) == keys


##############################
#     Tests for _present     #
##############################


@pytest.mark.parametrize(
    ("keys", "values", "expected"),
    [
        pytest.param([], [], {}, id="empty"),
        pytest.param(["a", "b"], [b"1", b""], {"a": b"1", "b": b""}, id="present"),
        pytest.param(["a", "b"], [None, b"2"], {"b": b"2"}, id="missing"),
        pytest.param(["a", "a"], [b"1", b"1"], {"a": b"1"}, id="duplicates"),
    ],
)
def test__present(keys: list[str], values: list, expected: dict) -> None:
    assert _present(keys, values) == expected


def test__present_different_lengths() -> None:
    with pytest.raises(ValueError, match=r"zip\(\)"):
        _present(["a"], [])


################################
#     Tests for _check_url     #
################################


@pytest.mark.parametrize(
    "url",
    [
        URL,
        "rediss://user:secret@host:6380/1",
        "unix:///tmp/redis.sock?db=1",
        "redis://[::1]:6379",
    ],
)
def test__check_url(url: str) -> None:
    _check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("redis://:s3cret/x@host", id="slash_in_password"),
        pytest.param("redis://user:s3cret#x@host", id="hash_in_password"),
        pytest.param("redis://:s3cret@host:port", id="port"),
        pytest.param("redis://:s3cret@[::1", id="ipv6"),
    ],
)
def test__check_url_invalid(url: str) -> None:
    with pytest.raises(ValueError, match=r"Invalid Redis URL") as exc_info:
        _check_url(url)
    assert (exc_info.value.__suppress_context__, "s3cret" in str(exc_info.value)) == (True, False)


#################################
#     Tests for _redact_url     #
#################################


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (URL, URL),
        ("redis://localhost", "redis://localhost"),
        ("redis://:secret@localhost:6379/0", URL),
        ("redis://user:secret@localhost:6379/0", URL),
        ("redis://user@localhost:6379/0", URL),
        ("redis://:p@ss@localhost:6379/0", URL),
        ("redis://:p%40ss@localhost:6379/0", URL),
        ("rediss://u:secret@[::1]:6380/2", "rediss://[::1]:6380/2"),
        (
            "redis://localhost?password=secret&db=2&username=u&ssl_password=x",
            "redis://localhost?db=2",
        ),
        ("redis://localhost:6379/0#secret", URL),
        ("unix:///tmp/redis.sock?db=1&password=secret", "unix:///tmp/redis.sock?db=1"),
        ("unix://user:secret@/tmp/redis.sock", "unix:///tmp/redis.sock"),
        ("redis://:se/cret@localhost", "<hidden Redis URL>"),
        ("redis://:12/cret@localhost", "<hidden Redis URL>"),
        ("redis://:12?cret@localhost", "<hidden Redis URL>"),
        ("redis://:12#cret@localhost", "<hidden Redis URL>"),
        ("redis://:secret@[::1", "<hidden Redis URL>"),
        ("secret@localhost", "<hidden Redis URL>"),
        ("user:secret@localhost", "<hidden Redis URL>"),
        ("", "<hidden Redis URL>"),
    ],
)
def test__redact_url(url: str, expected: str) -> None:
    assert _redact_url(url) == expected
