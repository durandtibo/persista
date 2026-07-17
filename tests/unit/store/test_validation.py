from __future__ import annotations

import logging

import pytest

from persista.store import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
from persista.store.validation import ON_CONFLICT_VALUES, validate_table_name

logger = logging.getLogger(__name__)


################################
#     normalize_on_conflict    #
################################


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


################################
#     validate_on_conflict     #
################################


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


###############################
#     validate_batch_size     #
###############################


@pytest.mark.parametrize("batch_size", [1, 2, 32, 1000])
def test_validate_batch_size_valid(batch_size: int) -> None:
    validate_batch_size(batch_size)


def test_validate_batch_size_zero() -> None:
    with pytest.raises(ValueError, match=r"batch_size must be a positive integer, got 0"):
        validate_batch_size(0)


@pytest.mark.parametrize("batch_size", [-1, -10])
def test_validate_batch_size_negative(batch_size: int) -> None:
    with pytest.raises(
        ValueError, match=rf"batch_size must be a positive integer, got {batch_size}"
    ):
        validate_batch_size(batch_size)


def test_validate_batch_size_returns_none() -> None:
    assert validate_batch_size(1) is None


###############################
#     validate_field_name     #
###############################


@pytest.mark.parametrize("name", ["author", "_author", "Author2", "a", "_", "field_name_2"])
def test_validate_field_name_valid(name: str) -> None:
    assert validate_field_name(name) is None


@pytest.mark.parametrize(
    "name",
    [
        "x') OR 1=1 OR ('",
        "author; DROP TABLE store;",
        "author'",
        "2author",
        "author name",
        "author-name",
        "",
    ],
)
def test_validate_field_name_invalid(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid filter field name"):
        validate_field_name(name)


###############################
#     validate_table_name      #
###############################


def test_validate_table_name_accepts_valid_identifier() -> None:
    validate_table_name("store")
    validate_table_name("_my_table_2")


def test_validate_table_name_rejects_invalid_identifier() -> None:
    with pytest.raises(ValueError, match=r"Invalid table name"):
        validate_table_name("store; DROP TABLE store;--")


def test_validate_table_name_rejects_leading_digit() -> None:
    with pytest.raises(ValueError, match=r"Invalid table name"):
        validate_table_name("2store")
