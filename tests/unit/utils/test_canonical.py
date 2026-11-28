from __future__ import annotations

import sys
from collections import OrderedDict, defaultdict
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Any, NamedTuple

import pytest

from persista.utils.canonical import (
    _encode,
    _encode_collection,
    encode_canonical,
    hash_canonical,
)


class Color(StrEnum):
    RED = "red"


class Number(IntEnum):
    ONE = 1


class Point(NamedTuple):
    x: int
    y: int


class Text(str):
    __slots__ = ()


class Float(float):
    pass


class Bytes(bytes):
    pass


def self_containing_list() -> list[Any]:
    value: list[Any] = []
    value.append(value)
    return value


def self_containing_dict() -> dict[str, Any]:
    value: dict[str, Any] = {}
    value["self"] = value
    return value


def self_containing_tuple() -> tuple[Any, ...]:
    inner: list[Any] = []
    value = (inner,)
    inner.append(value)
    return value


def nested_list(depth: int) -> list[Any]:
    value: list[Any] = []
    for _ in range(depth):
        value = [value]
    return value


UNSUPPORTED = [
    pytest.param(object(), r"builtins\.object", id="object"),
    pytest.param(Decimal(1), r"decimal\.Decimal", id="decimal"),
    pytest.param(complex(1, 2), r"builtins\.complex", id="complex"),
    pytest.param(bytearray(b"a"), r"builtins\.bytearray", id="bytearray"),
    pytest.param(memoryview(b"a"), r"builtins\.memoryview", id="memoryview"),
    pytest.param(range(3), r"builtins\.range", id="range"),
    pytest.param(Color.RED, r"Color", id="str-enum"),
    pytest.param(Number.ONE, r"Number", id="int-enum"),
    pytest.param(Point(1, 2), r"Point", id="named-tuple"),
    pytest.param(Text("a"), r"Text", id="str-subclass"),
    pytest.param(Float(1.0), r"Float", id="float-subclass"),
    pytest.param(Bytes(b"a"), r"Bytes", id="bytes-subclass"),
    pytest.param(OrderedDict(a=1), r"collections\.OrderedDict", id="ordered-dict"),
    pytest.param(defaultdict(int), r"collections\.defaultdict", id="default-dict"),
    pytest.param(int, r"builtins\.type", id="type"),
]

######################################
#     Tests for encode_canonical     #
######################################


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, b"N", id="none"),
        pytest.param(True, b"T", id="true"),
        pytest.param(False, b"F", id="false"),
        pytest.param(0, b"i1:\x00", id="zero"),
        pytest.param(1, b"i1:\x01", id="one"),
        pytest.param(-1, b"i1:\xff", id="minus-one"),
        pytest.param(127, b"i1:\x7f", id="127"),
        pytest.param(128, b"i2:\x00\x80", id="128"),
        pytest.param(-128, b"i2:\xff\x80", id="-128"),
        pytest.param(1.0, b"f\x3f\xf0\x00\x00\x00\x00\x00\x00", id="float"),
        pytest.param("", b"s0:", id="empty-str"),
        pytest.param(chr(0xE9), b"s2:\xc3\xa9", id="non-ascii-str"),
        pytest.param(chr(0xD800), b"s3:\xed\xa0\x80", id="lone-surrogate"),
        pytest.param(b"", b"b0:", id="empty-bytes"),
        pytest.param(b"ab", b"b2:ab", id="bytes"),
        pytest.param([], b"l0:", id="empty-list"),
        pytest.param((), b"t0:", id="empty-tuple"),
        pytest.param({}, b"d0:", id="empty-dict"),
        pytest.param(set(), b"S0:", id="empty-set"),
        pytest.param(frozenset(), b"z0:", id="empty-frozenset"),
    ],
)
def test_encode_canonical(value: object, expected: bytes) -> None:
    assert encode_canonical(value) == expected


def test_encode_canonical_nested() -> None:
    value = {"b": [None, (True,)], "a": {frozenset({b"x"})}}
    assert encode_canonical(value) == b"d2:s1:aS1:z1:b1:xs1:bl2:Nt1:T"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, "1", id="int-str"),
        pytest.param(1, 1.0, id="int-float"),
        pytest.param(1, True, id="int-bool"),
        pytest.param(0, False, id="zero-false"),
        pytest.param(0, None, id="zero-none"),
        pytest.param("a", b"a", id="str-bytes"),
        pytest.param([1, 2], (1, 2), id="list-tuple"),
        pytest.param({1, 2}, frozenset({1, 2}), id="set-frozenset"),
        pytest.param({1}, [1], id="set-list"),
        pytest.param({}, [], id="empty-dict-list"),
        pytest.param({"a": 1}, [("a", 1)], id="dict-pairs"),
        pytest.param({1: "a"}, {"1": "a"}, id="dict-key-types"),
        pytest.param({1}, {True}, id="set-int-bool"),
        pytest.param(0.0, -0.0, id="negative-zero"),
        pytest.param([[1], 2], [[1, 2]], id="list-boundaries"),
        pytest.param([[], []], [[[]]], id="list-nesting"),
        pytest.param(["ab", "c"], ["a", "bc"], id="str-boundaries"),
        pytest.param(["a", "b"], ["a1:b"], id="str-like-separator"),
        pytest.param(["as1:b"], ["a", "b"], id="str-like-encoding"),
        pytest.param([1, 2], [2, 1], id="list-order"),
        pytest.param({"a": 1, "b": 2}, {"a": 2, "b": 1}, id="dict-values"),
        pytest.param(chr(0xD83D) + chr(0xDE00), chr(0x1F600), id="surrogate-pair"),
        pytest.param(256, 1, id="int-length"),
        pytest.param(-1, 255, id="int-sign"),
    ],
)
def test_encode_canonical_different_values(first: object, second: object) -> None:
    assert encode_canonical(first) != encode_canonical(second)


