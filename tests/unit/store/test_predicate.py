from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import IntEnum, StrEnum
from fractions import Fraction
from typing import Any, NamedTuple

import pytest

from persista.store.predicate import (
    _arrays_equal,
    _containers_equal,
    _dicts_equal,
    _sets_equal,
    matches_filter,
    values_equal,
)

NAN = float("nan")


class Point(NamedTuple):
    x: int
    y: int


class Color(StrEnum):
    RED = "red"


class Number(IntEnum):
    ONE = 1


class UnequalStr(str):
    r"""A ``str`` that is equal to nothing."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


class Thing:
    r"""An object that is equal to another with the same name."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Thing) and self.name == other.name

    __hash__ = None


class SubThing(Thing):
    r"""A subclass of ``Thing``."""


class Always:
    r"""An object that says it is equal to everything."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = None


EQUAL = [
    pytest.param(None, None, id="none"),
    pytest.param(True, True, id="true"),
    pytest.param(False, False, id="false"),
    pytest.param(1, 1, id="int"),
    pytest.param(1, 1.0, id="int_float"),
    pytest.param(0.0, -0.0, id="negative_zero"),
    pytest.param(2**53, float(2**53), id="large_int_float"),
    pytest.param(10**400, 10**400, id="huge_int"),
    pytest.param(float("inf"), float("inf"), id="inf"),
    pytest.param(1, Decimal(1), id="decimal"),
    pytest.param(0.5, Fraction(1, 2), id="fraction"),
    pytest.param(Number.ONE, 1, id="int_enum"),
    pytest.param("", "", id="empty_str"),
    pytest.param("abc", "abc", id="str"),
    pytest.param(Color.RED, "red", id="str_enum"),
    pytest.param(UnequalStr("a"), "a", id="str_subclass"),
    pytest.param([], [], id="empty_list"),
    pytest.param([], (), id="list_tuple"),
    pytest.param([1, [2, "3"]], (1.0, (2, "3")), id="nested_array"),
    pytest.param(Point(1, 2), [1, 2], id="named_tuple"),
    pytest.param({}, {}, id="empty_dict"),
    pytest.param({"a": 1, "b": [True]}, {"b": (True,), "a": 1.0}, id="dict"),
    pytest.param(OrderedDict(a=1, b=2), {"b": 2, "a": 1}, id="dict_subclass"),
    pytest.param({1: "a", (2,): None}, {1: "a", (2,): None}, id="non_str_keys"),
    pytest.param({1, "a"}, {"a", 1}, id="set"),
    pytest.param({1}, frozenset({1.0}), id="set_frozenset"),
    pytest.param(b"ab", b"ab", id="bytes"),
    pytest.param(date(2024, 1, 2), date(2024, 1, 2), id="date"),
    pytest.param(Thing("a"), Thing("a"), id="object"),
    pytest.param(Thing("a"), SubThing("a"), id="object_subclass"),
]

NOT_EQUAL = [
    pytest.param(None, False, id="none_false"),
    pytest.param(None, 0, id="none_zero"),
    pytest.param(None, "", id="none_empty_str"),
    pytest.param(None, [], id="none_list"),
    pytest.param(None, Always(), id="none_object"),
    pytest.param(True, False, id="booleans"),
    pytest.param(True, 1, id="true_int"),
    pytest.param(True, 1.0, id="true_float"),
    pytest.param(False, 0, id="false_int"),
    pytest.param(True, "true", id="true_str"),
    pytest.param(True, Decimal(1), id="true_decimal"),
    pytest.param(True, Always(), id="true_object"),
    pytest.param(1, 2, id="ints"),
    pytest.param(1, "1", id="int_str"),
    pytest.param(1.0, "1.0", id="float_str"),
    pytest.param(2**53 + 1, float(2**53), id="rounded_int_float"),
    pytest.param(10**22 + 1, 1e22, id="large_rounded_int_float"),
    pytest.param(0.1, Decimal("0.1"), id="rounded_decimal"),
    pytest.param(NAN, NAN, id="nan"),
    pytest.param([NAN], [NAN], id="list_nan"),
    pytest.param({"a": NAN}, {"a": NAN}, id="dict_nan"),
    pytest.param(1, [1], id="int_list"),
    pytest.param(1, Always(), id="int_object"),
    pytest.param("a", "A", id="str_case"),
    pytest.param(chr(0xE9), "e" + chr(0x301), id="str_normalization"),
    pytest.param("a", b"a", id="str_bytes"),
    pytest.param("a", ["a"], id="str_list"),
    pytest.param("a", Always(), id="str_object"),
    pytest.param([1], [True], id="list_bool"),
    pytest.param([1], ["1"], id="list_str"),
    pytest.param([1, 2], [2, 1], id="list_order"),
    pytest.param([1], [1, 1], id="list_length"),
    pytest.param([], {}, id="list_dict"),
    pytest.param([1], {1}, id="list_set"),
    pytest.param({"a": 1}, {"a": True}, id="dict_bool"),
    pytest.param({"a": 1}, {"b": 1}, id="dict_key"),
    pytest.param({"a": 1}, {"a": 1, "b": 2}, id="dict_extra_key"),
    pytest.param({"a": None}, {}, id="dict_none_absent"),
    pytest.param({"a": None}, {"b": None}, id="dict_none_other_key"),
    pytest.param({1: "a"}, {True: "a"}, id="dict_bool_key"),
    pytest.param({}, set(), id="dict_set"),
    pytest.param({1}, {True}, id="set_bool"),
    pytest.param({(1,)}, {(True,)}, id="set_nested_bool"),
    pytest.param({1}, {1, 2}, id="set_length"),
    pytest.param(b"a", [97], id="bytes_list"),
    pytest.param(b"a", bytearray(b"a"), id="bytes_bytearray"),
    pytest.param(date(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC), id="date_datetime"),
    pytest.param(Thing("a"), Thing("b"), id="objects"),
    pytest.param(Thing("a"), Always(), id="object_other_class"),
]


##################################
#     Tests for values_equal     #
##################################


@pytest.mark.parametrize(("first", "second"), EQUAL)
def test_values_equal(first: object, second: object) -> None:
    assert values_equal(first, second) is True


@pytest.mark.parametrize(("first", "second"), EQUAL)
def test_values_equal_is_symmetric(first: object, second: object) -> None:
    assert values_equal(second, first) is True


@pytest.mark.parametrize(("first", "second"), NOT_EQUAL)
def test_values_equal_not_equal(first: object, second: object) -> None:
    assert values_equal(first, second) is False


@pytest.mark.parametrize(("first", "second"), NOT_EQUAL)
def test_values_equal_not_equal_is_symmetric(first: object, second: object) -> None:
    assert values_equal(second, first) is False


def test_values_equal_same_nan_object() -> None:
    assert values_equal(NAN, NAN) is False


def test_values_equal_does_not_modify_values() -> None:
    first, second = [1, {"a": (2,)}], [1, {"a": [2]}]
    values_equal(first, second)
    assert (first, second) == ([1, {"a": (2,)}], [1, {"a": [2]}])


####################################
#     Tests for matches_filter     #
####################################


@pytest.mark.parametrize(
    ("value", "fields"),
    [
        pytest.param({"a": 1, "b": 2}, {"a": 1}, id="one_field"),
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="every_field"),
        pytest.param({"a": 1}, {}, id="no_field"),
        pytest.param({}, {}, id="empty"),
        pytest.param({}, {"a": None}, id="absent_is_none"),
        pytest.param({"a": None}, {"a": None}, id="null_is_none"),
        pytest.param({"a.b": 1}, {"a.b": 1}, id="dotted_name"),
        pytest.param({"self": 1}, {"self": 1}, id="self"),
    ],
)
def test_matches_filter(value: dict[str, Any], fields: dict[str, Any]) -> None:
    assert matches_filter(value, fields) is True


@pytest.mark.parametrize(
    ("value", "fields"),
    [
        pytest.param({"a": 1}, {"a": 2}, id="other_value"),
        pytest.param({"a": 1}, {"a": 1, "b": 2}, id="one_field_differs"),
        pytest.param({"a": 1}, {"a": True}, id="other_type"),
        pytest.param({"a": 1}, {"a": None}, id="not_none"),
        pytest.param({}, {"a": 0}, id="absent"),
        pytest.param({"a": {"b": 1}}, {"a.b": 1}, id="not_a_path"),
        pytest.param({"a": {"b": 1, "c": 2}}, {"a": {"b": 1}}, id="not_a_subset"),
    ],
)
def test_matches_filter_no_match(value: dict[str, Any], fields: dict[str, Any]) -> None:
    assert matches_filter(value, fields) is False


#######################################
#     Tests for _containers_equal     #
#######################################


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ([1], (1,), True),
        ({"a": 1}, {"a": 1}, True),
        ({1}, {1}, True),
        (b"a", b"a", True),
        ([1], {1}, False),
        (b"a", Thing("a"), False),
    ],
)
def test__containers_equal(first: object, second: object, expected: bool) -> None:
    assert _containers_equal(first, second) is expected


###################################
#     Tests for _arrays_equal     #
###################################


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [([], [], True), ([1], (1.0,), True), ([1], [True], False), ([1], [1, 2], False)],
)
def test__arrays_equal(first: list, second: list, expected: bool) -> None:
    assert _arrays_equal(first, second) is expected


##################################
#     Tests for _dicts_equal     #
##################################


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ({}, {}, True),
        ({"a": 1}, {"a": 1.0}, True),
        ({"a": 1}, {"a": True}, False),
        ({"a": 1}, {"b": 1}, False),
        ({"a": 1}, {}, False),
    ],
)
def test__dicts_equal(first: dict, second: dict, expected: bool) -> None:
    assert _dicts_equal(first, second) is expected


#################################
#     Tests for _sets_equal     #
#################################


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (set(), set(), True),
        ({1, 2}, {2.0, 1.0}, True),
        ({0}, {False}, False),
        ({1}, {2}, False),
        ({1}, set(), False),
    ],
)
def test__sets_equal(first: set, second: set, expected: bool) -> None:
    assert _sets_equal(first, second) is expected


def test_values_equal_cyclic_values() -> None:
    first: list[Any] = []
    first.append(first)
    second: list[Any] = []
    second.append(second)
    with pytest.raises(RecursionError, match=r"recursion"):
        values_equal(first, second)
