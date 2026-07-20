r"""Provide helper functions for caches."""

from __future__ import annotations

__all__ = ["make_json_key", "make_key", "make_pickle_key"]

import json
import pickle
from typing import Any

from coola.hashing import hash_bytes


def _is_json_serializable(value: Any) -> bool:
    """Indicate whether a value can be JSON-serialized.

    Args:
        value: The value to check.

    Returns:
        ``True`` if ``value`` is JSON-serializable, otherwise ``False``.
    """
    try:
        json.dumps(value)
    except TypeError:
        return False
    return True


def make_json_key(
    func_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ignore_non_serializable: bool = False,
) -> str:
    """Derive a stable cache key from a function name and its call
    arguments.

    ``func_name``, ``args``, and ``kwargs`` are JSON-serialized (with
    ``kwargs`` keys sorted, so key order doesn't affect the result)
    and hashed. ``args`` and the values in ``kwargs`` must be
    JSON-serializable, unless ``ignore_non_serializable`` is set.

    Args:
        func_name: The name of the function being cached, typically
            its ``__qualname__``.
        args: The positional arguments the function was called with.
            Must be JSON-serializable, unless ``ignore_non_serializable``
            is set.
        kwargs: The keyword arguments the function was called with.
            Must be JSON-serializable, unless ``ignore_non_serializable``
            is set.
        ignore_non_serializable: If ``True``, positional arguments and
            keyword argument values that are not JSON-serializable are
            dropped before computing the key, instead of raising an
            error. This means calls that only differ in a non-serializable
            argument (e.g. a logger or a client instance) map to the
            same key.

    Returns:
        A hash of ``func_name``, ``args``, and ``kwargs``, stable
        across calls with equal arguments regardless of ``kwargs``
        order.

    Raises:
        TypeError: If ``args`` or ``kwargs`` contains a value that is
            not JSON-serializable and ``ignore_non_serializable`` is
            ``False``.

    Example:
        ```pycon
        >>> from persista.cache.utils import make_json_key
        >>> make_json_key("add", (1, 2), {}) == make_json_key("add", (1, 2), {})
        True
        >>> make_json_key("add", (), {"a": 1, "b": 2}) == make_json_key("add", (), {"b": 2, "a": 1})
        True
        >>> make_json_key("add", (1, 2), {}) == make_json_key("add", (1, 3), {})
        False

        ```
    """
    if ignore_non_serializable:
        args = tuple(a for a in args if _is_json_serializable(a))
        kwargs = {k: v for k, v in kwargs.items() if _is_json_serializable(v)}
    raw = json.dumps({"func": func_name, "args": args, "kwargs": kwargs}, sort_keys=True)
    return hash_bytes(raw.encode())


def _is_picklable(value: Any) -> bool:
    """Indicate whether a value can be pickled.

    Args:
        value: The value to check.

    Returns:
        ``True`` if ``value`` is picklable, otherwise ``False``.
    """
    try:
        pickle.dumps(value)
    except (pickle.PicklingError, TypeError, AttributeError):
        return False
    return True


def make_pickle_key(
    func_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    ignore_non_serializable: bool = False,
) -> str:
    """Derive a stable cache key from a function name and its call
    arguments.

    This is similar to ``make_json_key`` but uses ``pickle`` instead of
    ``json`` to serialize ``func_name``, ``args``, and ``kwargs``
    before hashing, so it supports a broader range of argument types
    at the cost of a key that is only stable within a single Python
    version (pickle's format can change across versions).

    Args:
        func_name: The name of the function being cached, typically
            its ``__qualname__``.
        args: The positional arguments the function was called with.
            Must be picklable, unless ``ignore_non_serializable`` is
            set.
        kwargs: The keyword arguments the function was called with.
            Must be picklable, unless ``ignore_non_serializable`` is
            set.
        ignore_non_serializable: If ``True``, positional arguments and
            keyword argument values that are not picklable are
            dropped before computing the key, instead of raising an
            error. This means calls that only differ in a
            non-picklable argument (e.g. a logger or a client
            instance) map to the same key.

    Returns:
        A hash of ``func_name``, ``args``, and ``kwargs``, stable
        across calls with equal arguments regardless of ``kwargs``
        order.

    Raises:
        pickle.PicklingError: If ``args`` or ``kwargs`` contains a
            value that cannot be pickled and ``ignore_non_serializable``
            is ``False``.

    Example:
        ```pycon
        >>> from persista.cache.utils import make_pickle_key
        >>> make_pickle_key("add", (1, 2), {}) == make_pickle_key("add", (1, 2), {})
        True
        >>> make_pickle_key("add", (), {"a": 1, "b": 2}) == make_pickle_key(
        ...     "add", (), {"b": 2, "a": 1}
        ... )
        True
        >>> make_pickle_key("add", (1, 2), {}) == make_pickle_key("add", (1, 3), {})
        False

        ```
    """
    if ignore_non_serializable:
        args = tuple(a for a in args if _is_picklable(a))
        kwargs = {k: v for k, v in kwargs.items() if _is_picklable(v)}
    raw = pickle.dumps((func_name, args, sorted(kwargs.items())))
    return hash_bytes(raw)


def make_key(
    func_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    strategy: str = "pickle",
    ignore_non_serializable: bool = False,
) -> str:
    """Derive a stable cache key from a function name and its call
    arguments, using the given serialization strategy.

    Args:
        func_name: The name of the function being cached, typically
            its ``__qualname__``.
        args: The positional arguments the function was called with.
            Must be serializable with ``strategy``, unless
            ``ignore_non_serializable`` is set.
        kwargs: The keyword arguments the function was called with.
            Must be serializable with ``strategy``, unless
            ``ignore_non_serializable`` is set.
        strategy: The serialization strategy used to compute the key.
            Either ``"json"`` (see ``make_json_key``) or ``"pickle"``
            (see ``make_pickle_key``).
        ignore_non_serializable: If ``True``, positional arguments and
            keyword argument values that are not serializable with
            ``strategy`` are dropped before computing the key, instead
            of raising an error. This means calls that only differ in
            a non-serializable argument (e.g. a logger or a client
            instance) map to the same key.

    Returns:
        A hash of ``func_name``, ``args``, and ``kwargs``, stable
        across calls with equal arguments regardless of ``kwargs``
        order.

    Raises:
        ValueError: If ``strategy`` is not ``"json"`` or ``"pickle"``.
        TypeError: If ``strategy`` is ``"json"`` and ``args`` or
            ``kwargs`` contains a value that is not JSON-serializable
            and ``ignore_non_serializable`` is ``False``.
        pickle.PicklingError: If ``strategy`` is ``"pickle"`` and
            ``args`` or ``kwargs`` contains a value that cannot be
            pickled and ``ignore_non_serializable`` is ``False``.

    Example:
        ```pycon
        >>> from persista.cache.utils import make_key
        >>> make_key("add", (1, 2), {}, strategy="json") == make_key(
        ...     "add", (1, 2), {}, strategy="json"
        ... )
        True
        >>> make_key("add", (1, 2), {}) == make_key("add", (1, 3), {})
        False

        ```
    """
    if strategy == "json":
        return make_json_key(
            func_name, args, kwargs, ignore_non_serializable=ignore_non_serializable
        )
    if strategy == "pickle":
        return make_pickle_key(
            func_name, args, kwargs, ignore_non_serializable=ignore_non_serializable
        )
    msg = f"Unknown strategy: {strategy!r}. Expected 'json' or 'pickle'."
    raise ValueError(msg)
