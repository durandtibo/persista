from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_duckdb,
    duckdb_available,
    is_duckdb_available,
    raise_duckdb_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.duckdb"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_duckdb_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


##################
#     duckdb     #
##################


def test_check_duckdb_with_package() -> None:
    with patch(f"{MODULE}.is_duckdb_available", lambda: True):
        check_duckdb()


def test_check_duckdb_without_package() -> None:
    with (
        patch(f"{MODULE}.is_duckdb_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'duckdb' package is required but not installed."),
    ):
        check_duckdb()


def test_is_duckdb_available() -> None:
    assert isinstance(is_duckdb_available(), bool)


def test_duckdb_available_with_package() -> None:
    with patch(f"{MODULE}.is_duckdb_available", lambda: True):
        fn = duckdb_available(my_function)
        assert fn(2) == 44


def test_duckdb_available_without_package() -> None:
    with patch(f"{MODULE}.is_duckdb_available", lambda: False):
        fn = duckdb_available(my_function)
        assert fn(2) is None


def test_duckdb_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_duckdb_available", lambda: True):

        @duckdb_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_duckdb_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_duckdb_available", lambda: False):

        @duckdb_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_duckdb_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'duckdb' package is required but not installed."):
        raise_duckdb_missing_error()
