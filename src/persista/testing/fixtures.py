r"""Define some pytest fixtures for testing.

`pytest` is required to use these fixtures.
"""

from __future__ import annotations

__all__ = [
    "duckdb_available",
    "duckdb_not_available",
    "faker_available",
    "faker_not_available",
    "psycopg_available",
    "psycopg_not_available",
]

import pytest

from persista.utils.imports import (
    is_duckdb_available,
    is_faker_available,
    is_psycopg_available,
)

duckdb_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_duckdb_available(), reason="Requires duckdb"
)
duckdb_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_duckdb_available(), reason="Skip if duckdb is available"
)

faker_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_faker_available(), reason="Requires faker"
)
faker_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_faker_available(), reason="Skip if faker is available"
)

psycopg_available: pytest.MarkDecorator = pytest.mark.skipif(
    not is_psycopg_available(), reason="Requires psycopg"
)
psycopg_not_available: pytest.MarkDecorator = pytest.mark.skipif(
    is_psycopg_available(), reason="Skip if psycopg is available"
)
