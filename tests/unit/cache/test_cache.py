from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from persista.cache.cache import Cache
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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
