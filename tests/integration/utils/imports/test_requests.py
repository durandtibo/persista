from __future__ import annotations

import pytest

from persista.testing.fixtures import requests_available, requests_not_available
from persista.utils.imports import check_requests, is_requests_available

####################
#     requests     #
####################


@requests_available
def test_check_requests_with_package() -> None:
    check_requests()


@requests_not_available
def test_check_requests_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'requests' package is required but not installed."):
        check_requests()


@requests_available
def test_is_requests_available_true() -> None:
    assert is_requests_available()


@requests_not_available
def test_is_requests_available_false() -> None:
    assert not is_requests_available()
