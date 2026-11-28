from __future__ import annotations

import pytest

from persista.testing.fixtures import rich_available, rich_not_available
from persista.utils.imports import check_rich, is_rich_available

################
#     rich     #
################


@rich_available
def test_check_rich_with_package() -> None:
    check_rich()


@rich_not_available
def test_check_rich_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'rich' package is required but not installed."):
        check_rich()


@rich_available
def test_is_rich_available_true() -> None:
    assert is_rich_available()


@rich_not_available
def test_is_rich_available_false() -> None:
    assert not is_rich_available()
