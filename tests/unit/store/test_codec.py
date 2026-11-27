from __future__ import annotations

import enum
import json
import pickle
from collections import OrderedDict, defaultdict
from typing import Any, NamedTuple

import pytest

from persista.store.codec import (
    Codec,
    JsonCodec,
    PickleCodec,
    _check_json_keys,
    _check_no_surrogate,
    check_is_dict,
    check_json_content,
)

HIGH_SURROGATE = chr(0xD800)
LOW_SURROGATE = chr(0xDFFF)


class Color(enum.StrEnum):
    RED = "red"


class Level(enum.IntEnum):
    HIGH = 3


class Point(NamedTuple):
    x: int
    y: int


class IdentityStr(str):
    r"""A ``str`` that is only equal to itself."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


class MyFloat(float):
    __slots__ = ()


def self_containing_value() -> dict[str, Any]:
    r"""Return a value that contains itself."""
    value: dict[str, Any] = {}
    value["self"] = value
    return value


JSON_VALUES = [
    pytest.param({}, id="empty"),
    pytest.param({"str": "a", "int": 1, "float": 1.5, "true": True, "none": None}, id="scalars"),
    pytest.param({"a": {"b": [{"c": 1}, []]}}, id="nested"),
    pytest.param({"": 1}, id="empty_key"),
    pytest.param({"é": "日本 🎉"}, id="unicode"),
    pytest.param({"big": 2**100}, id="big_int"),
    pytest.param({"nul": "a" + chr(0) + "b"}, id="nul"),
]

NON_STR_KEY_VALUES = [
    pytest.param({1: "a"}, "int", id="int"),
    pytest.param({True: "a"}, "bool", id="bool"),
    pytest.param({None: "a"}, "NoneType", id="none"),
    pytest.param({1.5: "a"}, "float", id="float"),
    pytest.param({"a": {1: "int", "1": "str"}}, "int", id="nested_dict"),
    pytest.param({"a": [{1: "a"}]}, "int", id="in_list"),
    pytest.param({"a": ({"b": {2: "a"}},)}, "int", id="in_tuple"),
]

NON_FINITE_VALUES = [
    pytest.param({"a": float("nan")}, id="nan"),
    pytest.param({"a": float("inf")}, id="inf"),
    pytest.param({"a": float("-inf")}, id="negative_inf"),
    pytest.param({"a": [1.0, (float("nan"),)]}, id="nested_nan"),
    pytest.param({float("nan"): 1}, id="nan_key"),
]

SURROGATE_VALUES = [
    pytest.param({"a": HIGH_SURROGATE}, id="value"),
    pytest.param({LOW_SURROGATE: 1}, id="key"),
    pytest.param({"a": ["ok", "x" + HIGH_SURROGATE + "y"]}, id="in_list"),
    pytest.param({"a": {"b": HIGH_SURROGATE}}, id="nested"),
]


###################################
#     Tests for check_is_dict     #
###################################


@pytest.mark.parametrize("value", [{}, {"a": 1}, OrderedDict(a=1)])
def test_check_is_dict(value: Any) -> None:
    check_is_dict(value)


@pytest.mark.parametrize("value", [None, 1, "a", [], (), {1}])
def test_check_is_dict_not_a_dict_raises(value: Any) -> None:
    with pytest.raises(TypeError, match=r"A value must be a dict, not"):
        check_is_dict(value)


########################################
#     Tests for check_json_content     #
########################################


@pytest.mark.parametrize("value", JSON_VALUES)
def test_check_json_content(value: dict[str, Any]) -> None:
    check_json_content(value)


@pytest.mark.parametrize(("value", "type_name"), NON_STR_KEY_VALUES)
def test_check_json_content_non_str_key_raises(value: dict[Any, Any], type_name: str) -> None:
    with pytest.raises(TypeError, match=rf"dict keys must be str, not {type_name}"):
        check_json_content(value)


@pytest.mark.parametrize("value", SURROGATE_VALUES)
def test_check_json_content_surrogate_raises(value: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        check_json_content(value)


def test_check_json_content_deeply_nested() -> None:
    value: dict[Any, Any] = {1: "a"}
    for _ in range(500):
        value = {"a": [value]}
    with pytest.raises(TypeError, match=r"dict keys must be str"):
        check_json_content(value)


def test_check_json_content_does_not_mutate_value() -> None:
    value = {"a": (1, [2]), "b": {"c": Color.RED}}
    check_json_content(value)
    assert value == {"a": (1, [2]), "b": {"c": Color.RED}}


######################################
#     Tests for _check_json_keys     #
######################################


@pytest.mark.parametrize("mapping", [{}, {"a": 1, "é": 2}, {Color.RED: 1, "blue": 2}])
def test__check_json_keys(mapping: dict[Any, Any]) -> None:
    _check_json_keys(mapping)


def test__check_json_keys_non_str_raises() -> None:
    with pytest.raises(TypeError, match=r"dict keys must be str, not tuple: \(1,\)"):
        _check_json_keys({(1,): 1})


def test__check_json_keys_same_string_twice_raises() -> None:
    with pytest.raises(ValueError, match=r"dict keys must be different JSON strings"):
        _check_json_keys({"a": 1, IdentityStr("a"): 2})


def test__check_json_keys_surrogate_raises() -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        _check_json_keys({HIGH_SURROGATE: 1})


#########################################
#     Tests for _check_no_surrogate     #
#########################################


@pytest.mark.parametrize("text", ["", "a", "é", "🎉"])
def test__check_no_surrogate(text: str) -> None:
    _check_no_surrogate(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(HIGH_SURROGATE, id="high"),
        pytest.param(LOW_SURROGATE, id="low"),
        pytest.param(chr(0xD83C) + chr(0xDF89), id="pair"),
    ],
)
def test__check_no_surrogate_raises(text: str) -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        _check_no_surrogate(text)


###########################
#     Tests for Codec     #
###########################


class IncompleteCodec(Codec):
    r"""Subclass the protocol without implementing it."""


def test_codec_encode_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match=r"^$"):
        IncompleteCodec().encode({})


def test_codec_decode_is_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match=r"^$"):
        IncompleteCodec().decode("{}")


###############################
#     Tests for JsonCodec     #
###############################


def test_json_codec_name() -> None:
    assert JsonCodec().name == "json"


def test_json_codec_repr() -> None:
    assert repr(JsonCodec()) == "JsonCodec()"


def test_json_codec_encode() -> None:
    assert JsonCodec().encode({"a": 1, "b": [True, None]}) == '{"a": 1, "b": [true, null]}'


def test_json_codec_encode_same_payload_as_json_dumps() -> None:
    # The format of the stored data does not change.
    value = {"title": "Zoé 🎉", "tags": ["a"]}
    assert JsonCodec().encode(value) == json.dumps(value)


@pytest.mark.parametrize("value", JSON_VALUES)
def test_json_codec_round_trip(value: dict[str, Any]) -> None:
    codec = JsonCodec()
    assert codec.decode(codec.encode(value)) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param((1, 2), [1, 2], id="tuple"),
        pytest.param([(1, (2,))], [[1, [2]]], id="nested_tuple"),
        pytest.param(Point(1, 2), [1, 2], id="named_tuple"),
        pytest.param(Color.RED, "red", id="str_enum"),
        pytest.param(Level.HIGH, 3, id="int_enum"),
        pytest.param(MyFloat(1.5), 1.5, id="float_subclass"),
        pytest.param(OrderedDict(b=1), {"b": 1}, id="ordered_dict"),
        pytest.param(defaultdict(int, b=1), {"b": 1}, id="defaultdict"),
    ],
)
def test_json_codec_round_trip_normalizes_type(value: Any, expected: Any) -> None:
    codec = JsonCodec()
    result = codec.decode(codec.encode({"a": value}))["a"]
    assert (type(result), result) == (type(expected), expected)


def test_json_codec_round_trip_str_enum_key() -> None:
    codec = JsonCodec()
    [key] = codec.decode(codec.encode({Color.RED: 1}))
    assert (type(key), key) == (str, "red")


def test_json_codec_round_trip_dict_subclass_value() -> None:
    codec = JsonCodec()
    assert type(codec.decode(codec.encode(OrderedDict(a=1)))) is dict


@pytest.mark.parametrize(("value", "type_name"), NON_STR_KEY_VALUES)
def test_json_codec_encode_non_str_key_raises(value: dict[Any, Any], type_name: str) -> None:
    with pytest.raises(TypeError, match=rf"keys must be str, not {type_name}"):
        JsonCodec().encode(value)


def test_json_codec_encode_tuple_key_raises() -> None:
    with pytest.raises(TypeError, match=r"keys must be str.*not tuple"):
        JsonCodec().encode({(1, 2): "a"})


def test_json_codec_encode_same_key_twice_raises() -> None:
    with pytest.raises(ValueError, match=r"dict keys must be different JSON strings"):
        JsonCodec().encode({"a": 1, IdentityStr("a"): 2})


@pytest.mark.parametrize("value", NON_FINITE_VALUES)
def test_json_codec_encode_non_finite_float_raises(value: dict[Any, Any]) -> None:
    with pytest.raises(ValueError, match=r"not JSON compliant"):
        JsonCodec().encode(value)


@pytest.mark.parametrize("value", SURROGATE_VALUES)
def test_json_codec_encode_surrogate_raises(value: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"lone surrogate"):
        JsonCodec().encode(value)


@pytest.mark.parametrize("value", [{1, 2}, b"a", object()])
def test_json_codec_encode_unsupported_object_raises(value: Any) -> None:
    with pytest.raises(TypeError, match=r"not JSON serializable"):
        JsonCodec().encode({"a": value})


@pytest.mark.parametrize("value", [None, 1, "a", [1]])
def test_json_codec_encode_not_a_dict_raises(value: Any) -> None:
    with pytest.raises(TypeError, match=r"A value must be a dict"):
        JsonCodec().encode(value)


def test_json_codec_encode_value_containing_itself_raises() -> None:
    with pytest.raises(ValueError, match=r"Circular reference"):
        JsonCodec().encode(self_containing_value())


def test_json_codec_encode_does_not_mutate_value() -> None:
    value = {"a": (1, 2)}
    JsonCodec().encode(value)
    assert value == {"a": (1, 2)}


@pytest.mark.parametrize("payload", ['{"a": 1}', b'{"a": 1}'])
def test_json_codec_decode(payload: str | bytes) -> None:
    assert JsonCodec().decode(payload) == {"a": 1}


def test_json_codec_decode_returns_new_object() -> None:
    codec = JsonCodec()
    assert codec.decode('{"a": []}')["a"] is not codec.decode('{"a": []}')["a"]


def test_json_codec_decode_invalid_payload_raises() -> None:
    with pytest.raises(ValueError, match=r"Expecting"):
        JsonCodec().decode("{")


def test_json_codec_get_repr_kwargs() -> None:
    assert JsonCodec()._get_repr_kwargs() == {}


#################################
#     Tests for PickleCodec     #
#################################


def test_pickle_codec_name() -> None:
    assert PickleCodec().name == "pickle"


def test_pickle_codec_repr() -> None:
    assert repr(PickleCodec()) == "PickleCodec()"


def test_pickle_codec_encode() -> None:
    assert PickleCodec().encode({"a": 1}) == pickle.dumps({"a": 1})


@pytest.mark.parametrize(
    "value",
    [
        pytest.param({}, id="empty"),
        pytest.param({"a": (1, 2), "b": {3}, "c": b"d"}, id="types"),
        pytest.param({1: "int", "1": "str", (2,): None}, id="keys"),
        pytest.param({"a": float("inf"), "b": HIGH_SURROGATE}, id="not_json"),
        pytest.param({"a": Point(1, 2), "b": Color.RED}, id="classes"),
        pytest.param(OrderedDict(a=1), id="dict_subclass"),
    ],
)
def test_pickle_codec_round_trip(value: dict[Any, Any]) -> None:
    codec = PickleCodec()
    result = codec.decode(codec.encode(value))
    assert (type(result), result) == (type(value), value)


def test_pickle_codec_round_trip_returns_new_object() -> None:
    codec = PickleCodec()
    value: dict[str, Any] = {"a": []}
    assert codec.decode(codec.encode(value))["a"] is not value["a"]


@pytest.mark.parametrize("value", [None, 1, "a", [1]])
def test_pickle_codec_encode_not_a_dict_raises(value: Any) -> None:
    with pytest.raises(TypeError, match=r"A value must be a dict"):
        PickleCodec().encode(value)


def test_pickle_codec_encode_unpicklable_raises() -> None:
    with pytest.raises((pickle.PicklingError, AttributeError), match=r"(Can't|local object)"):
        PickleCodec().encode({"a": lambda: None})


def test_pickle_codec_decode_str_raises() -> None:
    with pytest.raises(TypeError, match=r"A pickle payload must be bytes"):
        PickleCodec().decode("abc")


def test_pickle_codec_get_repr_kwargs() -> None:
    assert PickleCodec()._get_repr_kwargs() == {}
