r"""Provide module-level access to a shared default cache."""

from __future__ import annotations

__all__ = ["cached", "get_cache", "set_cache"]


import threading
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from persista.cache.cache import Cache
from persista.cache.memoize import memoize_with
from persista.cache.ttl import DEFAULT
from persista.store.codec import PickleCodec
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

P = ParamSpec("P")
R = TypeVar("R")

# A dict, rather than a plain module-level variable, lets the functions
# below assign the entry without a `global` statement. It is empty until
# the default cache is needed.
_state: dict[str, Cache] = {}
# Held while the default cache is created or replaced, so that threads
# share one default cache.
_lock = threading.Lock()


def _make_default_cache() -> Cache:
    """Create and open the shared default cache.

    Returns:
        A new open cache that keeps its entries in memory for 300
        seconds, with the :class:`~persista.store.PickleCodec`.
    """
    cache = Cache(InMemoryStore(codec=PickleCodec()), default_ttl=300)
    cache.open()
    return cache


def get_cache() -> Cache:
    """Return the shared default cache.

    Unless it was replaced with :func:`set_cache`, the default cache is
    created and opened by the first call. It keeps its entries in memory
    for 300 seconds, with the :class:`~persista.store.PickleCodec`, so it
    caches any value that can be pickled, with its type.

    Returns:
        The shared default :class:`~persista.cache.cache.Cache`
        instance, used by :func:`cached`.

    Example:
        ```pycon
        >>> from persista.cache import get_cache
        >>> cache = get_cache()
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting")
        'hello'

        ```
    """
    cache = _state.get("cache")
    if cache is None:
        with _lock:
            # Another thread may have set it while this one was waiting.
            cache = _state.get("cache")
            if cache is None:
                cache = _state["cache"] = _make_default_cache()
    return cache


def set_cache(cache: Cache) -> None:
    """Replace the shared default cache.

    The cache is not opened, and the cache that it replaces is not
    closed.

    Args:
        cache: The :class:`~persista.cache.cache.Cache` instance to
            install as the new shared default, in place of the one
            returned by :func:`get_cache`.

    Example:
        ```pycon
        >>> from persista.cache import Cache, get_cache, set_cache
        >>> previous = get_cache()
        >>> new_cache = Cache(default_ttl=60)
        >>> new_cache.open()
        >>> set_cache(new_cache)
        >>> get_cache().default_ttl
        60
        >>> set_cache(previous)  # restore the previous default cache

        ```
    """
    with _lock:
        _state["cache"] = cache


def cached(
    *,
    ttl: float | None = DEFAULT,
    ignore: Collection[str] = (),
    key: Callable[..., str] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Cache a function's return values in the shared default cache.

    This is :meth:`~persista.cache.cache.Cache.memoize` on the cache
    returned by :func:`get_cache` at the time of each call, so replacing
    the shared cache with :func:`set_cache` also changes where the
    functions that are already decorated store their results. Works on
    both sync and ``async def`` functions.

    Args:
        ttl: The time-to-live, in seconds, of the cached results.
            Defaults to the ``default_ttl`` of the cache. See
            :meth:`~persista.cache.cache.Cache.set`.
        ignore: The names of the parameters to leave out of the key. See
            :meth:`~persista.cache.cache.Cache.memoize`.
        key: A function of the call that returns its key. See
            :meth:`~persista.cache.cache.Cache.memoize`.

    Returns:
        A decorator that wraps a function with caching.

    Raises:
        TypeError: If ``ignore`` is a ``str``. See
            :meth:`~persista.cache.cache.Cache.memoize` for the errors of
            the decorator.
        ValueError: If ``ttl`` is negative or ``NaN``, or if ``ignore`` and
            ``key`` are both given.

    Example:
        ```pycon
        >>> from persista.cache import cached
        >>> calls = []
        >>> @cached(ttl=60)
        ... def square(x):
        ...     calls.append(x)
        ...     return x * x
        ...
        >>> square(4)
        16
        >>> square(x=4)  # the same call: served from the cache
        16
        >>> calls
        [4]

        ```
    """
    return memoize_with(get_cache, ttl=ttl, ignore=ignore, key=key)
