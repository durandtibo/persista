from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import compute_value_frequency


def records_of(*values: object) -> list[Record]:
    return [Record(id=str(i), metadata={"x": value}) for i, value in enumerate(values)]


#############################################
#     Tests for compute_value_frequency     #
#############################################


def test_compute_value_frequency() -> None:
    records = [
        Record(id="a", metadata={"lang": "en", "page": 1}),
        Record(id="b", metadata={"lang": "fr"}),
        Record(id="c", metadata={"lang": "en"}),
    ]
    assert compute_value_frequency(records) == {
        "lang": {"top_values": [("en", 2), ("fr", 1)], "distinct_count": 2},
        "page": {"top_values": [(1, 1)], "distinct_count": 1},
    }


def test_compute_value_frequency_empty_input() -> None:
    assert compute_value_frequency([]) == {}


def test_compute_value_frequency_empty_metadata() -> None:
    assert compute_value_frequency([Record(id="a")]) == {}


def test_compute_value_frequency_top_k_limits_values_not_count() -> None:
    assert compute_value_frequency(records_of("en", "fr", "de"), top_k=2) == {
        "x": {"top_values": [("en", 1), ("fr", 1)], "distinct_count": 3}
    }


def test_compute_value_frequency_top_k_zero() -> None:
    assert compute_value_frequency(records_of("en"), top_k=0) == {
        "x": {"top_values": [], "distinct_count": 1}
    }


def test_compute_value_frequency_negative_top_k() -> None:
    with pytest.raises(ValueError, match=r"'top_k' must be non-negative, got -1"):
        compute_value_frequency(records_of("en"), top_k=-1)


def test_compute_value_frequency_default_top_k() -> None:
    result = compute_value_frequency(records_of(*range(10)))
    assert result["x"]["top_values"] == [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1)]


def test_compute_value_frequency_types_are_kept_apart() -> None:
    assert compute_value_frequency(records_of(1, "1", True)) == {
        "x": {"top_values": [(1, 1), ("1", 1), (True, 1)], "distinct_count": 3}
    }


def test_compute_value_frequency_equal_numbers_counted_together() -> None:
    result = compute_value_frequency(records_of(1.0, 1))
    assert repr(result) == "{'x': {'top_values': [(1.0, 2)], 'distinct_count': 1}}"


def test_compute_value_frequency_unhashable_values() -> None:
    records = records_of(["x", "y"], ["x", "y"], "['x', 'y']", ("x", "y"))
    assert compute_value_frequency(records) == {
        "x": {
            "top_values": [(["x", "y"], 2), ("['x', 'y']", 1), (("x", "y"), 1)],
            "distinct_count": 3,
        }
    }


def test_compute_value_frequency_distinct_count_is_exact() -> None:
    records = records_of(*range(500))
    assert compute_value_frequency(records)["x"]["distinct_count"] == 500


@pytest.mark.parametrize(
    ("value", "error", "message"),
    [
        pytest.param(object(), TypeError, r"Cannot encode an object of type", id="custom"),
        pytest.param(
            bytearray(b"a"), TypeError, r"Cannot encode an object of type", id="bytearray"
        ),
        pytest.param(math.nan, ValueError, r"Cannot encode NaN by value", id="nan"),
    ],
)
def test_compute_value_frequency_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        compute_value_frequency(records_of(value))


def test_compute_value_frequency_generator_input() -> None:
    records = (record for record in records_of("en", "en"))
    assert compute_value_frequency(records)["x"]["top_values"] == [("en", 2)]


def test_compute_value_frequency_does_not_modify_input() -> None:
    records = records_of([1.0], [1])
    compute_value_frequency(records)
    assert repr(records) == (
        "[Record(id='0', metadata={'x': [1.0]}), Record(id='1', metadata={'x': [1]})]"
    )
