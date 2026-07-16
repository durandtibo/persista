from __future__ import annotations

import pytest

from persista.testing.fixtures import duckdb_available, duckdb_not_available
from persista.utils.imports import check_duckdb, is_duckdb_available

##################
#     duckdb     #
##################


@duckdb_available
def test_check_duckdb_with_package() -> None:
    check_duckdb()


@duckdb_not_available
def test_check_duckdb_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'duckdb' package is required but not installed."):
        check_duckdb()


@duckdb_available
def test_is_duckdb_available_true() -> None:
    assert is_duckdb_available()


@duckdb_not_available
def test_is_duckdb_available_false() -> None:
    assert not is_duckdb_available()
