from __future__ import annotations

import pytest

from persista.testing.fixtures import httpx_available, httpx_not_available
from persista.utils.imports import check_httpx, is_httpx_available

#################
#     httpx     #
#################


@httpx_available
def test_check_httpx_with_package() -> None:
    check_httpx()


@httpx_not_available
def test_check_httpx_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'httpx' package is required but not installed."):
        check_httpx()


@httpx_available
def test_is_httpx_available_true() -> None:
    assert is_httpx_available()


@httpx_not_available
def test_is_httpx_available_false() -> None:
    assert not is_httpx_available()
