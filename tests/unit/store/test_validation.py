from __future__ import annotations

import logging

import pytest

from persista.store.validation import (
    ON_CONFLICT_VALUES,
    normalize_on_conflict,
    validate_on_conflict,
)

logger = logging.getLogger(__name__)


##############################
#     normalize_on_conflict    #
##############################


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_normalize_on_conflict_valid(on_conflict: str) -> None:
    assert normalize_on_conflict(on_conflict) == on_conflict


@pytest.mark.parametrize("on_conflict", ["RAISE", "Skip", "OverWrite", "MERGE"])
def test_normalize_on_conflict_case_insensitive(on_conflict: str) -> None:
    assert normalize_on_conflict(on_conflict) == on_conflict.lower()


def test_normalize_on_conflict_strips_whitespace() -> None:
    assert normalize_on_conflict("  overwrite  ") == "overwrite"


def test_normalize_on_conflict_strips_whitespace_and_lowercases() -> None:
    assert normalize_on_conflict("  Skip\n") == "skip"


def test_normalize_on_conflict_invalid() -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value: 'bogus'"):
        normalize_on_conflict("bogus")


def test_normalize_on_conflict_empty_string() -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value: ''"):
        normalize_on_conflict("")


############################
#     validate_on_conflict    #
############################


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_validate_on_conflict_valid(on_conflict: str) -> None:
    validate_on_conflict(on_conflict)


def test_validate_on_conflict_invalid() -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value: 'bogus'"):
        validate_on_conflict("bogus")


def test_validate_on_conflict_case_sensitive() -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value: 'RAISE'"):
        validate_on_conflict("RAISE")


def test_validate_on_conflict_does_not_strip_whitespace() -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value: ' skip '"):
        validate_on_conflict(" skip ")


def test_validate_on_conflict_error_message_lists_valid_values() -> None:
    with pytest.raises(ValueError, match=r"Valid values are: \['merge', 'overwrite'"):
        validate_on_conflict("bogus")


def test_on_conflict_values() -> None:
    assert ON_CONFLICT_VALUES == ["merge", "overwrite", "raise", "skip"]
