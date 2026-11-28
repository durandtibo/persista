r"""Provide validation helpers for the arguments of
:class:`~persista.store.BaseStore` methods."""

from __future__ import annotations

__all__ = [
    "ON_CONFLICT_VALUES",
    "check_is_closed",
    "check_is_open",
    "normalize_on_conflict",
    "validate_batch_size",
    "validate_field_name",
    "validate_key",
    "validate_keys",
    "validate_namespace",
    "validate_on_conflict",
    "validate_table_name",
]

import re
from typing import TYPE_CHECKING, cast, get_args

from persista.store.types import OnConflict

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.store.base import BaseStore

ON_CONFLICT_VALUES = sorted(get_args(OnConflict))

_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_on_conflict(on_conflict: str) -> OnConflict:
    """Normalize and validate an ``on_conflict`` value.

    Args:
        on_conflict: The value to normalize. Matched
            case-insensitively, with leading/trailing whitespace
            stripped.

    Returns:
        The normalized value, one of :data:`ON_CONFLICT_VALUES`.

    Raises:
        ValueError: If the normalized value is not one of
            :data:`ON_CONFLICT_VALUES`.

    Example:
        ```pycon
        >>> from persista.store.validation import normalize_on_conflict
        >>> normalize_on_conflict(" Overwrite ")
        'overwrite'

        ```
    """
    normalized = on_conflict.lower().strip()
    validate_on_conflict(normalized)
    return cast("OnConflict", normalized)


def validate_on_conflict(on_conflict: str) -> None:
    """Validate that a value is a valid ``on_conflict`` strategy.

    Args:
        on_conflict: The value to validate.

    Raises:
        ValueError: If ``on_conflict`` is not one of
            :data:`ON_CONFLICT_VALUES`.

    Example:
        ```pycon
        >>> from persista.store.validation import validate_on_conflict
        >>> validate_on_conflict("overwrite")

        ```
    """
    if on_conflict not in ON_CONFLICT_VALUES:
        msg = f"Invalid on_conflict value: {on_conflict!r}. Valid values are: {ON_CONFLICT_VALUES}"
        raise ValueError(msg)


def validate_key(key: str) -> str:
    """Validate a key of a store.

    Args:
        key: The key to validate.

    Returns:
        The key. An instance of a subclass of ``str`` (for example a
        ``str`` enum) is converted to a ``str``.

    Raises:
        TypeError: If ``key`` is not a ``str``.

    Example:
        ```pycon
        >>> from persista.store.validation import validate_key
        >>> validate_key("user:1")
        'user:1'
        >>> validate_key(1)
        Traceback (most recent call last):
            ...
        TypeError: A key must be a str, not int: 1

        ```
    """
    if type(key) is str:
        return key
    if not isinstance(key, str):
        msg = f"A key must be a str, not {type(key).__name__}: {key!r}"
        raise TypeError(msg)
    return str.__str__(key)


def validate_keys(keys: Iterable[str]) -> list[str]:
    """Validate several keys of a store.

    Args:
        keys: The keys to validate. It is not modified.

    Returns:
        A new list with the keys, in the same order and with the same
        duplicates. See :func:`validate_key`.

    Raises:
        TypeError: If ``keys`` is a single ``str``, or if a key is not a
            ``str``.

    Example:
        ```pycon
        >>> from persista.store.validation import validate_keys
        >>> validate_keys(("user:1", "user:2"))
        ['user:1', 'user:2']

        ```
    """
    if isinstance(keys, str):
        msg = f"keys must be a list of keys, not a single str: {keys!r}"
        raise TypeError(msg)
    keys = list(keys)
    # Fast path: nothing to convert or to reject.
    if set(map(type, keys)) <= {str}:
        return keys
    return [validate_key(key) for key in keys]


