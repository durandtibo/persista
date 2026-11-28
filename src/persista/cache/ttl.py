r"""Provide the rule of the time-to-live (TTL) of the cache entries."""

from __future__ import annotations

__all__ = ["DEFAULT", "validate_ttl"]

from typing import Any


class _Default:
    """Represent the type of :data:`DEFAULT`."""

    def __repr__(self) -> str:
        return "DEFAULT"


DEFAULT: Any = _Default()
"""Sentinel for a ``ttl`` argument that is not given: the
``default_ttl`` of the cache applies."""


def validate_ttl(ttl: float | None, *, name: str = "ttl") -> None:
    r"""Check a time-to-live, in seconds.

    A time-to-live is ``None`` (the entry never expires), ``0`` (the entry
    is deleted instead of written) or a positive number.

    Args:
        ttl: The time-to-live to check.
        name: The name of the argument, used in the error message.

    Raises:
        ValueError: If ``ttl`` is negative or ``NaN``.
        TypeError: If ``ttl`` cannot be compared with a number.

    Example:
        ```pycon
        >>> from persista.cache.ttl import validate_ttl
        >>> validate_ttl(None)
        >>> validate_ttl(0)
        >>> validate_ttl(-1)
        Traceback (most recent call last):
            ...
        ValueError: ttl must be None, 0 or positive, got -1

        ```
    """
    # "not ttl >= 0" rather than "ttl < 0": every comparison with NaN is
    # false.
    if ttl is not None and not ttl >= 0:
        msg = f"{name} must be None, 0 or positive, got {ttl}"
        raise ValueError(msg)
