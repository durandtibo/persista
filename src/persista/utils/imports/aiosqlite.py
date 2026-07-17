r"""Contain utilities for optional aiosqlite dependency."""

from __future__ import annotations

__all__ = [
    "aiosqlite_available",
    "check_aiosqlite",
    "is_aiosqlite_available",
    "raise_aiosqlite_missing_error",
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


def check_aiosqlite() -> None:
    r"""Check if the ``aiosqlite`` package is installed.

    Raises:
        RuntimeError: if the ``aiosqlite`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_aiosqlite
        >>> check_aiosqlite()

        ```
    """
    if not is_aiosqlite_available():
        raise_aiosqlite_missing_error()


@lru_cache(1)
def is_aiosqlite_available() -> bool:
    r"""Indicate if the ``aiosqlite`` package is installed or not.

    Returns:
        ``True`` if ``aiosqlite`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_aiosqlite_available
        >>> is_aiosqlite_available()

        ```
    """
    return package_available("aiosqlite")


def aiosqlite_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``aiosqlite``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``aiosqlite`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import aiosqlite_available
        >>> @aiosqlite_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_aiosqlite_available)


def raise_aiosqlite_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``aiosqlite`` package is
    missing."""
    raise_package_missing_error("aiosqlite", "aiosqlite")
