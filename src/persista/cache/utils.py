r"""Provide helper functions for caches."""

from __future__ import annotations

__all__ = ["make_key"]

import json
from typing import Any

from coola.hashing import hash_bytes


def make_key(func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Derive a stable cache key from a function name and its call
    arguments.

    Args:
        func_name: The name of the function being cached.
        args: The positional arguments the function was called with.
        kwargs: The keyword arguments the function was called with.

    Returns:
        A hash of ``func_name``, ``args``, and ``kwargs``, stable
        across calls with equal arguments regardless of ``kwargs``
        order.
    """
    raw = json.dumps(
        {"func": func_name, "args": args, "kwargs": kwargs},
        sort_keys=True,
        default=str,
    )
    return hash_bytes(raw.encode())
