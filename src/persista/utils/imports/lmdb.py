r"""Contain utilities for optional lmdb dependency."""

from __future__ import annotations

__all__ = [
    "check_lmdb",
    "is_lmdb_available",
    "lmdb_available",
    "raise_lmdb_missing_error",
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


def check_lmdb() -> None:
    r"""Check if the ``lmdb`` package is installed.

    Raises:
        RuntimeError: if the ``lmdb`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_lmdb
        >>> check_lmdb()

        ```
    """
    if not is_lmdb_available():
        raise_lmdb_missing_error()


@lru_cache(1)
def is_lmdb_available() -> bool:
    r"""Indicate if the ``lmdb`` package is installed or not.

    Returns:
        ``True`` if ``lmdb`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_lmdb_available
        >>> is_lmdb_available()

        ```
    """
    return package_available("lmdb")


def lmdb_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``lmdb``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``lmdb`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import lmdb_available
        >>> @lmdb_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_lmdb_available)


def raise_lmdb_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``lmdb`` package is
    missing."""
    raise_package_missing_error("lmdb", "lmdb")
