from __future__ import annotations

import math

import pytest

from persista.cache.ttl import DEFAULT, _Default, validate_ttl

##############################
#     Tests for _Default     #
##############################


def test_default_repr() -> None:
    assert repr(_Default()) == "DEFAULT"


def test_default_sentinel_repr() -> None:
    assert repr(DEFAULT) == "DEFAULT"


##################################
#     Tests for validate_ttl     #
##################################


@pytest.mark.parametrize("ttl", [None, 0, 0.0, -0.0, 1, 0.001, 10**9, math.inf])
def test_validate_ttl_valid(ttl: float | None) -> None:
    validate_ttl(ttl)


@pytest.mark.parametrize("ttl", [-1, -0.001, -math.inf, math.nan])
def test_validate_ttl_invalid(ttl: float) -> None:
    with pytest.raises(ValueError, match=r"^ttl must be None, 0 or positive, got "):
        validate_ttl(ttl)


def test_validate_ttl_name() -> None:
    with pytest.raises(ValueError, match=r"default_ttl must be None, 0 or positive, got -1"):
        validate_ttl(-1, name="default_ttl")


def test_validate_ttl_not_a_number() -> None:
    with pytest.raises(TypeError, match=r"not supported between"):
        validate_ttl("10")
