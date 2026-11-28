from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from persista.cache.cache import Cache
from persista.cache.interface import _make_default_cache, _state, cached, get_cache, set_cache
from persista.cache.memoize import build_key_function
from persista.store.codec import PickleCodec
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def _isolate_default_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Each test starts without a default cache, and the one it creates is
    # forgotten afterwards.
    monkeypatch.delitem(_state, "cache", raising=False)
    yield
    if (cache := _state.get("cache")) is not None:
        cache.close()


@pytest.fixture
def cache() -> Iterator[Cache]:
    with Cache() as cache:
        set_cache(cache)
        yield cache


#########################################
#     Tests for _make_default_cache     #
#########################################


def test_make_default_cache_is_open() -> None:
    cache = _make_default_cache()
    assert not cache.closed
    cache.close()


def test_make_default_cache_ttl() -> None:
    assert _make_default_cache().default_ttl == 300


def test_make_default_cache_store() -> None:
    assert isinstance(_make_default_cache()._store, InMemoryStore)


def test_make_default_cache_codec() -> None:
    assert isinstance(_make_default_cache()._store._codec, PickleCodec)


def test_make_default_cache_new_instance() -> None:
    assert _make_default_cache() is not _make_default_cache()


###############################
#     Tests for get_cache     #
###############################


def test_get_cache_creates_cache_on_first_call() -> None:
    cache = get_cache()
    assert _state == {"cache": cache}


def test_get_cache_returns_open_cache() -> None:
    assert not get_cache().closed


def test_get_cache_returns_same_instance() -> None:
    assert get_cache() is get_cache()


def test_get_cache_returns_installed_cache(cache: Cache) -> None:
    assert get_cache() is cache


def test_get_cache_creates_one_default_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def make() -> Cache:
        calls.append(1)
        return _make_default_cache()

    monkeypatch.setattr("persista.cache.interface._make_default_cache", make)
    get_cache()
    get_cache()
    assert calls == [1]


class SetCacheOnEnter:
    r"""A lock during whose acquisition another thread installs a
    cache."""

    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def __enter__(self) -> None:
        _state["cache"] = self.cache

    def __exit__(self, *exc_info: object) -> None:
        pass


def test_get_cache_set_while_waiting_for_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = Cache()
    monkeypatch.setattr("persista.cache.interface._lock", SetCacheOnEnter(cache))
    assert get_cache() is cache


###############################
#     Tests for set_cache     #
###############################


def test_set_cache_before_get_cache_creates_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr("persista.cache.interface._make_default_cache", lambda: calls.append(1))
    set_cache(Cache())
    get_cache()
    assert calls == []


def test_set_cache_replaces_instance(cache: Cache) -> None:
    other = Cache()
    set_cache(other)
    assert get_cache() is not cache


def test_set_cache_does_not_open_cache() -> None:
    cache = Cache()
    set_cache(cache)
    assert cache.closed


############################
#     Tests for cached     #
############################


def test_cached() -> None:
    calls = []

    @cached()
    def double(x: int) -> int:
        calls.append(x)
        return x * 2

    assert (double(1), double(x=1), double(2), calls) == (2, 2, 4, [1, 2])


async def test_cached_async() -> None:
    calls = []

    @cached()
    async def double(x: int) -> int:
        calls.append(x)
        return x * 2

    results = [await double(1), await double(x=1)]
    assert (results, calls) == ([2, 2], [1])


def test_cached_creates_no_cache_at_decoration() -> None:
    @cached()
    def func() -> None:
        pass

    assert _state == {}


def test_cached_uses_default_cache(cache: Cache) -> None:
    def double(x: int) -> int:
        return x * 2

    cached()(double)(1)
    assert cache.get(build_key_function(double)((1,), {})) == 2


def test_cached_uses_cache_installed_at_call_time() -> None:
    calls = []
    func = cached()(lambda: calls.append(1))
    with Cache() as first, Cache() as second:
        set_cache(first)
        func()
        set_cache(second)
        func()
    assert calls == [1, 1]


def test_cached_shares_entries_with_memoize(cache: Cache) -> None:
    calls = []

    def func() -> None:
        calls.append(1)

    cache.memoize()(func)()
    cached()(func)()
    assert calls == [1]


@pytest.mark.usefixtures("cache")
def test_cached_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [1_000_000.0]
    monkeypatch.setattr("persista.cache.cache.time.time", lambda: clock[0])
    calls = []
    func = cached(ttl=10)(lambda: calls.append(1))
    func()
    clock[0] += 11
    func()
    assert calls == [1, 1]


@pytest.mark.usefixtures("cache")
def test_cached_ignore() -> None:
    calls = []

    @cached(ignore=("client",))
    def func(client: object) -> None:
        del client
        calls.append(1)

    func(object())
    func(object())
    assert calls == [1]


def test_cached_key(cache: Cache) -> None:
    cached(key=lambda: "my-key")(lambda: 1)()
    assert cache.get("my-key") == 1


@pytest.mark.parametrize("ttl", [-1, float("nan")])
def test_cached_ttl_invalid(ttl: float) -> None:
    with pytest.raises(ValueError, match=r"ttl must be None, 0 or positive"):
        cached(ttl=ttl)


def test_cached_ignore_and_key() -> None:
    with pytest.raises(ValueError, match=r"ignore and key cannot be used together"):
        cached(ignore=["x"], key=str)


def test_cached_unknown_ignore_name() -> None:
    decorator = cached(ignore=["z"])
    with pytest.raises(ValueError, match=r"does not have: \['z'\]"):
        decorator(lambda x: x)


def test_cached_options_are_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        cached(60)
