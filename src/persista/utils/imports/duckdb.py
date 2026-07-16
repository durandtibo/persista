r"""Contain utilities for optional duckdb dependency."""

from __future__ import annotations

__all__ = [
    "check_duckdb",
    "duckdb_available",
    "is_duckdb_available",
    "raise_duckdb_missing_error",
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


def check_duckdb() -> None:
    r"""Check if the ``duckdb`` package is installed.

    Raises:
        RuntimeError: if the ``duckdb`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_duckdb
        >>> check_duckdb()

        ```
    """
    if not is_duckdb_available():
        raise_duckdb_missing_error()


@lru_cache(1)
def is_duckdb_available() -> bool:
    r"""Indicate if the ``duckdb`` package is installed or not.

    Returns:
        ``True`` if ``duckdb`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_duckdb_available
        >>> is_duckdb_available()

        ```
    """
    return package_available("duckdb")


def duckdb_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``duckdb``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``duckdb`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import duckdb_available
        >>> @duckdb_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_duckdb_available)


def raise_duckdb_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``duckdb`` package is
    missing."""
    raise_package_missing_error("duckdb", "duckdb")
