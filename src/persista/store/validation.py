r"""Provide validation helpers for the ``on_conflict`` parameter used by
:class:`~persista.store.base.BaseStore` write methods."""

from __future__ import annotations

__all__ = [
    "ON_CONFLICT_VALUES",
    "aresolve_conflicts",
    "normalize_on_conflict",
    "resolve_conflicts",
    "validate_batch_size",
    "validate_field_name",
    "validate_on_conflict",
    "validate_table_name",
]

import re
from typing import TYPE_CHECKING, Any, get_args

from persista.store.types import OnConflict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

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
    """
    normalized = on_conflict.lower().strip()
    validate_on_conflict(normalized)
    return normalized


def validate_on_conflict(on_conflict: str) -> None:
    """Validate that a value is a valid ``on_conflict`` strategy.

    Args:
        on_conflict: The value to validate.

    Raises:
        ValueError: If ``on_conflict`` is not one of
            :data:`ON_CONFLICT_VALUES`.
    """
    if on_conflict not in ON_CONFLICT_VALUES:
        msg = f"Invalid on_conflict value: {on_conflict!r}. Valid values are: {ON_CONFLICT_VALUES}"
        raise ValueError(msg)


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
    """
    if not _FIELD_NAME_PATTERN.match(name):
        msg = (
            f"Invalid table name: {name!r}. Table names must match {_FIELD_NAME_PATTERN.pattern!r}"
        )
        raise ValueError(msg)


def resolve_conflicts(
    items: Mapping[str, dict[str, Any]],
    on_conflict: OnConflict,
    contains_many: Callable[[list[str]], list[bool]],
    get: Callable[[str], dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    """Resolve ``items`` against existing keys for a non-``"overwrite"``
    ``on_conflict`` strategy.

    Shared by every :class:`~persista.store.base.BaseStore` backend's
    ``set_many``: callers handle the ``"overwrite"`` case themselves
    (writing ``items`` as-is, without needing to check for conflicts)
    and use this helper for ``"raise"``/``"skip"``/``"merge"``.

    Args:
        items: The values to write, keyed by their unique key.
        on_conflict: The conflict strategy to apply; must not be
            ``"overwrite"``. See
            :meth:`~persista.store.base.BaseStore.set` for the meaning
            of each option.
        contains_many: Callable returning, for a list of keys, whether
            each one already exists in the store (same shape as
            :meth:`~persista.store.base.BaseStore.contains_many`).
        get: Callable returning the current value for a single key, or
            ``None`` if absent (same shape as
            :meth:`~persista.store.base.BaseStore.get`).

    Returns:
        The subset of ``items`` (with conflicting values merged in, for
        ``"merge"``) that should actually be written to the store.

    Raises:
        KeyError: If ``on_conflict`` is ``"raise"`` and any key in
            ``items`` already exists.
    """
    keys = list(items)
    found = contains_many(keys)
    conflicts = {key for key, exists in zip(keys, found, strict=True) if exists}
    if conflicts and on_conflict == "raise":
        msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
        raise KeyError(msg)

    to_write: dict[str, dict[str, Any]] = {}
    for key, value in items.items():
        if key in conflicts:
            if on_conflict == "skip":
                continue
            to_write[key] = {**(get(key) or {}), **value}
            continue
        to_write[key] = value
    return to_write


async def aresolve_conflicts(
    items: Mapping[str, dict[str, Any]],
    on_conflict: OnConflict,
    contains_many: Callable[[list[str]], Awaitable[list[bool]]],
    get: Callable[[str], Awaitable[dict[str, Any] | None]],
) -> dict[str, dict[str, Any]]:
    """Async equivalent of :func:`resolve_conflicts`."""
    keys = list(items)
    found = await contains_many(keys)
    conflicts = {key for key, exists in zip(keys, found, strict=True) if exists}
    if conflicts and on_conflict == "raise":
        msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
        raise KeyError(msg)

    to_write: dict[str, dict[str, Any]] = {}
    for key, value in items.items():
        if key in conflicts:
            if on_conflict == "skip":
                continue
            to_write[key] = {**(await get(key) or {}), **value}
            continue
        to_write[key] = value
    return to_write


def validate_batch_size(batch_size: int) -> None:
    """Validate that a value is a valid ``batch_size`` strategy.

    Args:
        batch_size: The value to validate.

    Raises:
        ValueError: If ``batch_size`` is invalid.
    """
    if batch_size < 1:
        msg = f"batch_size must be a positive integer, got {batch_size}"
        raise ValueError(msg)
