from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from persista.cache.cache import Cache
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine


@pytest.fixture
def cache() -> Cache:
    return Cache()


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.cache.time.time", lambda: clock[0])
    return clock


# --- constructor ---


def test_init_default_store() -> None:
    cache = Cache()
    assert isinstance(cache._store, InMemoryStore)


def test_init_custom_store() -> None:
    store = InMemoryStore()
    cache = Cache(store=store)
    assert cache._store is store


def test_init_default_ttl_is_none() -> None:
    assert Cache().default_ttl is None


def test_init_custom_default_ttl() -> None:
    assert Cache(default_ttl=60).default_ttl == 60


def test_init_default_ttl_negative() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be non-negative, got -1"):
        Cache(default_ttl=-1)


# --- get/set ---


def test_get_missing_key(cache: Cache) -> None:
    assert cache.get("missing") is None


def test_set_then_get(cache: Cache) -> None:
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_set_overwrites(cache: Cache) -> None:
    cache.set("key", "value")
    cache.set("key", "other")
    assert cache.get("key") == "other"


def test_set_ttl_none_never_expires(cache: Cache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=None)
    fake_time[0] += 10_000
    assert cache.get("key") == "value"


def test_set_ttl_zero_not_stored(cache: Cache) -> None:
    cache.set("key", "value", ttl=0)
    assert cache.get("key") is None


def test_set_ttl_zero_evicts_existing_entry(cache: Cache) -> None:
    cache.set("key", "value", ttl=60)
    cache.set("key", "other", ttl=0)
    assert cache.get("key") is None


