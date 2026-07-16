r"""Contain utilities for optional faker dependency."""

from __future__ import annotations

__all__ = [
    "check_faker",
    "faker_available",
    "is_faker_available",
    "raise_faker_missing_error",
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


def check_faker() -> None:
    r"""Check if the ``faker`` package is installed.

    Raises:
        RuntimeError: if the ``faker`` package is not installed.

    Example:
        ```pycon
        >>> from persista.utils.imports import check_faker
        >>> check_faker()

        ```
    """
    if not is_faker_available():
        raise_faker_missing_error()


@lru_cache(1)
def is_faker_available() -> bool:
    r"""Indicate if the ``faker`` package is installed or not.

    Returns:
        ``True`` if ``faker`` is available otherwise ``False``.

    Example:
        ```pycon
        >>> from persista.utils.imports import is_faker_available
        >>> is_faker_available()

        ```
    """
    return package_available("faker")


def faker_available(fn: F) -> F:
    r"""Implement a decorator to execute a function only if ``faker``
    package is installed.

    Args:
        fn: The function to execute.

    Returns:
        A wrapper around ``fn`` if ``faker`` package is installed,
            otherwise ``None``.

    Example:
        ```pycon
        >>> from persista.utils.imports import faker_available
        >>> @faker_available
        ... def my_function(n: int = 0) -> int:
        ...     return 42 + n
        ...
        >>> my_function()

        ```
    """
    return decorator_package_available(fn, is_faker_available)


def raise_faker_missing_error() -> NoReturn:
    r"""Raise a RuntimeError to indicate the ``faker`` package is
    missing."""
    raise_package_missing_error("faker", "faker")
