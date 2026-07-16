r"""Provide validation helpers for the ``on_conflict`` parameter used by
:class:`~persista.store.base.BaseStore` write methods."""

from __future__ import annotations

__all__ = [
    "ON_CONFLICT_VALUES",
    "normalize_on_conflict",
    "validate_batch_size",
    "validate_on_conflict",
]

from typing import cast, get_args

from persista.store.types import OnConflict

ON_CONFLICT_VALUES = sorted(get_args(OnConflict))


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
    return cast("OnConflict", normalized)


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