def test_set_ttl_positive_expires(cache: Cache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    assert cache.get("key") == "value"
    fake_time[0] += 11
    assert cache.get("key") is None


def test_set_ttl_negative_raises(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        cache.set("key", "value", ttl=-1)


def test_set_uses_default_ttl_when_not_given(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    cache.set("key", "value")
    fake_time[0] += 11
    assert cache.get("key") is None


def test_default_ttl_none_means_forever_by_default(cache: Cache, fake_time: list[float]) -> None:
    cache.set("key", "value")
    fake_time[0] += 10_000
    assert cache.get("key") == "value"


def test_get_cached_none_is_hit_by_default(cache: Cache) -> None:
    cache.set("key", None, ttl=None)
    assert cache.get("key") is None


def test_get_cached_none_is_miss_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    cache.set("key", None, ttl=None)
    hit, value = cache._get("key")
    assert hit is False
    assert value is None


# --- contains ---


def test_contains_missing_key(cache: Cache) -> None:
    assert cache.contains("missing") is False


def test_contains_existing_key(cache: Cache) -> None:
    cache.set("key", "value")
    assert cache.contains("key") is True


def test_contains_expired_key(cache: Cache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    assert cache.contains("key") is False


# --- get_many ---


def test_get_many_empty_keys_returns_empty_dict(cache: Cache) -> None:
    assert cache.get_many([]) == {}


def test_get_many_all_missing(cache: Cache) -> None:
    assert cache.get_many(["a", "b"]) == {}


def test_get_many_mixed_hits_and_misses(cache: Cache) -> None:
    cache.set("a", "1")
    cache.set("b", "2")
    assert cache.get_many(["a", "b", "missing"]) == {"a": "1", "b": "2"}


def test_get_many_expired_key_omitted(cache: Cache, fake_time: list[float]) -> None:
    cache.set("a", "1", ttl=10)
    cache.set("b", "2", ttl=None)
    fake_time[0] += 11
    assert cache.get_many(["a", "b"]) == {"b": "2"}


def test_get_many_expired_key_evicted_as_side_effect(cache: Cache, fake_time: list[float]) -> None:
    cache.set("a", "1", ttl=10)
    fake_time[0] += 11
    cache.get_many(["a"])
    assert cache.contains("a") is False


def test_get_many_cached_none_is_hit_by_default(cache: Cache) -> None:
    cache.set("a", None, ttl=None)
    assert cache.get_many(["a"]) == {"a": None}


def test_get_many_cached_none_is_omitted_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    cache.set("a", None, ttl=None)
    cache.set("b", "2")
    assert cache.get_many(["a", "b"]) == {"b": "2"}


# --- contains_many ---


def test_contains_many_empty_keys_returns_empty_list(cache: Cache) -> None:
    assert cache.contains_many([]) == []


def test_contains_many_all_missing(cache: Cache) -> None:
    assert cache.contains_many(["a", "b"]) == [False, False]


def test_contains_many_mixed_hits_and_misses(cache: Cache) -> None:
    cache.set("a", "1")
    cache.set("b", "2")
    assert cache.contains_many(["a", "b", "missing"]) == [True, True, False]


def test_contains_many_expired_key_omitted(cache: Cache, fake_time: list[float]) -> None:
    cache.set("a", "1", ttl=10)
    cache.set("b", "2", ttl=None)
    fake_time[0] += 11
    assert cache.contains_many(["a", "b"]) == [False, True]


def test_contains_many_expired_key_evicted_as_side_effect(
    cache: Cache, fake_time: list[float]
) -> None:
    cache.set("a", "1", ttl=10)
    fake_time[0] += 11
    cache.contains_many(["a"])
    assert cache.contains("a") is False


def test_contains_many_cached_none_is_hit_by_default(cache: Cache) -> None:
    cache.set("a", None, ttl=None)
    assert cache.contains_many(["a"]) == [True]


def test_contains_many_cached_none_is_omitted_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    cache.set("a", None, ttl=None)
    cache.set("b", "2")
    assert cache.contains_many(["a", "b"]) == [False, True]


# --- set_many ---


def test_set_many_empty_items_noop(cache: Cache) -> None:
    cache.set_many({})
    assert cache.get_many(["a"]) == {}


def test_set_many_then_get_many(cache: Cache) -> None:
    cache.set_many({"a": "1", "b": "2"})
    assert cache.get_many(["a", "b"]) == {"a": "1", "b": "2"}


def test_set_many_overwrites(cache: Cache) -> None:
    cache.set("a", "1")
    cache.set_many({"a": "2"})
    assert cache.get("a") == "2"


def test_set_many_ttl_none_never_expires(cache: Cache, fake_time: list[float]) -> None:
    cache.set_many({"a": "1"}, ttl=None)
    fake_time[0] += 10_000
    assert cache.get("a") == "1"


def test_set_many_ttl_zero_not_stored(cache: Cache) -> None:
    cache.set_many({"a": "1"}, ttl=0)
    assert cache.get("a") is None


def test_set_many_ttl_zero_evicts_existing_entries(cache: Cache) -> None:
    cache.set_many({"a": "1"}, ttl=60)
    cache.set_many({"a": "2"}, ttl=0)
    assert cache.get("a") is None


def test_set_many_ttl_positive_expires(cache: Cache, fake_time: list[float]) -> None:
    cache.set_many({"a": "1"}, ttl=10)
    assert cache.get("a") == "1"
    fake_time[0] += 11
    assert cache.get("a") is None


def test_set_many_ttl_negative_raises(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        cache.set_many({"a": "1"}, ttl=-1)


def test_set_many_uses_default_ttl() -> None:
    cache = Cache(default_ttl=60)
    cache.set_many({"a": "1"})
    assert cache.contains("a") is True


# --- delete_many ---


def test_delete_many_empty_keys_noop(cache: Cache) -> None:
    cache.delete_many([])


def test_delete_many_existing_keys(cache: Cache) -> None:
    cache.set_many({"a": "1", "b": "2"})
    cache.delete_many(["a", "b"])
    assert cache.get_many(["a", "b"]) == {}


def test_delete_many_missing_keys(cache: Cache) -> None:
    cache.delete_many(["missing"])


def test_delete_many_mixed_keys(cache: Cache) -> None:
    cache.set("a", "1")
    cache.delete_many(["a", "missing"])
    assert cache.get("a") is None


# --- delete ---


def test_delete_existing_key(cache: Cache) -> None:
    cache.set("key", "value")
    cache.delete("key")
    assert cache.get("key") is None


def test_delete_missing_key(cache: Cache) -> None:
    cache.delete("missing")
    assert cache.get("missing") is None


# --- clear ---


def test_clear(cache: Cache) -> None:
    cache.set("key", "value")
    cache.clear()
    assert cache.get("key") is None


# --- get_or_compute ---


def test_get_or_compute_miss_calls_fn(cache: Cache) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    assert cache.get_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


def test_get_or_compute_hit_does_not_call_fn(cache: Cache) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    cache.get_or_compute("key", fn, (1,), {})
    assert cache.get_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


def test_get_or_compute_passes_kwargs(cache: Cache) -> None:
    def fn(x: int, y: int = 0) -> int:
        return x + y

    assert cache.get_or_compute("key", fn, (1,), {"y": 2}) == 3


def test_get_or_compute_respects_ttl(cache: Cache, fake_time: list[float]) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    cache.get_or_compute("key", fn, (1,), {}, ttl=10)
    fake_time[0] += 11
    cache.get_or_compute("key", fn, (1,), {}, ttl=10)
    assert calls == [1, 1]


def test_get_or_compute_ttl_zero_recomputes_every_call(cache: Cache) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    cache.get_or_compute("key", fn, (1,), {}, ttl=0)
    cache.get_or_compute("key", fn, (1,), {}, ttl=0)
    assert calls == [1, 1]


def test_get_or_compute_uses_default_ttl_when_not_set(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    cache.get_or_compute("key", fn, (1,), {})
    fake_time[0] += 11
    cache.get_or_compute("key", fn, (1,), {})
    assert calls == [1, 1]


def test_get_or_compute_ttl_negative_raises(cache: Cache) -> None:
    def fn(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        cache.get_or_compute("key", fn, (1,), {}, ttl=-1)


# --- aget_or_compute ---


async def test_aget_or_compute_miss_calls_fn(cache: Cache) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await cache.aget_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


async def test_aget_or_compute_hit_does_not_call_fn(cache: Cache) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.aget_or_compute("key", fn, (1,), {})
    assert await cache.aget_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


async def test_aget_or_compute_passes_kwargs(cache: Cache) -> None:
    async def fn(x: int, y: int = 0) -> int:
        return x + y

    assert await cache.aget_or_compute("key", fn, (1,), {"y": 2}) == 3


async def test_aget_or_compute_respects_ttl(cache: Cache, fake_time: list[float]) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.aget_or_compute("key", fn, (1,), {}, ttl=10)
    fake_time[0] += 11
    await cache.aget_or_compute("key", fn, (1,), {}, ttl=10)
    assert calls == [1, 1]


async def test_aget_or_compute_ttl_zero_recomputes_every_call(cache: Cache) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.aget_or_compute("key", fn, (1,), {}, ttl=0)
    await cache.aget_or_compute("key", fn, (1,), {}, ttl=0)
    assert calls == [1, 1]


async def test_aget_or_compute_uses_default_ttl_when_not_set(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.aget_or_compute("key", fn, (1,), {})
    fake_time[0] += 11
    await cache.aget_or_compute("key", fn, (1,), {})
    assert calls == [1, 1]


async def test_aget_or_compute_ttl_negative_raises(cache: Cache) -> None:
    async def fn(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        await cache.aget_or_compute("key", fn, (1,), {}, ttl=-1)


async def test_aget_or_compute_different_keys_independent(cache: Cache) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await cache.aget_or_compute("key1", fn, (1,), {}) == 2
    assert await cache.aget_or_compute("key2", fn, (2,), {}) == 4
    assert calls == [1, 2]


# --- memoize ---


def test_memoize_caches_result(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert func(1) == 2
    assert func(1) == 2
    assert calls == [1]


def test_memoize_different_args_not_shared(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    func(2)
    assert calls == [1, 2]


def test_memoize_preserves_function_metadata(cache: Cache) -> None:
    @cache.memoize()
    def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


def test_memoize_respects_ttl(cache: Cache, fake_time: list[float]) -> None:
    calls = []

    @cache.memoize(ttl=10)
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    fake_time[0] += 11
    func(1)
    assert calls == [1, 1]


def test_memoize_uses_default_ttl_when_not_set(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    fake_time[0] += 11
    func(1)
    assert calls == [1, 1]


def test_memoize_strategy_json(cache: Cache) -> None:
    calls = []

    @cache.memoize(strategy="json")
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert func(1) == 2
    assert func(1) == 2
    assert calls == [1]


def test_memoize_strategy_json_rejects_non_serializable(cache: Cache) -> None:
    @cache.memoize(strategy="json")
    def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        func(object())


def test_memoize_default_strategy_rejects_non_serializable(cache: Cache) -> None:
    @cache.memoize()
    def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        func(threading.Lock())


def test_memoize_ignore_non_serializable(cache: Cache) -> None:
    calls = []

    @cache.memoize(strategy="json", ignore_non_serializable=True)
    def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert func(1, object()) == 2
    assert func(1, object()) == 2  # different object, but shares the cache entry
    assert calls == [1]


def test_memoize_kwargs(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert func(1, y=2) == 3
    assert func(1, y=2) == 3
    assert calls == [(1, 2)]


def test_memoize_two_caches_do_not_share_entries() -> None:
    calls = []

    cache1 = Cache()
    cache2 = Cache()

    @cache1.memoize()
    def func_a(x: int) -> int:
        calls.append(x)
        return x * 2

    @cache2.memoize()
    def func_b(x: int) -> int:
        calls.append(x)
        return x * 2

    func_a(1)
    func_b(1)
    assert calls == [1, 1]


def test_memoize_shared_across_functions_with_same_qualname(cache: Cache) -> None:
    # keys are derived from __qualname__, which is the same for both
    # closures below, so their cached results collide
    calls = []

    def make_func() -> Callable[[int], int]:
        @cache.memoize()
        def func(x: int) -> int:
            calls.append(x)
            return x

        return func

    f1 = make_func()
    f2 = make_func()
    f1(1)
    f2(1)
    assert calls == [1]


# --- memoize (async) ---


async def test_memoize_caches_result_async(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_different_args_not_shared_async(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


async def test_memoize_preserves_function_metadata_async(cache: Cache) -> None:
    @cache.memoize()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


async def test_memoize_respects_ttl_async(cache: Cache, fake_time: list[float]) -> None:
    calls = []

    @cache.memoize(ttl=10)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_memoize_uses_default_ttl_when_not_set_async(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_memoize_strategy_json_async(cache: Cache) -> None:
    calls = []

    @cache.memoize(strategy="json")
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_strategy_json_rejects_non_serializable_async(cache: Cache) -> None:
    @cache.memoize(strategy="json")
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(object())


async def test_memoize_default_strategy_rejects_non_serializable_async(cache: Cache) -> None:
    @cache.memoize()
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(threading.Lock())


async def test_memoize_ignore_non_serializable_async(cache: Cache) -> None:
    calls = []

    @cache.memoize(strategy="json", ignore_non_serializable=True)
    async def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert await func(1, object()) == 2
    assert await func(1, object()) == 2  # different object, but shares the cache entry
    assert calls == [1]


async def test_memoize_kwargs_async(cache: Cache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert await func(1, y=2) == 3
    assert await func(1, y=2) == 3
    assert calls == [(1, 2)]


async def test_memoize_two_caches_do_not_share_entries_async() -> None:
    calls = []

    cache1 = Cache()
    cache2 = Cache()

    @cache1.memoize()
    async def func_a(x: int) -> int:
        calls.append(x)
        return x * 2

    @cache2.memoize()
    async def func_b(x: int) -> int:
        calls.append(x)
        return x * 2

    await func_a(1)
    await func_b(1)
    assert calls == [1, 1]


async def test_memoize_shared_across_functions_with_same_qualname_async(cache: Cache) -> None:
    calls = []

    def make_func() -> Callable[[int], Awaitable[int]]:
        @cache.memoize()
        async def func(x: int) -> int:
            calls.append(x)
            return x

        return func

    f1 = make_func()
    f2 = make_func()
    await f1(1)
    await f2(1)
    assert calls == [1]


# --- get/set (async) ---


async def test_aget_missing_key(cache: Cache) -> None:
    assert await cache.aget("missing") is None


async def test_aset_then_get(cache: Cache) -> None:
    await cache.aset("key", "value")
    assert await cache.aget("key") == "value"


async def test_aset_overwrites(cache: Cache) -> None:
    await cache.aset("key", "value1")
    await cache.aset("key", "value2")
    assert await cache.aget("key") == "value2"


@pytest.mark.parametrize("value", [0, "", [], {}, None, False])
async def test_aset_falsy_values(cache: Cache, value: object) -> None:
    await cache.aset("key", value)
    assert await cache.aget("key") == value


async def test_aget_not_yet_expired(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    fake_time[0] += 9
    assert await cache.aget("key") == "value"


async def test_aget_exactly_at_expiry_is_not_expired(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    fake_time[0] += 10
    assert await cache.aget("key") == "value"


async def test_aget_expired(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    fake_time[0] += 11
    assert await cache.aget("key") is None


async def test_aget_expired_evicts_entry(fake_time: list[float]) -> None:
    store = InMemoryStore()
    cache = Cache(store=store)
    await cache.aset("key", "value", ttl=10)
    fake_time[0] += 11
    await cache.aget("key")
    assert await store.aget("key") is None


async def test_cache_async_full_round_trip_through_real_store() -> None:
    """Regression test: exercises Cache against a real InMemoryStore,
    which would raise TypeError if any call site used the sync (unprefixed)
    store methods instead of the async (a-prefixed) ones.
    """
    cache = Cache(store=InMemoryStore())
    await cache.aset("key", "value")
    assert await cache.aget("key") == "value"
    assert await cache.acontains("key") is True
    await cache.adelete("key")
    assert await cache.aget("key") is None
    await cache.aset("key1", "value1")
    await cache.aset("key2", "value2")
    await cache.aclear()
    assert await cache.aget("key1") is None
    assert await cache.aget("key2") is None


async def test_aset_uses_default_ttl_when_not_given(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    await cache.aset("key", "value")
    fake_time[0] += 11
    assert await cache.aget("key") is None


async def test_aset_ttl_overrides_default(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    await cache.aset("key", "value", ttl=100)
    fake_time[0] += 11
    assert await cache.aget("key") == "value"


async def test_aget_default_ttl_none_means_forever_by_default(
    cache: Cache, fake_time: list[float]
) -> None:
    await cache.aset("key", "value")
    fake_time[0] += 1_000_000
    assert await cache.aget("key") == "value"


async def test_aset_ttl_none_means_forever(cache: Cache, fake_time: list[float]) -> None:
    cache._default_ttl = 10
    await cache.aset("key", "value", ttl=None)
    fake_time[0] += 1_000_000
    assert await cache.aget("key") == "value"


async def test_aset_ttl_zero_evicts_existing_entry(cache: Cache) -> None:
    await cache.aset("key", "value")
    await cache.aset("key", "other", ttl=0)
    assert await cache.aget("key") is None


async def test_aset_ttl_negative(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        await cache.aset("key", "value", ttl=-1)


async def test_aget_cached_none_is_miss_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    await cache.aset("key", None)
    assert await cache.aget("key") is None


async def test_aget_cached_none_is_hit_without_ignore_none(cache: Cache) -> None:
    await cache.aset("key", None)
    assert await cache._aget("key") == (True, None)


# --- contains ---


async def test_acontains_missing_key(cache: Cache) -> None:
    assert await cache.acontains("missing") is False


async def test_acontains_existing_key(cache: Cache) -> None:
    await cache.aset("key", "value")
    assert await cache.acontains("key") is True


async def test_acontains_expired_key(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("key", "value", ttl=10)
    fake_time[0] += 11
    assert await cache.acontains("key") is False


# --- aget_many ---


async def test_aget_many_empty_keys_returns_empty_dict(cache: Cache) -> None:
    assert await cache.aget_many([]) == {}


async def test_aget_many_all_missing(cache: Cache) -> None:
    assert await cache.aget_many(["a", "b"]) == {}


async def test_aget_many_mixed_hits_and_misses(cache: Cache) -> None:
    await cache.aset("a", "1")
    await cache.aset("b", "2")
    assert await cache.aget_many(["a", "b", "missing"]) == {"a": "1", "b": "2"}


async def test_aget_many_expired_key_omitted(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("a", "1", ttl=10)
    await cache.aset("b", "2", ttl=None)
    fake_time[0] += 11
    assert await cache.aget_many(["a", "b"]) == {"b": "2"}


async def test_aget_many_expired_key_evicted_as_side_effect(
    cache: Cache, fake_time: list[float]
) -> None:
    await cache.aset("a", "1", ttl=10)
    fake_time[0] += 11
    await cache.aget_many(["a"])
    assert await cache.acontains("a") is False


async def test_aget_many_cached_none_is_hit_by_default(cache: Cache) -> None:
    await cache.aset("a", None, ttl=None)
    assert await cache.aget_many(["a"]) == {"a": None}


async def test_aget_many_cached_none_is_omitted_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    await cache.aset("a", None, ttl=None)
    await cache.aset("b", "2")
    assert await cache.aget_many(["a", "b"]) == {"b": "2"}


# --- acontains_many ---


async def test_acontains_many_empty_keys_returns_empty_list(cache: Cache) -> None:
    assert await cache.acontains_many([]) == []


async def test_acontains_many_all_missing(cache: Cache) -> None:
    assert await cache.acontains_many(["a", "b"]) == [False, False]


async def test_acontains_many_mixed_hits_and_misses(cache: Cache) -> None:
    await cache.aset("a", "1")
    await cache.aset("b", "2")
    assert await cache.acontains_many(["a", "b", "missing"]) == [True, True, False]


async def test_acontains_many_expired_key_omitted(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset("a", "1", ttl=10)
    await cache.aset("b", "2", ttl=None)
    fake_time[0] += 11
    assert await cache.acontains_many(["a", "b"]) == [False, True]


async def test_acontains_many_expired_key_evicted_as_side_effect(
    cache: Cache, fake_time: list[float]
) -> None:
    await cache.aset("a", "1", ttl=10)
    fake_time[0] += 11
    await cache.acontains_many(["a"])
    assert await cache.acontains("a") is False


async def test_acontains_many_cached_none_is_hit_by_default(cache: Cache) -> None:
    await cache.aset("a", None, ttl=None)
    assert await cache.acontains_many(["a"]) == [True]


async def test_acontains_many_cached_none_is_omitted_with_ignore_none() -> None:
    cache = Cache(ignore_none=True)
    await cache.aset("a", None, ttl=None)
    await cache.aset("b", "2")
    assert await cache.acontains_many(["a", "b"]) == [False, True]


# --- aset_many ---


async def test_aset_many_empty_items_noop(cache: Cache) -> None:
    await cache.aset_many({})
    assert await cache.aget_many(["a"]) == {}


async def test_aset_many_then_aget_many(cache: Cache) -> None:
    await cache.aset_many({"a": "1", "b": "2"})
    assert await cache.aget_many(["a", "b"]) == {"a": "1", "b": "2"}


async def test_aset_many_overwrites(cache: Cache) -> None:
    await cache.aset("a", "1")
    await cache.aset_many({"a": "2"})
    assert await cache.aget("a") == "2"


async def test_aset_many_ttl_none_never_expires(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset_many({"a": "1"}, ttl=None)
    fake_time[0] += 10_000
    assert await cache.aget("a") == "1"


async def test_aset_many_ttl_zero_not_stored(cache: Cache) -> None:
    await cache.aset_many({"a": "1"}, ttl=0)
    assert await cache.aget("a") is None


async def test_aset_many_ttl_zero_evicts_existing_entries(cache: Cache) -> None:
    await cache.aset_many({"a": "1"}, ttl=60)
    await cache.aset_many({"a": "2"}, ttl=0)
    assert await cache.aget("a") is None


async def test_aset_many_ttl_positive_expires(cache: Cache, fake_time: list[float]) -> None:
    await cache.aset_many({"a": "1"}, ttl=10)
    assert await cache.aget("a") == "1"
    fake_time[0] += 11
    assert await cache.aget("a") is None


async def test_aset_many_ttl_negative_raises(cache: Cache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        await cache.aset_many({"a": "1"}, ttl=-1)


async def test_aset_many_uses_default_ttl() -> None:
    cache = Cache(default_ttl=60)
    await cache.aset_many({"a": "1"})
    assert await cache.acontains("a") is True


# --- adelete_many ---


async def test_adelete_many_empty_keys_noop(cache: Cache) -> None:
    await cache.adelete_many([])


async def test_adelete_many_existing_keys(cache: Cache) -> None:
    await cache.aset_many({"a": "1", "b": "2"})
    await cache.adelete_many(["a", "b"])
    assert await cache.aget_many(["a", "b"]) == {}


async def test_adelete_many_missing_keys(cache: Cache) -> None:
    await cache.adelete_many(["missing"])


async def test_adelete_many_mixed_keys(cache: Cache) -> None:
    await cache.aset("a", "1")
    await cache.adelete_many(["a", "missing"])
    assert await cache.aget("a") is None


# --- delete ---


async def test_adelete_existing_key(cache: Cache) -> None:
    await cache.aset("key", "value")
    await cache.adelete("key")
    assert await cache.aget("key") is None


async def test_adelete_missing_key(cache: Cache) -> None:
    await cache.adelete("missing")
    assert await cache.aget("missing") is None


# --- clear ---


async def test_aclear_removes_all_entries(cache: Cache) -> None:
    await cache.aset("key1", "value1")
    await cache.aset("key2", "value2")
    await cache.aclear()
    assert await cache.aget("key1") is None
    assert await cache.aget("key2") is None


async def test_aclear_empty_cache(cache: Cache) -> None:
    await cache.aclear()


# --- get_or_compute ---


async def test_aget_or_compute_sync_fn_miss_calls_fn(cache: Cache) -> None:
    def fn(x: int) -> int:
        return x * 2

    assert await cache.aget_or_compute("key", fn, (1,), {}) == 2


async def test_aget_or_compute_sync_fn_hit_does_not_call_fn(cache: Cache) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.aget_or_compute("key", fn, (1,), {})
    assert await cache.aget_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


# --- memoize ---


async def test_amemoize_caches_result(cache: Cache) -> None:
    calls = []

    @cache.amemoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_amemoize_caches_result_sync_func(cache: Cache) -> None:
    calls = []

    @cache.amemoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_amemoize_different_args_not_shared(cache: Cache) -> None:
    calls = []

    @cache.amemoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


async def test_amemoize_preserves_function_metadata(cache: Cache) -> None:
    @cache.amemoize()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


async def test_amemoize_respects_ttl(cache: Cache, fake_time: list[float]) -> None:
    calls = []

    @cache.amemoize(ttl=10)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_amemoize_uses_default_ttl_when_not_set(fake_time: list[float]) -> None:
    cache = Cache(default_ttl=10)
    calls = []

    @cache.amemoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_amemoize_strategy_json(cache: Cache) -> None:
    calls = []

    @cache.amemoize(strategy="json")
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_amemoize_strategy_json_rejects_non_serializable(cache: Cache) -> None:
    @cache.amemoize(strategy="json")
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(object())


async def test_amemoize_default_strategy_rejects_non_serializable(cache: Cache) -> None:
    @cache.amemoize()
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(threading.Lock())


async def test_amemoize_ignore_non_serializable(cache: Cache) -> None:
    calls = []

    @cache.amemoize(strategy="json", ignore_non_serializable=True)
    async def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert await func(1, object()) == 2
    assert await func(1, object()) == 2  # different object, shares the cache entry
    assert calls == [1]


async def test_amemoize_kwargs(cache: Cache) -> None:
    calls = []

    @cache.amemoize()
    async def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert await func(1, y=2) == 3
    assert await func(1, y=2) == 3
    assert calls == [(1, 2)]


async def test_amemoize_two_caches_do_not_share_entries() -> None:
    cache1 = Cache()
    cache2 = Cache()
    calls = []

    @cache1.amemoize()
    async def func1(x: int) -> int:
        calls.append(("func1", x))
        return x * 2

    @cache2.amemoize()
    async def func2(x: int) -> int:
        calls.append(("func2", x))
        return x * 2

    await func1(1)
    await func2(1)
    assert calls == [("func1", 1), ("func2", 1)]


async def test_amemoize_shared_across_functions_with_same_qualname(cache: Cache) -> None:
    # keys are derived from __qualname__, which is the same for both
    # closures below, so their cached results collide
    calls = []

    def make_func() -> Callable[[int], Coroutine[None, None, int]]:
        @cache.amemoize()
        async def func(x: int) -> int:
            calls.append(x)
            return x

        return func

    f1 = make_func()
    f2 = make_func()
    await f1(1)
    await f2(1)
    assert calls == [1]
