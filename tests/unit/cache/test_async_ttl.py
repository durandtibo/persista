from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.cache.async_ttl import AsyncTTLCache
from persista.store.async_in_memory import AsyncInMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> AsyncTTLCache:
    return AsyncTTLCache()


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # The current time is `clock[0]`; mutate it to simulate time passing.
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.async_ttl.time.time", lambda: clock[0])
    return clock


######################################
#     Tests for AsyncTTLCache       #
######################################


# --- constructor ---


def test_init_default_store() -> None:
    cache = AsyncTTLCache()
    assert isinstance(cache._store, AsyncInMemoryStore)


def test_init_custom_store() -> None:
    store = AsyncInMemoryStore()
    cache = AsyncTTLCache(store=store)
    assert cache._store is store


def test_init_default_ttl() -> None:
    assert AsyncTTLCache().default_ttl == 300


def test_init_custom_default_ttl() -> None:
    assert AsyncTTLCache(default_ttl=60).default_ttl == 60


def test_init_default_ttl_zero() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be a positive number, got 0"):
        AsyncTTLCache(default_ttl=0)


def test_init_default_ttl_negative() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be a positive number, got -1"):
        AsyncTTLCache(default_ttl=-1)


# --- get/set ---


async def test_get_missing_key(cache: AsyncTTLCache) -> None:
    assert await cache.get("missing") is None


async def test_set_then_get(cache: AsyncTTLCache) -> None:
    await cache.set("key", "value")
    assert await cache.get("key") == "value"


async def test_set_overwrites(cache: AsyncTTLCache) -> None:
    await cache.set("key", "value1")
    await cache.set("key", "value2")
    assert await cache.get("key") == "value2"


@pytest.mark.parametrize("value", [0, "", [], {}, None, False])
async def test_set_falsy_values(cache: AsyncTTLCache, value: object) -> None:
    await cache.set("key", value)
    assert await cache.get("key") == value


async def test_get_not_yet_expired(cache: AsyncTTLCache, fake_time: list[float]) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 9
    assert await cache.get("key") == "value"


async def test_get_exactly_at_expiry_is_not_expired(
    cache: AsyncTTLCache, fake_time: list[float]
) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 10
    assert await cache.get("key") == "value"


async def test_get_expired(cache: AsyncTTLCache, fake_time: list[float]) -> None:
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    assert await cache.get("key") is None


async def test_get_expired_evicts_entry(fake_time: list[float]) -> None:
    store = AsyncInMemoryStore()
    cache = AsyncTTLCache(store=store)
    await cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    await cache.get("key")
    assert await store.get("key") is None


async def test_set_uses_default_ttl(fake_time: list[float]) -> None:
    cache = AsyncTTLCache(default_ttl=10)
    await cache.set("key", "value")
    fake_time[0] += 11
    assert await cache.get("key") is None


async def test_set_ttl_overrides_default(fake_time: list[float]) -> None:
    cache = AsyncTTLCache(default_ttl=10)
    await cache.set("key", "value", ttl=100)
    fake_time[0] += 11
    assert await cache.get("key") == "value"


async def test_set_ttl_zero(cache: AsyncTTLCache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be a positive number, got 0"):
        await cache.set("key", "value", ttl=0)


async def test_set_ttl_negative(cache: AsyncTTLCache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be a positive number, got -1"):
        await cache.set("key", "value", ttl=-1)


# --- clear ---


async def test_clear_removes_all_entries(cache: AsyncTTLCache) -> None:
    await cache.set("key1", "value1")
    await cache.set("key2", "value2")
    await cache.clear()
    assert await cache.get("key1") is None
    assert await cache.get("key2") is None


async def test_clear_empty_cache(cache: AsyncTTLCache) -> None:
    await cache.clear()


# --- memoize ---


async def test_memoize_caches_result(cache: AsyncTTLCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_different_args_not_shared(cache: AsyncTTLCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


async def test_memoize_preserves_function_metadata(cache: AsyncTTLCache) -> None:
    @cache.memoize()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


async def test_memoize_respects_ttl(cache: AsyncTTLCache, fake_time: list[float]) -> None:
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
    cache = AsyncTTLCache(default_ttl=10)
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    fake_time[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_memoize_kwargs(cache: AsyncTTLCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert await func(1, y=2) == 3
    assert await func(1, y=2) == 3
    assert calls == [(1, 2)]


async def test_memoize_two_caches_do_not_share_entries() -> None:
    cache1 = AsyncTTLCache()
    cache2 = AsyncTTLCache()
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


async def test_memoize_shared_across_functions_with_same_qualname(cache: AsyncTTLCache) -> None:
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
