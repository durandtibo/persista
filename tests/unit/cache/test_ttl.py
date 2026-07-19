from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.cache.ttl import TTLCache
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> TTLCache:
    return TTLCache()


@pytest.fixture
def fake_time(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # The current time is `clock[0]`; mutate it to simulate time passing.
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.ttl.time.time", lambda: clock[0])
    return clock


#################################
#     Tests for TTLCache       #
#################################


# --- constructor ---


def test_init_default_store() -> None:
    cache = TTLCache()
    assert isinstance(cache._store, InMemoryStore)


def test_init_custom_store() -> None:
    store = InMemoryStore()
    cache = TTLCache(store=store)
    assert cache._store is store


def test_init_default_ttl() -> None:
    assert TTLCache().default_ttl == 300


def test_init_custom_default_ttl() -> None:
    assert TTLCache(default_ttl=60).default_ttl == 60


def test_init_default_ttl_zero() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be a positive number, got 0"):
        TTLCache(default_ttl=0)


def test_init_default_ttl_negative() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be a positive number, got -1"):
        TTLCache(default_ttl=-1)


# --- get/set ---


def test_get_missing_key(cache: TTLCache) -> None:
    assert cache.get("missing") is None


def test_set_then_get(cache: TTLCache) -> None:
    cache.set("key", "value")
    assert cache.get("key") == "value"


def test_set_overwrites(cache: TTLCache) -> None:
    cache.set("key", "value1")
    cache.set("key", "value2")
    assert cache.get("key") == "value2"


@pytest.mark.parametrize("value", [0, "", [], {}, None, False])
def test_set_falsy_values(cache: TTLCache, value: object) -> None:
    cache.set("key", value)
    assert cache.get("key") == value


def test_get_not_yet_expired(cache: TTLCache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    fake_time[0] += 9
    assert cache.get("key") == "value"


def test_get_exactly_at_expiry_is_not_expired(cache: TTLCache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    fake_time[0] += 10
    assert cache.get("key") == "value"


def test_get_expired(cache: TTLCache, fake_time: list[float]) -> None:
    cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    assert cache.get("key") is None


def test_get_expired_evicts_entry(fake_time: list[float]) -> None:
    store = InMemoryStore()
    cache = TTLCache(store=store)
    cache.set("key", "value", ttl=10)
    fake_time[0] += 11
    cache.get("key")
    assert store.get("key") is None


def test_set_uses_default_ttl(fake_time: list[float]) -> None:
    cache = TTLCache(default_ttl=10)
    cache.set("key", "value")
    fake_time[0] += 11
    assert cache.get("key") is None


def test_set_ttl_overrides_default(fake_time: list[float]) -> None:
    cache = TTLCache(default_ttl=10)
    cache.set("key", "value", ttl=100)
    fake_time[0] += 11
    assert cache.get("key") == "value"


def test_set_ttl_zero(cache: TTLCache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be a positive number, got 0"):
        cache.set("key", "value", ttl=0)


def test_set_ttl_negative(cache: TTLCache) -> None:
    with pytest.raises(ValueError, match=r"ttl must be a positive number, got -1"):
        cache.set("key", "value", ttl=-1)


# --- clear ---


def test_clear_removes_all_entries(cache: TTLCache) -> None:
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.clear()
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_clear_empty_cache(cache: TTLCache) -> None:
    cache.clear()


# --- memoize ---


def test_memoize_caches_result(cache: TTLCache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert func(1) == 2
    assert func(1) == 2
    assert calls == [1]


def test_memoize_different_args_not_shared(cache: TTLCache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    func(2)
    assert calls == [1, 2]


def test_memoize_preserves_function_metadata(cache: TTLCache) -> None:
    @cache.memoize()
    def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


def test_memoize_respects_ttl(cache: TTLCache, fake_time: list[float]) -> None:
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
    cache = TTLCache(default_ttl=10)
    calls = []

    @cache.memoize()
    def func(x: int) -> int:
        calls.append(x)
        return x * 2

    func(1)
    fake_time[0] += 11
    func(1)
    assert calls == [1, 1]


def test_memoize_kwargs(cache: TTLCache) -> None:
    calls = []

    @cache.memoize()
    def func(x: int, y: int = 0) -> int:
        calls.append((x, y))
        return x + y

    assert func(1, y=2) == 3
    assert func(1, y=2) == 3
    assert calls == [(1, 2)]


async def test_memoize_caches_result_async(cache: TTLCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await func(1) == 2
    assert await func(1) == 2
    assert calls == [1]


async def test_memoize_different_args_not_shared_async(cache: TTLCache) -> None:
    calls = []

    @cache.memoize()
    async def func(x: int) -> int:
        calls.append(x)
        return x * 2

    await func(1)
    await func(2)
    assert calls == [1, 2]


async def test_memoize_preserves_function_metadata_async(cache: TTLCache) -> None:
    @cache.memoize()
    async def func(x: int) -> int:
        """Double x."""
        return x * 2

    assert func.__name__ == "func"
    assert func.__doc__ == "Double x."


def test_memoize_two_caches_do_not_share_entries() -> None:
    cache1 = TTLCache()
    cache2 = TTLCache()
    calls = []

    @cache1.memoize()
    def func1(x: int) -> int:
        calls.append(("func1", x))
        return x * 2

    @cache2.memoize()
    def func2(x: int) -> int:
        calls.append(("func2", x))
        return x * 2

    func1(1)
    func2(1)
    assert calls == [("func1", 1), ("func2", 1)]


def test_memoize_shared_across_functions_with_same_qualname(cache: TTLCache) -> None:
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
