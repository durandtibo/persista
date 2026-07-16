r"""Contain stores."""

from __future__ import annotations

__all__ = [
    "BaseStore",
    "OnConflict",
    "normalize_on_conflict",
    "validate_batch_size",
    "validate_on_conflict",
]

from persista.store.base import BaseStore
from persista.store.types import OnConflict
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_on_conflict,
)
