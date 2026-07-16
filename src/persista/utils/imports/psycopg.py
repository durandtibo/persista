r"""Contain utilities for optional psycopg dependency."""

from __future__ import annotations

__all__ = [
    "check_psycopg",
    "is_psycopg_available",
    "psycopg_available",
    "raise_psycopg_missing_error",
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


def check_psycopg() -> None:
    r"""Check if the ``psycopg`` package is installed.

    Raises:
        RuntimeError: if the ``psycopg`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_psycopg
        >>> check_psycopg()

        ```
    """
    if not is_psycopg_available():
        raise_psycopg_missing_error()


@lru_cache(1)
def is_psycopg_available() -> bool:
    r"""Indicate if the ``psycopg`` package is installed or not.

    Returns:
        ``True`` if ``psycopg`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_psycopg_available
        >>> is_psycopg_available()

        ```
    """
    return package_available("psycopg")


def psycopg_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``psycopg``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``psycopg`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import psycopg_available
        >>> @psycopg_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_psycopg_available)


def raise_psycopg_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``psycopg`` package is
    missing."""
    raise_package_missing_error("psycopg", "psycopg[binary]")
