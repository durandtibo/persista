from __future__ import annotations

import enum
import logging
from typing import TYPE_CHECKING

import pytest

from persista.store import (
    InMemoryStore,
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_on_conflict,
)
from persista.store.validation import (
    ON_CONFLICT_VALUES,
    check_is_closed,
    check_is_open,
    validate_key,
    validate_keys,
    validate_namespace,
    validate_table_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


class StrKey(enum.StrEnum):
    USER = "user"


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


################################
#     Tests for validate_key   #
################################


@pytest.mark.parametrize("key", ["", "a", "user:1", "é", "A key"])
def test_validate_key(key: str) -> None:
    assert validate_key(key) is key


def test_validate_key_converts_str_subclass() -> None:
    key = validate_key(StrKey.USER)
    assert (type(key), key) == (str, "user")


@pytest.mark.parametrize("key", [1, 1.5, True, None, b"a", ("a",)])
def test_validate_key_not_a_str_raises(key: object) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str, not"):
        validate_key(key)


#################################
#     Tests for validate_keys   #
#################################


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        pytest.param([], [], id="empty"),
        pytest.param(["a"], ["a"], id="single"),
        pytest.param(["b", "a", "b"], ["b", "a", "b"], id="duplicates"),
        pytest.param(("a", "b"), ["a", "b"], id="tuple"),
        pytest.param({"a": 1, "b": 2}, ["a", "b"], id="mapping"),
    ],
)
def test_validate_keys(keys: Iterable[str], expected: list[str]) -> None:
    assert validate_keys(keys) == expected


def test_validate_keys_consumes_a_generator_once() -> None:
    assert validate_keys(key for key in ["a", "b"]) == ["a", "b"]


def test_validate_keys_returns_new_list() -> None:
    keys = ["a"]
    assert validate_keys(keys) is not keys


def test_validate_keys_converts_str_subclass() -> None:
    assert [type(key) for key in validate_keys(["a", StrKey.USER])] == [str, str]


def test_validate_keys_does_not_mutate_input() -> None:
    keys = [StrKey.USER]
    validate_keys(keys)
    assert type(keys[0]) is StrKey


def test_validate_keys_single_str_raises() -> None:
    with pytest.raises(TypeError, match=r"not a single str: 'ab'"):
        validate_keys("ab")


def test_validate_keys_non_str_key_raises() -> None:
    with pytest.raises(TypeError, match=r"A key must be a str, not int: 1"):
        validate_keys(["a", 1])


########################################
#     Tests for validate_namespace     #
########################################


@pytest.mark.parametrize(
    "namespace",
    [
        "persista",
        "a",
        "v",
        "app:cache",
        "a:",
        ":a",
        ":",
        "a:keys",
        "v:a",
        "a:V",
        "a:vv",
        "av",
        "a:v ",
        " ",
        "é:🎉",
        "a*?[b]",
    ],
)
def test_validate_namespace_valid(namespace: str) -> None:
    validate_namespace(namespace)


def test_validate_namespace_empty() -> None:
    with pytest.raises(ValueError, match=r"A namespace must not be empty"):
        validate_namespace("")


@pytest.mark.parametrize("namespace", ["a:v", ":v", "a:v:", "a:v:b", ":v:", "a:v:keys"])
def test_validate_namespace_that_could_collide(namespace: str) -> None:
    with pytest.raises(ValueError, match=r"must not contain ':v:' or end with ':v'"):
        validate_namespace(namespace)


def test_validate_namespace_surrogate() -> None:
    with pytest.raises(ValueError, match=r"valid Unicode, but it has a lone surrogate"):
        validate_namespace("a" + chr(0xD800))


@pytest.mark.parametrize("namespace", [None, 1, b"a"])
def test_validate_namespace_not_a_str(namespace: object) -> None:
    with pytest.raises(TypeError, match=r"A namespace must be a str"):
        validate_namespace(namespace)


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


###############################
#     check_is_open            #
###############################


def test_check_is_open_does_not_raise_when_open() -> None:
    store = InMemoryStore()
    with store:
        check_is_open(store)


def test_check_is_open_raises_when_closed() -> None:
    store = InMemoryStore()
    with pytest.raises(RuntimeError, match="is not open"):
        check_is_open(store)


def test_check_is_open_raises_after_close() -> None:
    store = InMemoryStore()
    store.open()
    store.close()
    with pytest.raises(RuntimeError, match="is not open"):
        check_is_open(store)


###############################
#     check_is_closed          #
###############################


def test_check_is_closed_does_not_raise_when_closed() -> None:
    store = InMemoryStore()
    check_is_closed(store)


def test_check_is_closed_raises_when_open() -> None:
    store = InMemoryStore()
    with store, pytest.raises(RuntimeError, match="is not closed"):
        check_is_closed(store)


def test_check_is_closed_does_not_raise_after_close() -> None:
    store = InMemoryStore()
    store.open()
    store.close()
    check_is_closed(store)
