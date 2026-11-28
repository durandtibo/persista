from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from persista.record.equality import encode_value, hash_metadata
from persista.store.predicate import values_equal

##################################
#     Tests for encode_value     #
##################################


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, 1.0, id="int-float"),
        pytest.param(0.0, -0.0, id="zeros"),
        pytest.param({"a": 1, "b": 2}, {"b": 2, "a": 1}, id="dict-order"),
        pytest.param([1, {"a": 2.0}], [1.0, {"a": 2}], id="nested"),
    ],
)
def test_encode_value_equal(first: object, second: object) -> None:
    assert encode_value(first) == encode_value(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, "1", id="int-str"),
        pytest.param(1, True, id="int-bool"),
        pytest.param("1", True, id="str-bool"),
        pytest.param(0, None, id="int-none"),
        pytest.param([1, 2], (1, 2), id="list-tuple"),
        pytest.param([1, 2], [2, 1], id="order"),
        pytest.param({"a": None}, {}, id="none-absent"),
        pytest.param(b"a", "a", id="bytes-str"),
    ],
)
def test_encode_value_different(first: object, second: object) -> None:
    assert encode_value(first) != encode_value(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (1, 1),
        (1, 1.0),
        (1, "1"),
        (1, True),
        (0, False),
        (0.0, -0.0),
        (1.5, 1),
        (2**53 + 1, float(2**53)),
        (None, 0),
        ({"a": [1]}, {"a": [1.0]}),
        ({"a": None}, {}),
        ({1: "a"}, {True: "a"}),
    ],
)
def test_encode_value_agrees_with_the_filters(first: object, second: object) -> None:
    assert (encode_value(first) == encode_value(second)) is values_equal(first, second)


def test_encode_value_nan() -> None:
    with pytest.raises(ValueError, match=r"Cannot encode NaN by value"):
        encode_value(math.nan)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(datetime(2024, 1, 1, tzinfo=UTC), id="datetime"),
        pytest.param(Decimal(1), id="decimal"),
        pytest.param(object(), id="object"),
        pytest.param(bytearray(b"a"), id="bytearray"),
    ],
)
def test_encode_value_unsupported_type(value: object) -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type"):
        encode_value(value)


###################################
#     Tests for hash_metadata     #
###################################


def test_hash_metadata() -> None:
    assert (
        hash_metadata({"page": 1})
        == "f2de515c360882035cbf7b19d06e9279d4c170a974eb248012d552305a7db478"
    )


def test_hash_metadata_mapping_proxy() -> None:
    assert hash_metadata(MappingProxyType({"page": 1})) == hash_metadata({"page": 1})


def test_hash_metadata_equal_metadata() -> None:
    assert hash_metadata({"a": 1, "b": 2.0}) == hash_metadata({"b": 2, "a": 1.0})


def test_hash_metadata_different_metadata() -> None:
    assert hash_metadata({"x": 1}) != hash_metadata({"x": "1"})


def test_hash_metadata_empty() -> None:
    assert len(hash_metadata({})) == 64


def test_hash_metadata_does_not_mutate_input() -> None:
    metadata = {"b": 1.0, "a": [2.0]}
    hash_metadata(metadata)
    assert repr(metadata) == "{'b': 1.0, 'a': [2.0]}"


def test_hash_metadata_unsupported_type() -> None:
    with pytest.raises(TypeError, match=r"Cannot encode an object of type builtins\.object"):
        hash_metadata({"x": object()})


def test_hash_metadata_nan() -> None:
    with pytest.raises(ValueError, match=r"Cannot encode NaN by value"):
        hash_metadata({"x": math.nan})
