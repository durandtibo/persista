from __future__ import annotations

import pytest

from persista.testing.fixtures import redis_available, redis_not_available
from persista.utils.imports import check_redis, is_redis_available

#################
#     redis     #
#################


@redis_available
def test_check_redis_with_package() -> None:
    check_redis()


@redis_not_available
def test_check_redis_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'redis' package is required but not installed."):
        check_redis()


@redis_available
def test_is_redis_available_true() -> None:
    assert is_redis_available()


@redis_not_available
def test_is_redis_available_false() -> None:
    assert not is_redis_available()
