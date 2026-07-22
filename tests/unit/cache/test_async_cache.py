from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from persista.cache.async_cache import AsyncCache
from persista.store.async_in_memory import AsyncInMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> AsyncCache:
    return AsyncCache()


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # The current time is `clock[0]`; mutate it to simulate time passing.
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.async_cache.time.time", lambda: clock[0])
    return clock


######################################
#     Tests for AsyncCache          #
######################################


# --- constructor ---


def test_init_default_store() -> None:
    cache = AsyncCache()
    assert isinstance(cache._store, AsyncInMemoryStore)


def test_init_custom_store() -> None:
    store = AsyncInMemoryStore()
    cache = AsyncCache(store=store)
    assert cache._store is store


def test_init_default_ttl_is_none() -> None:
    assert AsyncCache().default_ttl is None


def test_init_custom_default_ttl() -> None:
    assert AsyncCache(default_ttl=60).default_ttl == 60


def test_init_default_ttl_negative() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be non-negative, got -1"):
        AsyncCache(default_ttl=-1)


# --- get/set ---


async def test_get_missing_key(cache: AsyncCache) -> None:
    assert await cache.get("missing") is None


async def test_set_then_get(cache: AsyncCache) -> None:
    await cache.set("key", "value")
    assert await cache.get("key") == "value"


async def test_set_overwrites(cache: AsyncCache) -> None:
    await cache.set("key", "value1")
    await cache.set("key", "value2")
    assert await cache.get("key") == "value2"


@pytest.mark.parametrize("value", [0, "", [], {}, None, False])
async def test_set_falsy_values(cache: AsyncCache, value: object) -> None:
    await cache.set("key", value)
    assert await cache.get("key") == value


async def test_get_not_yet_expired(cache: AsyncCache, fake_time: list[float]) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 9
    assert await cache.get("key") == "value"


async def test_get_exactly_at_expiry_is_not_expired(
    cache: AsyncCache, fake_time: list[float]
) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 10
    assert await cache.get("key") == "value"


async def test_get_expired(cache: AsyncCache, fake_time: list[float]) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    assert await cache.get("key") is None


async def test_get_expired_evicts_entry(fake_time: list[float]) -> None:
    store = AsyncInMemoryStore()
    cache = AsyncCache(store=store)
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    await cache.get("key")
    assert await store.get("key") is None


async def test_set_uses_default_ttl_when_not_given(fake_time: list[float]) -> None:
    cache = AsyncCache(default_ttl=10)
    await cache.set("key", "value")
    fake_time[0] += 11
    assert await cache.get("key") is None


async def test_set_ttl_overrides_default(fake_time: list[float]) -> None:
    cache = AsyncCache(default_ttl=10)
    await cache.set("key", "value", ttl=100)
    fake_time[0] += 11
    assert await cache.get("key") == "value"


async def test_default_ttl_none_means_forever_by_default(
    cache: AsyncCache, fake_time: list[float]
) -> None:
    await cache.set("key", "value")
    fake_time[0] += 1_000_000
    assert await cache.get("key") == "value"


async def test_set_ttl_none_means_forever(cache: AsyncCache, fake_time: list[float]) -> None:
    cache.default_ttl = 10
    await cache.set("key", "value", ttl=None)
    fake_time[0] += 1_000_000
    assert await cache.get("key") == "value"


async def test_set_ttl_zero_evicts_existing_entry(cache: AsyncCache) -> None:
    await cache.set("key", "value")
    await cache.set("key", "other", ttl=0)
    assert await cache.get("key") is None