def validate_namespace(namespace: str) -> None:
    """Validate the namespace of a store whose keys are
    ``<namespace>:v:<key>`` and ``<namespace>:keys``, such as
    :class:`~persista.store.RedisStore`.

    With these rules, two different namespaces never produce the same
    key, even if one starts with the other.

    Args:
        namespace: The namespace to validate.

    Raises:
        TypeError: If ``namespace`` is not a ``str``.
        ValueError: If ``namespace`` is empty, contains ``":v:"``, ends
            with ``":v"``, or contains a lone surrogate.

    Example:
        ```pycon
        >>> from persista.store.validation import validate_namespace
        >>> validate_namespace("app:cache")
        >>> validate_namespace("app:v")
        Traceback (most recent call last):
            ...
        ValueError: Invalid namespace: 'app:v'. A namespace must not contain ':v:' or end with ':v'

        ```
    """
    if not isinstance(namespace, str):
        msg = f"A namespace must be a str, not {type(namespace).__name__}: {namespace!r}"
        raise TypeError(msg)
    if not namespace:
        msg = "A namespace must not be empty"
        raise ValueError(msg)
    # ":v:" separates the namespace from the key of a value.
    if ":v:" in namespace or namespace.endswith(":v"):
        msg = (
            f"Invalid namespace: {namespace!r}. A namespace must not contain ':v:' or end with ':v'"
        )
        raise ValueError(msg)
    try:
        namespace.encode()
    except UnicodeEncodeError as exc:
        msg = f"A namespace must be valid Unicode, but it has a lone surrogate: {namespace!r}"
        raise ValueError(msg) from exc


def validate_field_name(name: str) -> None:
    """Validate that a value filter field name is safe to interpolate
    into a SQL fragment.

    ``BaseStore.filter`` implementations build SQL by interpolating
    the field name directly (only the filter value is passed as a
    bound parameter), so an unrestricted field name is a SQL
    injection vector. Restricting it to a simple identifier shape
    closes that off.

    Args:
        name: The field name to validate.

    Raises:
        ValueError: If ``name`` is not a valid identifier (letters,
            digits, underscores, not starting with a digit).

    Example:
        ```pycon
        >>> from persista.store.validation import validate_field_name
        >>> validate_field_name("user_id")
        >>> validate_field_name("bad name")
        Traceback (most recent call last):
            ...
        ValueError: Invalid filter field name: 'bad name'. Field names must match '^[A-Za-z_][A-Za-z0-9_]*$'

        ```
    """
    if not _FIELD_NAME_PATTERN.match(name):
        msg = f"Invalid filter field name: {name!r}. Field names must match {_FIELD_NAME_PATTERN.pattern!r}"
        raise ValueError(msg)


def validate_table_name(name: str) -> None:
    """Validate that a value is safe to interpolate into SQL as a table
    name.

    Args:
        name: The table name to validate.

    Raises:
        ValueError: If ``name`` is not a valid identifier (letters,
            digits, underscores, not starting with a digit).

    Example:
        ```pycon
        >>> from persista.store.validation import validate_table_name
        >>> validate_table_name("my_table")

        ```
    """
    if not _FIELD_NAME_PATTERN.match(name):
        msg = (
            f"Invalid table name: {name!r}. Table names must match {_FIELD_NAME_PATTERN.pattern!r}"
        )
        raise ValueError(msg)


def validate_batch_size(batch_size: int) -> None:
    """Validate that a value is a valid ``batch_size`` strategy.

    Args:
        batch_size: The value to validate.

    Raises:
        ValueError: If ``batch_size`` is invalid.

    Example:
        ```pycon
        >>> from persista.store.validation import validate_batch_size
        >>> validate_batch_size(32)

        ```
    """
    if batch_size < 1:
        msg = f"batch_size must be a positive integer, got {batch_size}"
        raise ValueError(msg)


def check_is_open(store: BaseStore) -> None:
    """Check that a store is open, raising if it is not.

    Args:
        store: The :class:`~persista.store.base.BaseStore` to check.

    Raises:
        RuntimeError: If ``store`` is closed.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.validation import check_is_open
        >>> store = InMemoryStore()
        >>> with store:
        ...     check_is_open(store)
        ...

        ```
    """
    if store.closed:
        msg = (
            f"{type(store).__name__} is not open; call open()/aopen() or use it as a "
            "context manager."
        )
        raise RuntimeError(msg)


def check_is_closed(store: BaseStore) -> None:
    """Check that a store is closed, raising if it is not.

    Args:
        store: The :class:`~persista.store.base.BaseStore` to check.

    Raises:
        RuntimeError: If ``store`` is open.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.validation import check_is_closed
        >>> store = InMemoryStore()
        >>> check_is_closed(store)

        ```
    """
    if not store.closed:
        msg = f"{type(store).__name__} is not closed; call close()/aclose() first."
        raise RuntimeError(msg)
