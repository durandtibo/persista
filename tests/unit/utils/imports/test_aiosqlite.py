from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    aiosqlite_available,
    check_aiosqlite,
    is_aiosqlite_available,
    raise_aiosqlite_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.aiosqlite"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_aiosqlite_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


#####################
#     aiosqlite     #
#####################


def test_check_aiosqlite_with_package() -> None:
    with patch(f"{MODULE}.is_aiosqlite_available", lambda: True):
        check_aiosqlite()


def test_check_aiosqlite_without_package() -> None:
    with (
        patch(f"{MODULE}.is_aiosqlite_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'aiosqlite' package is required but not installed."),
    ):
        check_aiosqlite()


def test_is_aiosqlite_available() -> None:
    assert isinstance(is_aiosqlite_available(), bool)


def test_aiosqlite_available_with_package() -> None:
    with patch(f"{MODULE}.is_aiosqlite_available", lambda: True):
        fn = aiosqlite_available(my_function)
        assert fn(2) == 44


def test_aiosqlite_available_without_package() -> None:
    with patch(f"{MODULE}.is_aiosqlite_available", lambda: False):
        fn = aiosqlite_available(my_function)
        assert fn(2) is None


def test_aiosqlite_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_aiosqlite_available", lambda: True):

        @aiosqlite_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_aiosqlite_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_aiosqlite_available", lambda: False):

        @aiosqlite_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_aiosqlite_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'aiosqlite' package is required but not installed."):
        raise_aiosqlite_missing_error()
