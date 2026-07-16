r"""Contain utilities for optional dependencies."""

from __future__ import annotations

__all__ = [
    "check_duckdb",
    "check_faker",
    "duckdb_available",
    "faker_available",
    "is_duckdb_available",
    "is_faker_available",
    "raise_duckdb_missing_error",
    "raise_faker_missing_error",
]

from persista.utils.imports.duckdb import (
    check_duckdb,
    duckdb_available,
    is_duckdb_available,
    raise_duckdb_missing_error,
)
from persista.utils.imports.faker import (
    check_faker,
    faker_available,
    is_faker_available,
    raise_faker_missing_error,
)
