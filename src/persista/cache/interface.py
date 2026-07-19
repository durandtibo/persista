r"""Provide module-level access to a shared default ``TTLCache``."""

from __future__ import annotations

__all__ = ["cached", "get_ttl_cache", "set_ttl_cache"]


import functools
import inspect
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.ttl import TTLCache
from persista.cache.utils import make_key

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")

_state = {"cache": TTLCache()}


def get_ttl_cache() -> TTLCache:
    """Return the shared default cache.

    Returns:
        The shared default :class:`~persista.cache.ttl.TTLCache`
        instance, used by :func:`cached` when no explicit cache is
        given.

    Example:
        ```pycon
        >>> from persista.cache.interface import get_ttl_cache
        >>> cache = get_ttl_cache()
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting")
        'hello'

        ```
    """
    return _state["cache"]


def set_ttl_cache(cache: TTLCache) -> None:
    """Replace the shared default cache.

    Args:
        cache: The :class:`~persista.cache.ttl.TTLCache` instance to
            install as the new shared default, in place of the one
            returned by :func:`get_ttl_cache`.

    Example:
        ```pycon
        >>> from persista.cache import TTLCache
        >>> from persista.cache import get_ttl_cache, set_ttl_cache
        >>> set_ttl_cache(TTLCache(default_ttl=60))
        >>> get_ttl_cache().default_ttl
        60

        ```
    """
    _state["cache"] = cache


def cached(ttl: int | None = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Cache a function's return values in the shared default cache.

    Works on both sync and async functions (``async def``), by
    delegating to :meth:`~persista.cache.ttl.TTLCache.memoize` on the
    cache returned by :func:`get_ttl_cache` at call time, so replacing
    the shared cache via :func:`set_ttl_cache` also changes where
    already-decorated functions store their results.

    Args:
        ttl: The time-to-live, in seconds, applied to cached results.
            Defaults to the cache's ``default_ttl``. Must be positive.

    Returns:
        A decorator that wraps a function with caching.

    Raises:
        ValueError: If ``ttl`` is not positive.

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
        >>> square(4)  # served from the cache, not re-computed
        16
        >>> calls
        [4]

        ```
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                cache = get_ttl_cache()
                key = make_key(func.__qualname__, args, kwargs)
                result = cache.get(key)
                if result is not None:
                    return result
                result = await func(*args, **kwargs)
                cache.set(key, result, ttl=ttl)
                return result

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            cache = get_ttl_cache()
            key = make_key(func.__qualname__, args, kwargs)
            result = cache.get(key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result

        return wrapper

    return decorator
