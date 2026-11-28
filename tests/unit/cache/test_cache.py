from __future__ import annotations

import asyncio
import inspect
import math
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from persista.cache.cache import MISSING, Cache
from persista.cache.memoize import build_key_function
from persista.cache.ttl import DEFAULT
from persista.store.codec import PickleCodec
from persista.store.in_memory import InMemoryStore
from persista.store.null import NullStore

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

NOW = 1_000_000.0


@pytest.fixture
def cache() -> Generator[Cache]:
    with Cache() as cache:
        yield cache


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    values = [NOW]
    monkeypatch.setattr("persista.cache.cache.time.time", lambda: values[0])
    return values


#################################
#     Tests for constructor     #
#################################


def test_cache_default_store() -> None:
    assert isinstance(Cache()._store, InMemoryStore)


def test_cache_default_store_uses_pickle_codec() -> None:
    assert isinstance(Cache()._store._codec, PickleCodec)


def test_cache_custom_store() -> None:
    store = InMemoryStore()
    assert Cache(store)._store is store


def test_cache_default_ttl_is_none() -> None:
    assert Cache().default_ttl is None


@pytest.mark.parametrize("ttl", [None, 0, 60, math.inf])
def test_cache_default_ttl(ttl: float | None) -> None:
    assert Cache(default_ttl=ttl).default_ttl == ttl


@pytest.mark.parametrize("ttl", [-1, math.nan])
def test_cache_default_ttl_invalid(ttl: float) -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be None, 0 or positive"):
        Cache(default_ttl=ttl)


def test_cache_default_ttl_is_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional arguments"):
        Cache(InMemoryStore(), 60)


###################################
#     Tests for default store     #
###################################


