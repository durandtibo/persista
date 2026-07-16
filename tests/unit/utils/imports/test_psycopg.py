from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_psycopg,
    is_psycopg_available,
    psycopg_available,
    raise_psycopg_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.psycopg"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_psycopg_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


###################
#     psycopg     #
###################


def test_check_psycopg_with_package() -> None:
    with patch(f"{MODULE}.is_psycopg_available", lambda: True):
        check_psycopg()


def test_check_psycopg_without_package() -> None:
    with (
        patch(f"{MODULE}.is_psycopg_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'psycopg' package is required but not installed."),
    ):
        check_psycopg()


def test_is_psycopg_available() -> None:
    assert isinstance(is_psycopg_available(), bool)


def test_psycopg_available_with_package() -> None:
    with patch(f"{MODULE}.is_psycopg_available", lambda: True):
        fn = psycopg_available(my_function)
        assert fn(2) == 44


def test_psycopg_available_without_package() -> None:
    with patch(f"{MODULE}.is_psycopg_available", lambda: False):
        fn = psycopg_available(my_function)
        assert fn(2) is None


def test_psycopg_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_psycopg_available", lambda: True):

        @psycopg_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_psycopg_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_psycopg_available", lambda: False):

        @psycopg_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_psycopg_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'psycopg' package is required but not installed."):
        raise_psycopg_missing_error()
