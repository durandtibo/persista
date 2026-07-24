from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from persista.cache.async_cache import AsyncCache
from persista.cache.cache import Cache
from persista.cache.interface import (
    async_cached,
    cached,
    get_async_cache,
    get_cache,
    set_async_cache,
    set_cache,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_default_cache() -> Iterator[None]:
    # Isolate tests from each other and from any cache installed by
    # a previous test via `set_cache`.
    original = get_cache()
    set_cache(Cache(default_ttl=300))
    yield
    set_cache(original)


@pytest.fixture(autouse=True)
def _reset_default_async_cache() -> Iterator[None]:
    # Isolate tests from each other and from any cache installed by
    # a previous test via `set_async_cache`.
    original = get_async_cache()
    set_async_cache(AsyncCache())
    yield
    set_async_cache(original)


#################################
#     Tests for get_cache       #
#################################


def test_get_cache_returns_cache() -> None:
    assert isinstance(get_cache(), Cache)


def test_get_cache_returns_same_instance() -> None:
    assert get_cache() is get_cache()


#################################
#     Tests for set_cache       #
#################################


def test_set_cache_replaces_instance() -> None:
    cache = Cache()
    set_cache(cache)
    assert get_cache() is cache


def test_set_cache_reflected_by_previously_decorated_function() -> None:
    calls = []

    @cached()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    assert calls == [1]

    # Swapping the shared cache should make `func` start with a clean slate.
    set_cache(Cache())
    func(1)
    assert calls == [1, 1]


################################
#     Tests for cached         #
################################


def test_cached_caches_result() -> None:
    calls = []

    @cached()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert func(1) == 2
    assert func(1) == 2
    assert calls == [1]


def test_cached_different_args_not_shared() -> None:
    calls = []

    @cached()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    func(2)
    assert calls == [1, 2]


def test_cached_preserves_function_metadata() -> None:
    @cached()
    def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


def test_cached_uses_shared_default_cache() -> None:
    @cached()
    def func(x: int) -> int:
        return x * 2

    func(1)
    key = next(iter(get_cache()._store._data))
    assert get_cache()._store.get(key) is not None


def test_cached_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.cache.time.time", lambda: clock[0])
    calls = []

    @cached(ttl=10)
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    clock[0] += 11
    func(1)
    assert calls == [1, 1]


def test_cached_ttl_zero_recomputes_every_call() -> None:
    calls = []

    @cached(ttl=0)
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    func(1)
    assert calls == [1, 1]


async def test_cached_caches_result_async() -> None:
    calls = []

    @cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


def test_cached_strategy_json() -> None:
    calls = []

    @cached(strategy="json")
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert func(1) == 2
    assert func(1) == 2
    assert calls == [1]


def test_cached_strategy_json_rejects_non_serializable() -> None:
    @cached(strategy="json")
    def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        func(object())


def test_cached_default_strategy_rejects_non_serializable() -> None:
    @cached()
    def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        func(threading.Lock())


def test_cached_ignore_non_serializable() -> None:
    calls = []

    @cached(strategy="json", ignore_non_serializable=True)
    def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert func(1, object()) == 2
    assert func(1, object()) == 2  # different object, but shares the cache entry
    assert calls == [1]


###########################################
#     Tests for get_async_cache       #
###########################################


def test_get_async_cache_returns_async_cache() -> None:
    assert isinstance(get_async_cache(), AsyncCache)


def test_get_async_cache_returns_same_instance() -> None:
    assert get_async_cache() is get_async_cache()


###########################################
#     Tests for set_async_cache       #
###########################################


def test_set_async_cache_replaces_instance() -> None:
    cache = AsyncCache()
    set_async_cache(cache)
    assert get_async_cache() is cache


async def test_set_async_cache_reflected_by_previously_decorated_function() -> None:
    calls = []

    @async_cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    assert calls == [1]

    # Swapping the shared cache should make `func` start with a clean slate.
    set_async_cache(AsyncCache())
    await func(1)
    assert calls == [1, 1]


######################################
#     Tests for async_cached         #
######################################


async def test_async_cached_caches_result() -> None:
    calls = []

    @async_cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_async_cached_different_args_not_shared() -> None:
    calls = []

    @async_cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


def test_async_cached_preserves_function_metadata() -> None:
    @async_cached()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


async def test_async_cached_strategy_json() -> None:
    calls = []

    @async_cached(strategy="json")
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_async_cached_strategy_json_rejects_non_serializable() -> None:
    @async_cached(strategy="json")
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(object())


async def test_async_cached_default_strategy_rejects_non_serializable() -> None:
    @async_cached()
    async def func(x: object) -> object:
        return x

    with pytest.raises(TypeError):
        await func(threading.Lock())


async def test_async_cached_ignore_non_serializable() -> None:
    calls = []

    @async_cached(strategy="json", ignore_non_serializable=True)
    async def func(x: int, _obj: object) -> int:
        calls.append(x)
        return x * 2

    assert await func(1, object()) == 2
    assert await func(1, object()) == 2  # different object, shares the cache entry
    assert calls == [1]


async def test_async_cached_uses_shared_default_cache() -> None:
    @async_cached()
    async def func(x: int) -> int:
        return x * 2

    await func(1)
    key = next(iter(get_async_cache()._store._data))
    assert await get_async_cache()._store.aget(key) is not None


async def test_async_cached_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.async_cache.time.time", lambda: clock[0])
    calls = []

    @async_cached(ttl=10)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    clock[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_async_cached_ttl_zero_recomputes_every_call() -> None:
    calls = []

    @async_cached(ttl=0)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(1)
    assert calls == [1, 1]
