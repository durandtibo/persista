r"""Contain utilities for optional redis dependency."""

from __future__ import annotations

__all__ = [
    "check_redis",
    "is_redis_available",
    "raise_redis_missing_error",
    "redis_available",
]

from functools import lru_cache
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar

from coola.utils.imports import (
    decorator_package_available,
    package_available,
    raise_package_missing_error,
)

if TYPE_CHECKING:
    from collections.abc import Callable

F = TypeVar("F", bound="Callable[..., Any]")


def check_redis() -> None:
    r"""Check if the ``redis`` package is installed.

    Raises:
        RuntimeError: if the ``redis`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_redis
        >>> check_redis()

        ```
    """
    if not is_redis_available():
        raise_redis_missing_error()


@lru_cache(1)
def is_redis_available() -> bool:
    r"""Indicate if the ``redis`` package is installed or not.

    Returns:
        ``True`` if ``redis`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_redis_available
        >>> is_redis_available()

        ```
    """
    return package_available("redis")


def redis_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``redis``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``redis`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import redis_available
        >>> @redis_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_redis_available)


def raise_redis_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``redis`` package is
    missing."""
    raise_package_missing_error("redis", "redis")
