from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.cache.async_ttl import AsyncTTLCache
from persista.cache.interface import (
    async_cached,
    cached,
    get_async_ttl_cache,
    get_ttl_cache,
    set_async_ttl_cache,
    set_ttl_cache,
)
from persista.cache.ttl import TTLCache

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_default_cache() -> Iterator[None]:
    # Isolate tests from each other and from any cache installed by
    # a previous test via `set_ttl_cache`.
    original = get_ttl_cache()
    set_ttl_cache(TTLCache())
    yield
    set_ttl_cache(original)


@pytest.fixture(autouse=True)
def _reset_default_async_cache() -> Iterator[None]:
    # Isolate tests from each other and from any cache installed by
    # a previous test via `set_async_ttl_cache`.
    original = get_async_ttl_cache()
    set_async_ttl_cache(AsyncTTLCache())
    yield
    set_async_ttl_cache(original)


#####################################
#     Tests for get_ttl_cache       #
#####################################


def test_get_ttl_cache_returns_ttl_cache() -> None:
    assert isinstance(get_ttl_cache(), TTLCache)


def test_get_ttl_cache_returns_same_instance() -> None:
    assert get_ttl_cache() is get_ttl_cache()


#####################################
#     Tests for set_ttl_cache       #
#####################################


def test_set_ttl_cache_replaces_instance() -> None:
    cache = TTLCache()
    set_ttl_cache(cache)
    assert get_ttl_cache() is cache


def test_set_ttl_cache_reflected_by_previously_decorated_function() -> None:
    calls = []

    @cached()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    assert calls == [1]

    # Swapping the shared cache should make `func` start with a clean slate.
    set_ttl_cache(TTLCache())
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
    key = next(iter(get_ttl_cache()._store._data))
    assert get_ttl_cache()._store.get(key) is not None


def test_cached_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.ttl.time.time", lambda: clock[0])
    calls = []

    @cached(ttl=10)
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    clock[0] += 11
    func(1)
    assert calls == [1, 1]


def test_cached_ttl_zero() -> None:
    @cached(ttl=0)
    def func(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match=r"ttl must be a positive number, got 0"):
        func(1)


async def test_cached_caches_result_async() -> None:
    calls = []

    @cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


###########################################
#     Tests for get_async_ttl_cache       #
###########################################


def test_get_async_ttl_cache_returns_async_ttl_cache() -> None:
    assert isinstance(get_async_ttl_cache(), AsyncTTLCache)


def test_get_async_ttl_cache_returns_same_instance() -> None:
    assert get_async_ttl_cache() is get_async_ttl_cache()


###########################################
#     Tests for set_async_ttl_cache       #
###########################################


def test_set_async_ttl_cache_replaces_instance() -> None:
    cache = AsyncTTLCache()
    set_async_ttl_cache(cache)
    assert get_async_ttl_cache() is cache


async def test_set_async_ttl_cache_reflected_by_previously_decorated_function() -> None:
    calls = []

    @async_cached()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    assert calls == [1]

    # Swapping the shared cache should make `func` start with a clean slate.
    set_async_ttl_cache(AsyncTTLCache())
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


async def test_async_cached_uses_shared_default_cache() -> None:
    @async_cached()
    async def func(x: int) -> int:
        return x * 2

    await func(1)
    key = next(iter(get_async_ttl_cache()._store._data))
    assert await get_async_ttl_cache()._store.get(key) is not None


async def test_async_cached_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.async_ttl.time.time", lambda: clock[0])
    calls = []

    @async_cached(ttl=10)
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    clock[0] += 11
    await func(1)
    assert calls == [1, 1]


async def test_async_cached_ttl_zero() -> None:
    @async_cached(ttl=0)
    async def func(x: int) -> int:
        return x * 2

    with pytest.raises(ValueError, match=r"ttl must be a positive number, got 0"):
        await func(1)