async def test_set_ttl_negative(cache: AsyncCache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        await cache.set("key", "value", ttl=-1)


async def test_get_cached_none_is_miss_with_ignore_none() -> None:
    cache = AsyncCache(ignore_none=True)
    await cache.set("key", None)
    assert await cache.get("key") is None


async def test_get_cached_none_is_hit_without_ignore_none(cache: AsyncCache) -> None:
    await cache.set("key", None)
    assert await cache._get("key") == (True, None)


# --- contains ---


async def test_contains_missing_key(cache: AsyncCache) -> None:
    assert await cache.contains("missing") is False


async def test_contains_existing_key(cache: AsyncCache) -> None:
    await cache.set("key", "value")
    assert await cache.contains("key") is True


async def test_contains_expired_key(cache: AsyncCache, fake_time: list[float]) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    assert await cache.contains("key") is False


# --- delete ---


async def test_delete_existing_key(cache: AsyncCache) -> None:
    await cache.set("key", "value")
    await cache.delete("key")
    assert await cache.get("key") is None


async def test_delete_missing_key(cache: AsyncCache) -> None:
    await cache.delete("missing")
    assert await cache.get("missing") is None


# --- clear ---


async def test_clear_removes_all_entries(cache: AsyncCache) -> None:
    await cache.set("key1", "value1")
    await cache.set("key2", "value2")
    await cache.clear()
    assert await cache.get("key1") is None
    assert await cache.get("key2") is None


async def test_clear_empty_cache(cache: AsyncCache) -> None:
    await cache.clear()


# --- get_or_compute ---


async def test_get_or_compute_miss_calls_fn(cache: AsyncCache) -> None:
    async def fn(x: int) -> int:
        return x * 2

    assert await cache.get_or_compute("key", fn, (1,), {}) == 2


async def test_get_or_compute_hit_does_not_call_fn(cache: AsyncCache) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.get_or_compute("key", fn, (1,), {})
    assert await cache.get_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


async def test_get_or_compute_passes_kwargs(cache: AsyncCache) -> None:
    async def fn(x: int, y: int = 0) -> int:
        return x + y

    assert await cache.get_or_compute("key", fn, (1,), {"y": 2}) == 3


async def test_get_or_compute_respects_ttl(cache: AsyncCache, fake_time: list[float]) -> None:
    calls = []

    async def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.get_or_compute("key", fn, (1,), {}, ttl=10)
    fake_time[0] += 11
    await cache.get_or_compute("key", fn, (1,), {}, ttl=10)
    assert calls == [1, 1]


async def test_get_or_compute_ttl_negative_raises(cache: AsyncCache) -> None:
    async def fn(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match=r"ttl must be non-negative, got -1"):
        await cache.get_or_compute("key", fn, (1,), {}, ttl=-1)


async def test_get_or_compute_different_keys_independent(cache: AsyncCache) -> None:
    async def fn(x: int) -> int:
        return x * 2

    assert await cache.get_or_compute("key1", fn, (1,), {}) == 2
    assert await cache.get_or_compute("key2", fn, (2,), {}) == 4


async def test_get_or_compute_sync_fn_miss_calls_fn(cache: AsyncCache) -> None:
    def fn(x: int) -> int:
        return x * 2

    assert await cache.get_or_compute("key", fn, (1,), {}) == 2


async def test_get_or_compute_sync_fn_hit_does_not_call_fn(cache: AsyncCache) -> None:
    calls = []

    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    await cache.get_or_compute("key", fn, (1,), {})
    assert await cache.get_or_compute("key", fn, (1,), {}) == 2
    assert calls == [1]


# --- memoize ---


async def test_memoize_caches_result(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_caches_result_sync_func(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_different_args_not_shared(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


async def test_memoize_preserves_function_metadata(cache: AsyncCache) -> None:
    @cache.memoize()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


async def test_memoize_respects_ttl(cache: AsyncCache, fake_time: list[float]) -> None:
    calls = []

    @cache.memoize(ttl=10)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_memoize_uses_default_ttl_when_not_set(fake_time: list[float]) -> None:
    cache = AsyncCache(default_ttl=10)
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_memoize_strategy_json(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize(strategy="json")
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_strategy_json_rejects_non_serializable(cache: AsyncCache) -> None:
    @cache.memoize(strategy="json")
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(object())


async def test_memoize_default_strategy_rejects_non_serializable(cache: AsyncCache) -> None:
    @cache.memoize()
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(threading.Lock())


async def test_memoize_ignore_non_serializable(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize(strategy="json", ignore_non_serializable=True)
    async def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert await func(1, object()) == 2
    assert await func(1, object()) == 2  # different object, shares the cache entry
    assert calls == [1]


async def test_memoize_kwargs(cache: AsyncCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert await func(1, y=2) == 3
    assert await func(1, y=2) == 3
    assert calls == [(1, 2)]


async def test_memoize_two_caches_do_not_share_entries() -> None:
    cache1 = AsyncCache()
    cache2 = AsyncCache()
    calls = []

    @cache1.memoize()
    async def func1(x: int) -> int:
        calls.append(("func1", x))
        return x * 2

    @cache2.memoize()
    async def func2(x: int) -> int:
        calls.append(("func2", x))
        return x * 2

    await func1(1)
    await func2(1)
    assert calls == [("func1", 1), ("func2", 1)]


async def test_memoize_shared_across_functions_with_same_qualname(cache: AsyncCache) -> None:
    # keys are derived from __qualname__, which is the same for both
    # closures below, so their cached results collide
    calls = []

    def make_func() -> Callable[[int], Coroutine[None, None, int]]:
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
