from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from persista.utils.imports import (
    check_redis,
    is_redis_available,
    raise_redis_missing_error,
    redis_available,
)

logger = logging.getLogger(__name__)


MODULE = "persista.utils.imports.redis"


@pytest.fixture(autouse=True)
def _cache_clear() -> None:
    is_redis_available.cache_clear()


def my_function(n: int = 0) -> int:
    return 42 + n


#################
#     redis     #
#################


def test_check_redis_with_package() -> None:
    with patch(f"{MODULE}.is_redis_available", lambda: True):
        check_redis()


def test_check_redis_without_package() -> None:
    with (
        patch(f"{MODULE}.is_redis_available", lambda: False),
        pytest.raises(RuntimeError, match=r"'redis' package is required but not installed."),
    ):
        check_redis()


def test_is_redis_available() -> None:
    assert isinstance(is_redis_available(), bool)


def test_redis_available_with_package() -> None:
    with patch(f"{MODULE}.is_redis_available", lambda: True):
        fn = redis_available(my_function)
        assert fn(2) == 44


def test_redis_available_without_package() -> None:
    with patch(f"{MODULE}.is_redis_available", lambda: False):
        fn = redis_available(my_function)
        assert fn(2) is None


def test_redis_available_decorator_with_package() -> None:
    with patch(f"{MODULE}.is_redis_available", lambda: True):

        @redis_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) == 44


def test_redis_available_decorator_without_package() -> None:
    with patch(f"{MODULE}.is_redis_available", lambda: False):

        @redis_available
        def fn(n: int = 0) -> int:
            return 42 + n

        assert fn(2) is None


def test_raise_redis_missing_error() -> None:
    with pytest.raises(RuntimeError, match=r"'redis' package is required but not installed."):
        raise_redis_missing_error()
