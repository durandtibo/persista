from __future__ import annotations

import pytest

from persista.testing.fixtures import faker_available, faker_not_available
from persista.utils.imports import check_faker, is_faker_available

#################
#     faker     #
#################


@faker_available
def test_check_faker_with_package() -> None:
    check_faker()


@faker_not_available
def test_check_faker_without_package() -> None:
    with pytest.raises(RuntimeError, match=r"'faker' package is required but not installed."):
        check_faker()


@faker_available
def test_is_faker_available_true() -> None:
    assert is_faker_available()


@faker_not_available
def test_is_faker_available_false() -> None:
    assert not is_faker_available()
