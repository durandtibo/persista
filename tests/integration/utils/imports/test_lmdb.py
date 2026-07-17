from __future__ import annotations

import pytest

from persista.testing.fixtures import lmdb_available, lmdb_not_available
from persista.utils.imports import check_lmdb, is_lmdb_available

################
#     lmdb     #
################


@lmdb_available
def test_check_lmdb_with_package() -> None:
    check_lmdb()


@lmdb_not_available
def test_check_lmdb_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'lmdb' package is required but not installed."):
        check_lmdb()


@lmdb_available
def test_is_lmdb_available_true() -> None:
    assert is_lmdb_available()


@lmdb_not_available
def test_is_lmdb_available_false() -> None:
    assert not is_lmdb_available()
