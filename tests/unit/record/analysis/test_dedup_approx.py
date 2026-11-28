from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import count_approx_duplicate_records

####################################################
#     Tests for count_approx_duplicate_records     #
####################################################


def test_count_approx_duplicate_records_no_duplicates() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 0


def test_count_approx_duplicate_records_one_duplicate() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 1


def test_count_approx_duplicate_records_multiple_duplicates() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
        Record(id="c", metadata={"source": "x"}),
        Record(id="d", metadata={"source": "y"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 2


def test_count_approx_duplicate_records_empty_input() -> None:
    assert count_approx_duplicate_records([], expected_record_count=100) == 0


def test_count_approx_duplicate_records_single_record() -> None:
    records = [Record(id="a", metadata={"source": "x"})]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 0


def test_count_approx_duplicate_records_key_order_ignored() -> None:
    records = [
        Record(id="a", metadata={"source": "x", "page": 1}),
        Record(id="b", metadata={"page": 1, "source": "x"}),
    ]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 1


def test_count_approx_duplicate_records_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})
        yield Record(id="b", metadata={"source": "x"})

    assert count_approx_duplicate_records(gen(), expected_record_count=100) == 1


def test_count_approx_duplicate_records_generator_consumed_only_once() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})

    g = gen()
    count_approx_duplicate_records(g, expected_record_count=100)
    assert list(g) == []


def test_count_approx_duplicate_records_default_args_do_not_raise() -> None:
    records = [Record(id="a", metadata={"source": "x"})]
    assert count_approx_duplicate_records(records) == 0


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(1, "1", id="int-str"),
        pytest.param(1, True, id="int-bool"),
        pytest.param("1", True, id="str-bool"),
        pytest.param([1, 2], (1, 2), id="list-tuple"),
        pytest.param({"a": None}, {}, id="none-absent"),
    ],
)
def test_count_approx_duplicate_records_different_values(first: object, second: object) -> None:
    records = [Record(id="a", metadata={"x": first}), Record(id="b", metadata={"x": second})]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 0


def test_count_approx_duplicate_records_equal_numbers() -> None:
    records = [Record(id="a", metadata={"x": 1}), Record(id="b", metadata={"x": 1.0})]
    assert count_approx_duplicate_records(records, expected_record_count=100) == 1


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
def test_count_approx_duplicate_records_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    records = [Record(id="a", metadata={"x": value})]
    with pytest.raises(error, match=message):
        count_approx_duplicate_records(records, expected_record_count=100)


@pytest.mark.parametrize("expected_record_count", [0, -1])
def test_count_approx_duplicate_records_invalid_expected_record_count(
    expected_record_count: int,
) -> None:
    with pytest.raises(ValueError, match=r"'expected_record_count' must be positive"):
        count_approx_duplicate_records([], expected_record_count=expected_record_count)


@pytest.mark.parametrize("fp_rate", [0.0, 1.0, -0.1, 1.5, math.nan])
def test_count_approx_duplicate_records_invalid_fp_rate(fp_rate: float) -> None:
    with pytest.raises(ValueError, match=r"fp_rate must be in \(0, 1\)"):
        count_approx_duplicate_records([], expected_record_count=10, fp_rate=fp_rate)


def test_count_approx_duplicate_records_invalid_parameter_consumes_nothing() -> None:
    records = iter([Record(id="a")])
    with pytest.raises(ValueError, match=r"'expected_record_count' must be positive"):
        count_approx_duplicate_records(records, expected_record_count=0)
    assert list(records) == [Record(id="a")]


def test_count_approx_duplicate_records_does_not_modify_input() -> None:
    records = [Record(id="a", metadata={"x": [1.0]})]
    count_approx_duplicate_records(records, expected_record_count=100)
    assert repr(records) == "[Record(id='a', metadata={'x': [1.0]})]"
