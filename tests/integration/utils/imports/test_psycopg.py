from __future__ import annotations

import pytest

from persista.testing.fixtures import psycopg_available, psycopg_not_available
from persista.utils.imports import check_psycopg, is_psycopg_available

###################
#     psycopg     #
###################


@psycopg_available
def test_check_psycopg_with_package() -> None:
    check_psycopg()


@psycopg_not_available
def test_check_psycopg_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'psycopg' package is required but not installed."):
        check_psycopg()


@psycopg_available
def test_is_psycopg_available_true() -> None:
    assert is_psycopg_available()


@psycopg_not_available
def test_is_psycopg_available_false() -> None:
    assert not is_psycopg_available()
