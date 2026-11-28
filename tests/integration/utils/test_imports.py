from __future__ import annotations

import pytest

from persista.testing.fixtures import (
    duckdb_available,
    duckdb_not_available,
    faker_available,
    faker_not_available,
    httpx_available,
    httpx_not_available,
    lmdb_available,
    lmdb_not_available,
    psycopg_available,
    psycopg_not_available,
    redis_available,
    redis_not_available,
    requests_available,
    requests_not_available,
    rich_available,
    rich_not_available,
    urllib3_available,
    urllib3_not_available,
)
from persista.utils import imports

AVAILABLE = [
    pytest.param("duckdb", marks=duckdb_available),
    pytest.param("faker", marks=faker_available),
    pytest.param("httpx", marks=httpx_available),
    pytest.param("lmdb", marks=lmdb_available),
    pytest.param("psycopg", marks=psycopg_available),
    pytest.param("redis", marks=redis_available),
    pytest.param("requests", marks=requests_available),
    pytest.param("rich", marks=rich_available),
    pytest.param("urllib3", marks=urllib3_available),
]
NOT_AVAILABLE = [
    pytest.param("duckdb", marks=duckdb_not_available),
    pytest.param("faker", marks=faker_not_available),
    pytest.param("httpx", marks=httpx_not_available),
    pytest.param("lmdb", marks=lmdb_not_available),
    pytest.param("psycopg", marks=psycopg_not_available),
    pytest.param("redis", marks=redis_not_available),
    pytest.param("requests", marks=requests_not_available),
    pytest.param("rich", marks=rich_not_available),
    pytest.param("urllib3", marks=urllib3_not_available),
]


##################################
#     Tests for check_<name>     #
##################################


@pytest.mark.parametrize("name", AVAILABLE)
def test_check_with_package(name: str) -> None:
    getattr(imports, f"check_{name}")()


@pytest.mark.parametrize("name", NOT_AVAILABLE)
def test_check_without_package(name: str) -> None:
    with pytest.raises(RuntimeError, match=rf"'{name}' package is required but not installed."):
        getattr(imports, f"check_{name}")()


#########################################
#     Tests for is_<name>_available     #
#########################################


@pytest.mark.parametrize("name", AVAILABLE)
def test_is_available_true(name: str) -> None:
    assert getattr(imports, f"is_{name}_available")()


@pytest.mark.parametrize("name", NOT_AVAILABLE)
def test_is_available_false(name: str) -> None:
    assert not getattr(imports, f"is_{name}_available")()
