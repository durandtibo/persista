from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_lmdb,
    is_lmdb_available,
    lmdb_available,
    raise_lmdb_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.lmdb"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_lmdb_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


################
#     lmdb     #
################


def test_check_lmdb_with_package() -> None:
    with patch(f"{MODULE}.is_lmdb_available", lambda: True):
        check_lmdb()


def test_check_lmdb_without_package() -> None:
    with (
        patch(f"{MODULE}.is_lmdb_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'lmdb' package is required but not installed."),
    ):
        check_lmdb()


def test_is_lmdb_available() -> None:
    assert isinstance(is_lmdb_available(), bool)


def test_lmdb_available_with_package() -> None:
    with patch(f"{MODULE}.is_lmdb_available", lambda: True):
        fn = lmdb_available(my_function)
        assert fn(2) == 44


def test_lmdb_available_without_package() -> None:
    with patch(f"{MODULE}.is_lmdb_available", lambda: False):
        fn = lmdb_available(my_function)
        assert fn(2) is None


def test_lmdb_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_lmdb_available", lambda: True):

        @lmdb_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_lmdb_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_lmdb_available", lambda: False):

        @lmdb_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_lmdb_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'lmdb' package is required but not installed."):
        raise_lmdb_missing_error()
