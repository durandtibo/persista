r"""Provide module-level access to shared default caches."""

from __future__ import annotations

__all__ = [
    "async_cached",
    "cached",
    "get_cache",
    "set_cache",
]


import functools
import inspect
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.cache import _UNSET, Cache
from persista.cache.utils import make_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

T = TypeVar("T")

_state = {"cache": Cache(default_ttl=300)}


def get_cache() -> Cache:
    """Return the shared default cache.

    Returns:
        The shared default :class:`~persista.cache.cache.Cache`
        instance, used by :func:`cached` when no explicit cache is
        given.

    Example:
        ```pycon
        >>> from persista.cache.interface import get_cache
        >>> cache = get_cache()
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting")
        'hello'

        ```
    """
    return _state["cache"]


def set_cache(cache: Cache) -> None:
    """Replace the shared default cache.

    Args:
        cache: The :class:`~persista.cache.cache.Cache` instance to
            install as the new shared default, in place of the one
            returned by :func:`get_cache`.

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> from persista.cache import get_cache, set_cache
        >>> set_cache(Cache(default_ttl=60))
        >>> get_cache().default_ttl
        60

        ```
    """
    _state["cache"] = cache


def cached(
    ttl: float | None = _UNSET,
    strategy: str = "json",
    ignore_non_serializable: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Cache a function's return values in the shared default cache.

    Works on both sync and async functions (``async def``), by
    looking up :func:`get_cache` on every call, so replacing the
    shared cache via :func:`set_cache` also changes where
    already-decorated functions store their results.

    The cache key is derived from the decorated function's qualified
    name (``__qualname__``) and call arguments, via
    :func:`~persista.cache.utils.make_key`.

    Args:
        ttl: The time-to-live, in seconds, applied to cached results.
            Defaults to the cache's ``default_ttl`` when not given.
            See :meth:`~persista.cache.cache.Cache.set`.
        strategy: The serialization strategy used to compute the
            cache key. Either ``"json"`` or ``"pickle"``. See
            :func:`~persista.cache.utils.make_key`.
        ignore_non_serializable: If ``True``, positional arguments and
            keyword argument values that are not serializable with
            ``strategy`` are dropped before computing the key, instead
            of raising an error. See
            :func:`~persista.cache.utils.make_key`.

    Returns:
        A decorator that wraps a function with caching.

    Raises:
        ValueError: If ``ttl`` is negative.

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
                cache = get_cache()
                key = make_key(
                    func.__qualname__,
                    args,
                    kwargs,
                    strategy=strategy,
                    ignore_non_serializable=ignore_non_serializable,
                )
                return await cache.aget_or_compute(key, func, args, kwargs, ttl=ttl)

            return async_wrapper  # pyright: ignore[reportReturnType]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            cache = get_cache()
            key = make_key(
                func.__qualname__,
                args,
                kwargs,
                strategy=strategy,
                ignore_non_serializable=ignore_non_serializable,
            )
            return cache.get_or_compute(key, func, args, kwargs, ttl=ttl)

        return wrapper

    return decorator


def async_cached(
    ttl: float | None = _UNSET,
    strategy: str = "json",
    ignore_non_serializable: bool = False,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Cache an async function's return values in the shared default
    cache.

    Looks up :func:`get_cache` on every call, so replacing the
    shared cache via :func:`set_cache` also changes where
    already-decorated functions store their results.

    The cache key is derived from the decorated function's qualified
    name (``__qualname__``) and call arguments, via
    :func:`~persista.cache.utils.make_key`.

    Args:
        ttl: The time-to-live, in seconds, applied to cached results.
            Defaults to the cache's ``default_ttl`` when not given.
            See :meth:`~persista.cache.cache.Cache.aset`.
        strategy: The serialization strategy used to compute the
            cache key. Either ``"json"`` or ``"pickle"``. See
            :func:`~persista.cache.utils.make_key`.
        ignore_non_serializable: If ``True``, positional arguments and
            keyword argument values that are not serializable with
            ``strategy`` are dropped before computing the key, instead
            of raising an error. See
            :func:`~persista.cache.utils.make_key`.

    Returns:
        A decorator that wraps an async function with caching.

    Raises:
        ValueError: If ``ttl`` is negative.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.cache import async_cached
        >>> calls = []
        >>> @async_cached(ttl=60)
        ... async def cube(x):
        ...     calls.append(x)
        ...     return x * x * x
        ...
        >>> async def main():
        ...     print(await cube(4))
        ...     print(await cube(4))  # served from the cache, not re-computed
        ...
        >>> asyncio.run(main())
        64
        64
        >>> calls
        [4]

        ```
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache()
            key = make_key(
                func.__qualname__,
                args,
                kwargs,
                strategy=strategy,
                ignore_non_serializable=ignore_non_serializable,
            )
            return await cache.aget_or_compute(key, func, args, kwargs, ttl=ttl)

        return wrapper

    return decorator