@pytest.mark.parametrize(
    "value",
    [
        pytest.param((1, 2), id="tuple"),
        pytest.param({1, 2}, id="set"),
        pytest.param(b"data", id="bytes"),
        pytest.param({1: "int", "1": "str"}, id="non_str_keys"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(complex(1, 2), id="object"),
    ],
)
def test_default_store_keeps_type_of_value(cache: Cache, value: object) -> None:
    cache.set("key", value)
    result = cache.get("key")
    assert (type(result), result) == (type(value), value)


def test_default_store_returns_a_copy(cache: Cache) -> None:
    cache.set("key", [1])
    cache.get("key").append(2)
    assert cache.get("key") == [1]


def test_json_store_returns_tuple_as_list() -> None:
    with Cache(InMemoryStore()) as cache:
        cache.set("key", (1, 2))
        assert cache.get("key") == [1, 2]


def test_null_store_always_misses() -> None:
    with Cache(NullStore()) as cache:
        cache.set("key", 1)
        assert cache.get("key", MISSING) is MISSING


##################################
#     Tests for open / close     #
##################################


def test_closed_before_open() -> None:
    assert Cache().closed


def test_open() -> None:
    cache = Cache()
    cache.open()
    assert not cache.closed
    cache.close()


def test_close() -> None:
    cache = Cache()
    cache.open()
    cache.close()
    assert cache.closed


async def test_aopen() -> None:
    cache = Cache()
    await cache.aopen()
    assert not cache.closed
    await cache.aclose()


async def test_aclose() -> None:
    cache = Cache()
    await cache.aopen()
    await cache.aclose()
    assert cache.closed


def test_context_manager() -> None:
    with Cache() as cache:
        assert not cache.closed
    assert cache.closed


async def test_async_context_manager() -> None:
    async with Cache() as cache:
        assert not cache.closed
    assert cache.closed


SYNC_CALLS = [
    pytest.param(lambda c: c.get("a"), id="get"),
    pytest.param(lambda c: c.get_many([]), id="get_many"),
    pytest.param(lambda c: c.contains("a"), id="contains"),
    pytest.param(lambda c: c.set("a", 1), id="set"),
    pytest.param(lambda c: c.set("a", 1, ttl=0), id="set-ttl-0"),
    pytest.param(lambda c: c.set_many({}), id="set_many"),
    pytest.param(lambda c: c.set_many({}, ttl=0), id="set_many-ttl-0"),
    pytest.param(lambda c: c.delete("a"), id="delete"),
    pytest.param(lambda c: c.delete_many([]), id="delete_many"),
    pytest.param(lambda c: c.clear(), id="clear"),
    pytest.param(lambda c: c.get_or_compute("a", int), id="get_or_compute"),
]

ASYNC_CALLS = [
    pytest.param(lambda c: c.aget("a"), id="aget"),
    pytest.param(lambda c: c.aget_many([]), id="aget_many"),
    pytest.param(lambda c: c.acontains("a"), id="acontains"),
    pytest.param(lambda c: c.aset("a", 1), id="aset"),
    pytest.param(lambda c: c.aset("a", 1, ttl=0), id="aset-ttl-0"),
    pytest.param(lambda c: c.aset_many({}), id="aset_many"),
    pytest.param(lambda c: c.aset_many({}, ttl=0), id="aset_many-ttl-0"),
    pytest.param(lambda c: c.adelete("a"), id="adelete"),
    pytest.param(lambda c: c.adelete_many([]), id="adelete_many"),
    pytest.param(lambda c: c.aclear(), id="aclear"),
    pytest.param(lambda c: c.aget_or_compute("a", int), id="aget_or_compute"),
]


@pytest.mark.parametrize("call", SYNC_CALLS)
def test_closed_cache_raises(call: Callable[[Cache], object]) -> None:
    with pytest.raises(RuntimeError, match=r"is not open"):
        call(Cache())


@pytest.mark.parametrize("call", ASYNC_CALLS)
async def test_closed_cache_raises_async(call: Callable[[Cache], Any]) -> None:
    with pytest.raises(RuntimeError, match=r"is not open"):
        await call(Cache())


###########################
#     Tests for get       #
###########################


def test_get_missing(cache: Cache) -> None:
    assert cache.get("missing") is None


def test_get_missing_default(cache: Cache) -> None:
    assert cache.get("missing", "fallback") == "fallback"


def test_get_hit_ignores_default(cache: Cache) -> None:
    cache.set("key", "value")
    assert cache.get("key", "fallback") == "value"


@pytest.mark.parametrize("value", [None, 0, False, "", []])
def test_get_falsy_value(cache: Cache, value: object) -> None:
    cache.set("key", value)
    assert cache.get("key", MISSING) == value


def test_get_not_yet_expired(cache: Cache, clock: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    clock[0] += 9
    assert cache.get("key") == "value"


def test_get_exactly_at_expiry_is_not_expired(cache: Cache, clock: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    clock[0] += 10
    assert cache.get("key") == "value"


def test_get_expired(cache: Cache, clock: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    clock[0] += 11
    assert cache.get("key", MISSING) is MISSING


def test_get_expired_deletes_entry(cache: Cache, clock: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    clock[0] += 11
    cache.get("key")
    assert cache._store.count() == 0


def test_expired_entry_stays_in_store_until_read(cache: Cache, clock: list[float]) -> None:
    cache.set_many({"a": 1, "b": 2}, ttl=10)
    clock[0] += 11
    cache.get("a")
    assert list(cache._store.keys()) == ["b"]


def test_get_key_not_str(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str"):
        cache.get(1)


async def test_aget(cache: Cache) -> None:
    cache.set("key", (1, {2}))
    assert await cache.aget("key") == (1, {2})


async def test_aget_missing_default(cache: Cache) -> None:
    assert await cache.aget("missing", "fallback") == "fallback"


async def test_aget_cached_none(cache: Cache) -> None:
    await cache.aset("key", None)
    assert await cache.aget("key", MISSING) is None


async def test_aget_expired(cache: Cache, clock: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    clock[0] += 11
    assert await cache.aget("key", MISSING) is MISSING


async def test_aget_expired_deletes_entry(cache: Cache, clock: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    clock[0] += 11
    await cache.aget("key")
    assert cache._store.count() == 0


################################
#     Tests for get_many       #
################################


def test_get_many_returns_hits_only(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": None})
    assert cache.get_many(["a", "missing", "b"]) == {"a": 1, "b": None}


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param([], {}, id="empty"),
        pytest.param(["missing"], {}, id="all-missing"),
        pytest.param(["a", "a"], {"a": 1}, id="duplicates"),
    ],
)
def test_get_many(cache: Cache, keys: list[str], expected: dict[str, int]) -> None:
    cache.set("a", 1)
    assert cache.get_many(keys) == expected


def test_get_many_order_of_keys(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    assert list(cache.get_many(["b", "a"])) == ["b", "a"]


def test_get_many_one_shot_iterable(cache: Cache) -> None:
    cache.set("a", 1)
    assert cache.get_many(iter(["a"])) == {"a": 1}


def test_get_many_does_not_mutate_keys(cache: Cache) -> None:
    keys = ["a", "b"]
    cache.get_many(keys)
    assert keys == ["a", "b"]


def test_get_many_expired(cache: Cache, clock: list[float]) -> None:
    cache.set("a", 1, ttl=10)
    cache.set("b", 2)
    clock[0] += 11
    assert cache.get_many(["a", "b"]) == {"b": 2}


def test_get_many_expired_deleted(cache: Cache, clock: list[float]) -> None:
    cache.set("a", 1, ttl=10)
    clock[0] += 11
    cache.get_many(["a"])
    assert cache._store.count() == 0


def test_get_many_str(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"keys must be a list of keys"):
        cache.get_many("abc")


async def test_aget_many_returns_hits_only(cache: Cache) -> None:
    await cache.aset_many({"a": 1, "b": None})
    assert await cache.aget_many(["a", "missing", "b"]) == {"a": 1, "b": None}


async def test_aget_many_empty(cache: Cache) -> None:
    assert await cache.aget_many([]) == {}


async def test_aget_many_expired(cache: Cache, clock: list[float]) -> None:
    await cache.aset("a", 1, ttl=10)
    clock[0] += 11
    assert await cache.aget_many(["a"]) == {}


async def test_aget_many_expired_deleted(cache: Cache, clock: list[float]) -> None:
    await cache.aset("a", 1, ttl=10)
    clock[0] += 11
    await cache.aget_many(["a"])
    assert cache._store.count() == 0


async def test_aget_many_str(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"keys must be a list of keys"):
        await cache.aget_many("abc")


################################
#     Tests for contains       #
################################


@pytest.mark.parametrize(("key", "expected"), [("a", True), ("none", True), ("b", False)])
def test_contains(cache: Cache, key: str, expected: bool) -> None:
    cache.set_many({"a": 1, "none": None})
    assert cache.contains(key) is expected


def test_contains_expired(cache: Cache, clock: list[float]) -> None:
    cache.set("a", 1, ttl=10)
    clock[0] += 11
    assert not cache.contains("a")


def test_contains_expired_deletes_entry(cache: Cache, clock: list[float]) -> None:
    cache.set("a", 1, ttl=10)
    clock[0] += 11
    cache.contains("a")
    assert cache._store.count() == 0


@pytest.mark.parametrize(("key", "expected"), [("a", True), ("none", True), ("b", False)])
async def test_acontains(cache: Cache, key: str, expected: bool) -> None:
    await cache.aset_many({"a": 1, "none": None})
    assert await cache.acontains(key) is expected


async def test_acontains_expired(cache: Cache, clock: list[float]) -> None:
    await cache.aset("a", 1, ttl=10)
    clock[0] += 11
    assert not await cache.acontains("a")


################################
#     Tests for set            #
################################


def test_set_overwrites(cache: Cache) -> None:
    cache.set("key", "value")
    cache.set("key", "other")
    assert cache.get("key") == "other"


@pytest.mark.parametrize("ttl", [None, math.inf])
def test_set_never_expires(clock: list[float], ttl: float | None) -> None:
    with Cache(default_ttl=1) as cache:
        cache.set("key", "value", ttl=ttl)
        clock[0] += 1e12
        assert cache.get("key") == "value"


def test_set_infinite_ttl_json_store() -> None:
    with Cache(InMemoryStore()) as cache:
        cache.set("key", "value", ttl=math.inf)
        assert cache.get("key") == "value"


def test_set_ttl_zero_not_stored(cache: Cache) -> None:
    cache.set("key", "value", ttl=0)
    assert cache._store.count() == 0


def test_set_ttl_zero_deletes_entry(cache: Cache) -> None:
    cache.set("key", "value", ttl=60)
    cache.set("key", "other", ttl=0)
    assert cache._store.count() == 0


@pytest.mark.parametrize("ttl", [-1, math.nan])
def test_set_ttl_invalid(cache: Cache, ttl: float) -> None:
    cache.set("key", "old")
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cache.set("key", "new", ttl=ttl)
    assert cache.get("key") == "old"


def test_set_default_ttl(clock: list[float]) -> None:
    with Cache(default_ttl=10) as cache:
        cache.set("key", "value")
        clock[0] += 11
        assert cache.get("key") is None


def test_set_default_ttl_zero() -> None:
    with Cache(default_ttl=0) as cache:
        cache.set("key", "value")
        assert cache._store.count() == 0


def test_set_ttl_overrides_default_ttl(clock: list[float]) -> None:
    with Cache(default_ttl=10) as cache:
        cache.set("key", "value", ttl=100)
        clock[0] += 11
        assert cache.get("key") == "value"


def test_set_ttl_is_keyword_only(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"positional arguments"):
        cache.set("key", "value", 10)


async def test_aset(cache: Cache) -> None:
    await cache.aset("key", "value")
    assert cache.get("key") == "value"


async def test_aset_ttl(cache: Cache, clock: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    clock[0] += 11
    assert await cache.aget("key") is None


async def test_aset_ttl_zero_deletes_entry(cache: Cache) -> None:
    await cache.aset("key", "value")
    await cache.aset("key", "other", ttl=0)
    assert cache._store.count() == 0


async def test_aset_ttl_invalid(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        await cache.aset("key", "value", ttl=math.nan)
    assert cache._store.count() == 0


################################
#     Tests for set_many       #
################################


def test_set_many(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    assert cache.get_many(["a", "b"]) == {"a": 1, "b": 2}


def test_set_many_empty(cache: Cache) -> None:
    cache.set_many({})
    assert cache._store.count() == 0


def test_set_many_does_not_mutate_items(cache: Cache) -> None:
    items = {"a": [1]}
    cache.set_many(items)
    assert items == {"a": [1]}


def test_set_many_ttl(cache: Cache, clock: list[float]) -> None:
    cache.set_many({"a": 1, "b": 2}, ttl=10)
    clock[0] += 11
    assert cache.get_many(["a", "b"]) == {}


def test_set_many_ttl_zero_deletes_entries(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    cache.set_many({"a": 3, "b": 4}, ttl=0)
    assert cache._store.count() == 0


@pytest.mark.parametrize("ttl", [-1, math.nan])
def test_set_many_ttl_invalid(cache: Cache, ttl: float) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cache.set_many({"a": 1}, ttl=ttl)
    assert cache._store.count() == 0


def test_set_many_unencodable_value_writes_nothing(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"cannot pickle"):
        cache.set_many({"a": 1, "b": memoryview(b"")})
    assert cache._store.count() == 0


async def test_aset_many(cache: Cache) -> None:
    await cache.aset_many({"a": 1, "b": 2})
    assert cache.get_many(["a", "b"]) == {"a": 1, "b": 2}


async def test_aset_many_ttl_zero_deletes_entries(cache: Cache) -> None:
    await cache.aset_many({"a": 1})
    await cache.aset_many({"a": 2}, ttl=0)
    assert cache._store.count() == 0


async def test_aset_many_ttl_invalid(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        await cache.aset_many({"a": 1}, ttl=-1)
    assert cache._store.count() == 0


#####################################
#     Tests for delete / clear      #
#####################################


def test_delete(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    cache.delete("a")
    assert list(cache._store.keys()) == ["b"]


def test_delete_missing(cache: Cache) -> None:
    cache.delete("missing")
    assert cache._store.count() == 0


async def test_adelete(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    await cache.adelete("a")
    assert list(cache._store.keys()) == ["b"]


@pytest.mark.parametrize(
    ("keys", "remaining"),
    [
        pytest.param([], ["a", "b"], id="empty"),
        pytest.param(["a", "b"], [], id="existing"),
        pytest.param(["a", "missing", "a"], ["b"], id="mixed"),
    ],
)
def test_delete_many(cache: Cache, keys: list[str], remaining: list[str]) -> None:
    cache.set_many({"a": 1, "b": 2})
    cache.delete_many(keys)
    assert list(cache._store.keys()) == remaining


async def test_adelete_many(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    await cache.adelete_many(["a"])
    assert list(cache._store.keys()) == ["b"]


def test_clear(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    cache.clear()
    assert cache._store.count() == 0


async def test_aclear(cache: Cache) -> None:
    cache.set_many({"a": 1, "b": 2})
    await cache.aclear()
    assert cache._store.count() == 0


######################################
#     Tests for get_or_compute       #
######################################


def test_get_or_compute_miss(cache: Cache) -> None:
    assert cache.get_or_compute("key", lambda: 8) == 8


def test_get_or_compute_stores_value(cache: Cache) -> None:
    cache.get_or_compute("key", lambda: 8)
    assert cache.get("key") == 8


@pytest.mark.parametrize("value", [8, None])
def test_get_or_compute_hit(cache: Cache, value: int | None) -> None:
    cache.set("key", value)
    calls = []
    assert (cache.get_or_compute("key", lambda: calls.append(1)), calls) == (value, [])


def test_get_or_compute_ttl(cache: Cache, clock: list[float]) -> None:
    cache.get_or_compute("key", lambda: 1, ttl=10)
    clock[0] += 11
    assert cache.get_or_compute("key", lambda: 2) == 2


def test_get_or_compute_ttl_zero_not_stored(cache: Cache) -> None:
    cache.get_or_compute("key", lambda: 1, ttl=0)
    assert cache._store.count() == 0


def test_get_or_compute_default_ttl(clock: list[float]) -> None:
    with Cache(default_ttl=10) as cache:
        cache.get_or_compute("key", lambda: 1)
        clock[0] += 11
        assert not cache.contains("key")


@pytest.mark.parametrize("ttl", [-1, math.nan])
def test_get_or_compute_ttl_invalid_does_not_call_fn(cache: Cache, ttl: float) -> None:
    calls = []
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cache.get_or_compute("key", lambda: calls.append(1), ttl=ttl)
    assert calls == []


def test_get_or_compute_ttl_invalid_on_hit(cache: Cache) -> None:
    cache.set("key", 1)
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cache.get_or_compute("key", lambda: 2, ttl=-1)


def test_get_or_compute_fn_error(cache: Cache) -> None:
    def compute() -> None:
        msg = "cannot compute"
        raise LookupError(msg)

    with pytest.raises(LookupError, match=r"cannot compute"):
        cache.get_or_compute("key", compute)
    assert cache._store.count() == 0


async def test_aget_or_compute_sync_fn(cache: Cache) -> None:
    assert await cache.aget_or_compute("key", lambda: 8) == 8


async def test_aget_or_compute_async_fn(cache: Cache) -> None:
    async def compute() -> int:
        return 8

    assert await cache.aget_or_compute("key", compute) == 8


async def test_aget_or_compute_stores_awaited_value(cache: Cache) -> None:
    await cache.aget_or_compute("key", lambda: asyncio.sleep(0, result=8))
    assert cache.get("key") == 8


async def test_aget_or_compute_hit(cache: Cache) -> None:
    cache.set("key", None)
    calls = []
    result = await cache.aget_or_compute("key", lambda: calls.append(1))
    assert (result, calls) == (None, [])


async def test_aget_or_compute_ttl_zero_not_stored(cache: Cache) -> None:
    await cache.aget_or_compute("key", lambda: 1, ttl=0)
    assert cache._store.count() == 0


async def test_aget_or_compute_ttl_invalid_does_not_call_fn(cache: Cache) -> None:
    calls = []
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        await cache.aget_or_compute("key", lambda: calls.append(1), ttl=math.nan)
    assert calls == []


###############################
#     Tests for memoize       #
###############################


def test_memoize(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def square(x: int) -> int:
        calls.append(x)
        return x * x

    assert (square(4), square(4), square(3), calls) == (16, 16, 9, [4, 3])


async def test_memoize_async(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    async def square(x: int) -> int:
        calls.append(x)
        return x * x

    results = [await square(4), await square(4), await square(3)]
    assert (results, calls) == ([16, 16, 9], [4, 3])


def test_memoize_same_call_written_differently(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def func(a: int, b: int = 2) -> int:
        calls.append(a)
        return a + b

    func(1)
    func(a=1)
    func(1, 2)
    func(b=2, a=1)
    assert calls == [1]


async def test_memoize_same_call_written_differently_async(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    async def func(a: int) -> int:
        calls.append(a)
        return a

    await func(1)
    await func(a=1)
    assert calls == [1]


def test_memoize_list_and_tuple_not_shared(cache: Cache) -> None:
    @cache.memoize()
    def kind(items: object) -> str:
        return type(items).__name__

    kind([1, 2])
    assert kind((1, 2)) == "tuple"


async def test_memoize_list_and_tuple_not_shared_async(cache: Cache) -> None:
    @cache.memoize()
    async def kind(items: object) -> str:
        return type(items).__name__

    await kind([1, 2])
    assert await kind((1, 2)) == "tuple"


def test_memoize_equal_argument_of_another_type_raises(cache: Cache) -> None:
    @cache.memoize()
    def identity(x: object) -> object:
        return x

    identity(1)
    with pytest.raises(TypeError, match=r"Cannot encode an object of type decimal\.Decimal"):
        identity(Decimal(1))


def test_memoize_set_argument(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def size(items: set[int]) -> int:
        calls.append(1)
        return len(items)

    size({0, 8})
    size({8, 0})
    assert calls == [1]


def test_memoize_keeps_type_of_result_on_hit(cache: Cache) -> None:
    @cache.memoize()
    def pair() -> tuple[int, int]:
        return (1, 2)

    pair()
    assert pair() == (1, 2)


@pytest.mark.parametrize("ttl", [None, 100])
def test_memoize_ttl(clock: list[float], ttl: float | None) -> None:
    calls = []
    with Cache(default_ttl=1) as cache:
        func = cache.memoize(ttl=ttl)(lambda: calls.append(1))
        func()
        clock[0] += 11
        func()
    assert calls == [1]


def test_memoize_ttl_expires(cache: Cache, clock: list[float]) -> None:
    calls = []
    func = cache.memoize(ttl=10)(lambda: calls.append(1))
    func()
    clock[0] += 11
    func()
    assert calls == [1, 1]


async def test_memoize_default_ttl_async(clock: list[float]) -> None:
    calls = []
    async with Cache(default_ttl=10) as cache:

        @cache.memoize()
        async def func() -> None:
            calls.append(1)

        await func()
        clock[0] += 11
        await func()
    assert calls == [1, 1]


def test_memoize_ignore(cache: Cache) -> None:
    calls = []

    @cache.memoize(ignore=("client",))
    def func(x: int, client: object) -> int:
        del client
        calls.append(x)
        return x

    func(1, object())
    func(1, client=object())
    assert calls == [1]


def test_memoize_key(cache: Cache) -> None:
    @cache.memoize(key=lambda x: f"square:{x}")
    def square(x: int) -> int:
        return x * x

    square(4)
    assert cache.get("square:4") == 16


async def test_memoize_key_async(cache: Cache) -> None:
    @cache.memoize(key=lambda x: f"square:{x}")
    async def square(x: int) -> int:
        return x * x

    await square(4)
    assert cache.get("square:4") == 16


def test_memoize_key_not_str(cache: Cache) -> None:
    func = cache.memoize(key=lambda: 1)(lambda: 2)
    with pytest.raises(TypeError, match=r"A key must be a str"):
        func()


def test_memoize_method_without_ignore_or_key(cache: Cache) -> None:
    class Loader:
        @cache.memoize()
        def load(self, x: int) -> int:
            return x

    with pytest.raises(TypeError, match=r"Cannot compute the cache key of a call of .*load"):
        Loader().load(1)


def test_memoize_method_ignore_self(cache: Cache) -> None:
    calls = []

    class Loader:
        @cache.memoize(ignore=("self",))
        def load(self, x: int) -> int:
            calls.append(x)
            return x

    Loader().load(1)
    Loader().load(1)
    assert calls == [1]


def test_memoize_method_key(cache: Cache) -> None:
    class Loader:
        def __init__(self, name: str) -> None:
            self.name = name

        @cache.memoize(key=lambda self, x: f"{self.name}:{x}")
        def load(self, x: int) -> str:
            return f"{self.name}-{x}"

    Loader("a").load(1)
    assert Loader("b").load(1) == "b-1"


def test_memoize_argument_not_encodable_does_not_call_function(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def func(x: object) -> None:
        calls.append(x)

    with pytest.raises(TypeError, match=r"Cannot compute the cache key"):
        func(object())
    assert calls == []


def test_memoize_binding_error(cache: Cache) -> None:
    func = cache.memoize()(lambda x: x)
    with pytest.raises(TypeError, match=r"missing a required argument"):
        func()


def test_memoize_same_qualname_different_modules(cache: Cache) -> None:
    def make_func(module: str) -> Callable[[], str]:
        def load() -> str:
            return module

        load.__module__ = module
        return cache.memoize()(load)

    make_func("first")()
    assert make_func("second")() == "second"


def test_memoize_same_qualname_shares_entries(cache: Cache) -> None:
    def make_func(value: int) -> Callable[[], int]:
        return cache.memoize()(lambda: value)

    make_func(1)()
    assert make_func(2)() == 1


def test_memoize_sync_and_key_function_agree(cache: Cache) -> None:
    def double(x: int) -> int:
        return 2 * x

    cache.set(build_key_function(double)((1,), {}), 100)
    assert cache.memoize()(double)(1) == 100


def test_memoize_preserves_metadata(cache: Cache) -> None:
    def func() -> None:
        pass

    func.__doc__ = "Do nothing."
    wrapper = cache.memoize()(func)
    assert (wrapper.__name__, wrapper.__doc__) == ("func", "Do nothing.")


async def test_memoize_preserves_coroutine_function(cache: Cache) -> None:
    @cache.memoize()
    async def func() -> None:
        pass

    assert inspect.iscoroutinefunction(func)


def test_memoize_two_caches_do_not_share_entries() -> None:
    calls = []

    def func() -> None:
        calls.append(1)

    with Cache() as first, Cache() as second:
        first.memoize()(func)()
        second.memoize()(func)()
    assert calls == [1, 1]


def test_memoize_closed_cache_raises() -> None:
    func = Cache().memoize()(lambda: 1)
    with pytest.raises(RuntimeError, match=r"is not open"):
        func()


@pytest.mark.parametrize("ttl", [-1, math.nan])
def test_memoize_ttl_invalid(cache: Cache, ttl: float) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cache.memoize(ttl=ttl)


def test_memoize_options_are_keyword_only(cache: Cache) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        cache.memoize(60)


##################################
#     Tests for _resolve_ttl     #
##################################


def test_resolve_ttl_default() -> None:
    assert Cache(default_ttl=10)._resolve_ttl(DEFAULT) == 10


@pytest.mark.parametrize("ttl", [None, 0, 5])
def test_resolve_ttl_explicit(ttl: float | None) -> None:
    assert Cache(default_ttl=10)._resolve_ttl(ttl) == ttl


def test_resolve_ttl_invalid() -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive, got -1"):
        Cache()._resolve_ttl(-1)


###################################
#     Tests for _make_entries     #
###################################


@pytest.mark.parametrize(
    ("ttl", "expires_at"),
    [
        pytest.param(None, None, id="none"),
        pytest.param(math.inf, None, id="infinity"),
        pytest.param(10, 1_000_010.0, id="positive"),
    ],
)
def test_make_entries(clock: list[float], ttl: float | None, expires_at: float | None) -> None:
    del clock
    assert Cache._make_entries({"a": 1, "b": 2}, ttl) == {
        "a": {"value": 1, "expires_at": expires_at},
        "b": {"value": 2, "expires_at": expires_at},
    }


def test_make_entries_empty() -> None:
    assert Cache._make_entries({}, 10) == {}


#################################
#     Tests for _is_expired     #
#################################


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [(None, False), (NOW - 1, True), (NOW, False), (NOW + 1, False)],
)
def test_is_expired(expires_at: float | None, expected: bool) -> None:
    assert Cache._is_expired({"value": 1, "expires_at": expires_at}, NOW) is expected


####################################
#     Tests for _split_entries     #
####################################


def test_split_entries(clock: list[float]) -> None:
    del clock
    entries = [
        {"value": 1, "expires_at": None},
        None,
        {"value": 3, "expires_at": NOW - 1},
    ]
    assert Cache()._split_entries(["a", "b", "c"], entries) == ({"a": 1}, ["c"])


def test_split_entries_empty() -> None:
    assert Cache()._split_entries([], []) == ({}, [])


########################################
#     Tests for _get_repr_kwargs       #
########################################


def test_get_repr_kwargs() -> None:
    store = InMemoryStore()
    assert Cache(store, default_ttl=5)._get_repr_kwargs() == {"store": store, "default_ttl": 5}


@pytest.mark.parametrize("func", [repr, str])
def test_repr_and_str(cache: Cache, func: Callable[[object], str]) -> None:
    assert func(cache).startswith("Cache(")


@pytest.mark.parametrize("func", [repr, str])
def test_repr_and_str_closed(func: Callable[[object], str]) -> None:
    assert func(Cache()).startswith("Cache(")
