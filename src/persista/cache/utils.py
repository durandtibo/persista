r"""Provide helper functions for caches."""

from __future__ import annotations

__all__ = ["make_key"]

import json
from typing import Any

from coola.hashing import hash_bytes


def make_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Derive a stable cache key from a function name and its call
    arguments.

    ``func_name``, ``args``, and ``kwargs`` are JSON-serialized (with
    ``kwargs`` keys sorted, so key order doesn't affect the result)
    and hashed. ``args`` and the values in ``kwargs`` must be
    JSON-serializable.

    Args:
        func_name: The name of the function being cached, typically
            its ``__qualname__``.
        args: The positional arguments the function was called with.
            Must be JSON-serializable.
        kwargs: The keyword arguments the function was called with.
            Must be JSON-serializable.

    Returns:
        A hash of ``func_name``, ``args``, and ``kwargs``, stable
        across calls with equal arguments regardless of ``kwargs``
        order.

    Raises:
        TypeError: If ``args`` or ``kwargs`` contains a value that is
            not JSON-serializable.

    Example:
        ```pycon
        >>> from persista.cache.utils import make_key
        >>> make_key("add", (1, 2), {}) == make_key("add", (1, 2), {})
        True
        >>> make_key("add", (), {"a": 1, "b": 2}) == make_key("add", (), {"b": 2, "a": 1})
        True
        >>> make_key("add", (1, 2), {}) == make_key("add", (1, 3), {})
        False

        ```
    """
    raw = json.dumps({"func": func_name, "args": args, "kwargs": kwargs}, sort_keys=True)
    return hash_bytes(raw.encode())
