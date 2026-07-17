from __future__ import annotations

import pytest

from persista.testing.fixtures import aiosqlite_available, aiosqlite_not_available
from persista.utils.imports import check_aiosqlite, is_aiosqlite_available

#####################
#     aiosqlite     #
#####################


@aiosqlite_available
def test_check_aiosqlite_with_package() -> None:
    check_aiosqlite()


@aiosqlite_not_available
def test_check_aiosqlite_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'aiosqlite' package is required but not installed."):
        check_aiosqlite()


@aiosqlite_available
def test_is_aiosqlite_available_true() -> None:
    assert is_aiosqlite_available()


@aiosqlite_not_available
def test_is_aiosqlite_available_false() -> None:
    assert not is_aiosqlite_available()