def test_encode_canonical_dict_order_does_not_matter() -> None:
    assert encode_canonical({"a": 1, "b": 2}) == encode_canonical({"b": 2, "a": 1})


def test_encode_canonical_dict_keys_of_mixed_types() -> None:
    assert encode_canonical({1: "a", "1": "b", None: "c"}) == encode_canonical(
        {None: "c", "1": "b", 1: "a"}
    )


def test_encode_canonical_set_order_does_not_matter() -> None:
    # 0 and 8 collide in a small set, so the iteration order depends on the
    # insertion order.
    first = {0, 8}
    second = {8, 0}
    assert encode_canonical(first) == encode_canonical(second)


def test_encode_canonical_every_nan_is_the_same() -> None:
    assert encode_canonical(float("nan")) == encode_canonical(-float("nan"))


def test_encode_canonical_nan_differs_from_infinity() -> None:
    assert encode_canonical(float("nan")) != encode_canonical(float("inf"))


def test_encode_canonical_nan_dict_keys_order_does_not_matter() -> None:
    first, second = float("nan"), float("nan")
    assert encode_canonical({first: 1, second: 2}) == encode_canonical({second: 2, first: 1})


def test_encode_canonical_two_nan_items_differ_from_one() -> None:
    assert encode_canonical({float("nan"), float("nan")}) != encode_canonical({float("nan")})


def test_encode_canonical_big_int() -> None:
    # Larger than the default limit of sys.set_int_max_str_digits.
    value = 10 ** (sys.int_info.default_max_str_digits + 1)
    assert encode_canonical(value) != encode_canonical(value + 1)


def test_encode_canonical_shared_object_is_encoded_by_value() -> None:
    item = [1]
    assert encode_canonical([item, item]) == encode_canonical([[1], [1]])


def test_encode_canonical_does_not_mutate_value() -> None:
    value = {"b": [2, 1], "a": {3}}
    encode_canonical(value)
    assert list(value.items()) == [("b", [2, 1]), ("a", {3})]


@pytest.mark.parametrize(("value", "name"), UNSUPPORTED)
def test_encode_canonical_unsupported_type(value: object, name: str) -> None:
    with pytest.raises(TypeError, match=rf"Cannot encode an object of type .*{name}"):
        encode_canonical(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([object()], id="list"),
        pytest.param((object(),), id="tuple"),
        pytest.param({"a": object()}, id="dict-value"),
        pytest.param({object(): 1}, id="dict-key"),
        pytest.param({object()}, id="set"),
        pytest.param(frozenset({object()}), id="frozenset"),
    ],
)
def test_encode_canonical_unsupported_nested_type(value: object) -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type builtins\.object"):
        encode_canonical(value)


@pytest.mark.parametrize(
    ("value", "name"),
    [
        pytest.param(self_containing_list(), "list", id="list"),
        pytest.param(self_containing_dict(), "dict", id="dict"),
        pytest.param(self_containing_tuple(), "tuple", id="tuple"),
    ],
)
def test_encode_canonical_cycle(value: object, name: str) -> None:
    with pytest.raises(ValueError, match=rf"Cannot encode a {name} that contains itself"):
        encode_canonical(value)


def test_encode_canonical_too_deep() -> None:
    with pytest.raises(RecursionError, match=r"recursion"):
        encode_canonical(nested_list(sys.getrecursionlimit()))


####################################
#     Tests for hash_canonical     #
####################################


def test_hash_canonical() -> None:
    # BLAKE2b of b"N", with a 32-byte digest.
    assert (
        hash_canonical(None) == "be42f9777572b1c9400b38485493f88d5d28313e8cac8e697809f069a967789f"
    )


def test_hash_canonical_equal_values() -> None:
    assert hash_canonical({"a": 1, "b": 2}) == hash_canonical({"b": 2, "a": 1})


def test_hash_canonical_different_types() -> None:
    assert hash_canonical([1]) != hash_canonical((1,))


def test_hash_canonical_unsupported_type() -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type builtins\.object"):
        hash_canonical(object())


def test_hash_canonical_cycle() -> None:
    with pytest.raises(ValueError, match=r"Cannot encode a list that contains itself"):
        hash_canonical(self_containing_list())


#############################
#     Tests for _encode     #
#############################


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, b"N", id="scalar"),
        pytest.param([1], b"l1:i1:\x01", id="collection"),
    ],
)
def test_encode(value: object, expected: bytes) -> None:
    assert _encode(value, set()) == expected


def test_encode_keeps_parents() -> None:
    parents = {1}
    _encode([[2], {"a": (3,)}], parents)
    assert parents == {1}


def test_encode_unsupported_type() -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type builtins\.object"):
        _encode(object(), set())


########################################
#     Tests for _encode_collection     #
########################################


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param([2, 1], b"l2:i1:\x02i1:\x01", id="list"),
        pytest.param((2, 1), b"t2:i1:\x02i1:\x01", id="tuple"),
        pytest.param({2, 1}, b"S2:i1:\x01i1:\x02", id="set"),
        pytest.param(frozenset({2, 1}), b"z2:i1:\x01i1:\x02", id="frozenset"),
        pytest.param({"b": None, "a": True}, b"d2:s1:aTs1:bN", id="dict"),
    ],
)
def test_encode_collection(value: object, expected: bytes) -> None:
    assert _encode_collection(value, set()) == expected


def test_encode_collection_value_in_parents() -> None:
    value = [1]
    with pytest.raises(ValueError, match=r"Cannot encode a list that contains itself"):
        _encode_collection(value, {id(value)})


def test_encode_collection_unsupported_type() -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type builtins\.object"):
        _encode_collection(object(), set())
