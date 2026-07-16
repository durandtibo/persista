from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_faker,
    faker_available,
    is_faker_available,
    raise_faker_missing_error,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.faker"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_faker_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


#################
#     faker     #
#################


def test_check_faker_with_package() -> None:
    with patch(f"{MODULE}.is_faker_available", lambda: True):
        check_faker()


def test_check_faker_without_package() -> None:
    with (
        patch(f"{MODULE}.is_faker_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'faker' package is required but not installed."),
    ):
        check_faker()


def test_is_faker_available() -> None:
    assert isinstance(is_faker_available(), bool)


def test_faker_available_with_package() -> None:
    with patch(f"{MODULE}.is_faker_available", lambda: True):
        fn = faker_available(my_function)
        assert fn(2) == 44


def test_faker_available_without_package() -> None:
    with patch(f"{MODULE}.is_faker_available", lambda: False):
        fn = faker_available(my_function)
        assert fn(2) is None


def test_faker_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_faker_available", lambda: True):

        @faker_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_faker_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_faker_available", lambda: False):

        @faker_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_faker_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'faker' package is required but not installed."):
        raise_faker_missing_error()
