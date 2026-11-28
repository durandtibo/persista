from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import find_duplicate_record_ids

###############################################
#     Tests for find_duplicate_record_ids     #
###############################################


def test_find_duplicate_record_ids_no_duplicates() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert find_duplicate_record_ids(records) == []


def test_find_duplicate_record_ids_one_group() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "b"]]


def test_find_duplicate_record_ids_group_includes_all_occurrences() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "x"}),
        Record(id="c", metadata={"source": "x"}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "b", "c"]]


def test_find_duplicate_record_ids_multiple_groups_in_order() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
        Record(id="c", metadata={"source": "x"}),
        Record(id="d", metadata={"source": "y"}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "c"], ["b", "d"]]


def test_find_duplicate_record_ids_empty_input() -> None:
    assert find_duplicate_record_ids([]) == []


def test_find_duplicate_record_ids_single_record() -> None:
    records = [Record(id="a", metadata={"source": "x"})]
    assert find_duplicate_record_ids(records) == []


def test_find_duplicate_record_ids_key_order_ignored() -> None:
    records = [
        Record(id="a", metadata={"source": "x", "page": 1}),
        Record(id="b", metadata={"page": 1, "source": "x"}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "b"]]


def test_find_duplicate_record_ids_empty_metadata_grouped_together() -> None:
    records = [
        Record(id="a", metadata={}),
        Record(id="b", metadata={}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "b"]]


def test_find_duplicate_record_ids_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})
        yield Record(id="b", metadata={"source": "x"})

    assert find_duplicate_record_ids(gen()) == [["a", "b"]]


def test_find_duplicate_record_ids_generator_consumed_only_once() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})

    g = gen()
    find_duplicate_record_ids(g)
    assert list(g) == []


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
def test_find_duplicate_record_ids_different_values_not_grouped(
    first: object, second: object
) -> None:
    records = [Record(id="a", metadata={"x": first}), Record(id="b", metadata={"x": second})]
    assert find_duplicate_record_ids(records) == []


def test_find_duplicate_record_ids_equal_numbers_grouped() -> None:
    records = [Record(id="a", metadata={"x": [1]}), Record(id="b", metadata={"x": [1.0]})]
    assert find_duplicate_record_ids(records) == [["a", "b"]]


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
def test_find_duplicate_record_ids_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    records = [Record(id="a", metadata={"x": value})]
    with pytest.raises(error, match=message):
        find_duplicate_record_ids(records)


def test_find_duplicate_record_ids_does_not_modify_input() -> None:
    records = [Record(id="a", metadata={"x": [1.0]}), Record(id="b", metadata={"x": [1]})]
    find_duplicate_record_ids(records)
    assert repr(records) == (
        "[Record(id='a', metadata={'x': [1.0]}), Record(id='b', metadata={'x': [1]})]"
    )
