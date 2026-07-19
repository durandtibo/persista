from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_httpx,
    httpx_available,
    is_httpx_available,
    raise_httpx_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.httpx"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_httpx_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


#################
#     httpx     #
#################


def test_check_httpx_with_package() -> None:
    with patch(f"{MODULE}.is_httpx_available", lambda: True):
        check_httpx()


def test_check_httpx_without_package() -> None:
    with (
        patch(f"{MODULE}.is_httpx_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."),
    ):
        check_httpx()


def test_is_httpx_available() -> None:
    assert isinstance(is_httpx_available(), bool)


def test_httpx_available_with_package() -> None:
    with patch(f"{MODULE}.is_httpx_available", lambda: True):
        fn = httpx_available(my_function)
        assert fn(2) == 44


def test_httpx_available_without_package() -> None:
    with patch(f"{MODULE}.is_httpx_available", lambda: False):
        fn = httpx_available(my_function)
        assert fn(2) is None


def test_httpx_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_httpx_available", lambda: True):

        @httpx_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_httpx_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_httpx_available", lambda: False):

        @httpx_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_httpx_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        raise_httpx_missing_error()
