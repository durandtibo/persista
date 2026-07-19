from __future__ import annotations

import pytest

from persista.testing.fixtures import urllib3_available, urllib3_not_available
from persista.utils.imports import check_urllib3, is_urllib3_available

###################
#     urllib3     #
###################


@urllib3_available
def test_check_urllib3_with_package() -> None:
    check_urllib3()


@urllib3_not_available
def test_check_urllib3_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'urllib3' package is required but not installed."):
        check_urllib3()


@urllib3_available
def test_is_urllib3_available_true() -> None:
    assert is_urllib3_available()


@urllib3_not_available
def test_is_urllib3_available_false() -> None:
    assert not is_urllib3_available()
