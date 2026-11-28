from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import diff_records

########################################
#     Tests for diff_records     #
########################################


def test_diff_records_no_changes() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": []}


def test_diff_records_added() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert diff_records(before, after) == {"added": ["b"], "removed": [], "changed": []}


def test_diff_records_removed() -> None:
    before = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, after) == {"added": [], "removed": ["b"], "changed": []}


def test_diff_records_changed() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    after = [Record(id="a", metadata={"source": "y"})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": ["a"]}


def test_diff_records_mixed() -> None:
    before = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    after = [
        Record(id="a", metadata={"source": "x", "page": 1}),
        Record(id="c", metadata={"source": "z"}),
    ]
    assert diff_records(before, after) == {
        "added": ["c"],
        "removed": ["b"],
        "changed": ["a"],
    }


def test_diff_records_both_empty() -> None:
    assert diff_records([], []) == {"added": [], "removed": [], "changed": []}


def test_diff_records_before_empty() -> None:
    after = [Record(id="a", metadata={"source": "x"})]
    assert diff_records([], after) == {"added": ["a"], "removed": [], "changed": []}


def test_diff_records_after_empty() -> None:
    before = [Record(id="a", metadata={"source": "x"})]
    assert diff_records(before, []) == {"added": [], "removed": ["a"], "changed": []}


def test_diff_records_generator_input() -> None:
    def gen_before() -> object:
        yield Record(id="a", metadata={"source": "x"})

    def gen_after() -> object:
        yield Record(id="a", metadata={"source": "y"})

    assert diff_records(gen_before(), gen_after()) == {
        "added": [],
        "removed": [],
        "changed": ["a"],
    }


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
def test_diff_records_changed_type(first: object, second: object) -> None:
    before = [Record(id="a", metadata={"x": first})]
    after = [Record(id="a", metadata={"x": second})]
    assert diff_records(before, after)["changed"] == ["a"]


def test_diff_records_equal_numbers_not_changed() -> None:
    before = [Record(id="a", metadata={"x": 1})]
    after = [Record(id="a", metadata={"x": 1.0})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": []}


def test_diff_records_duplicate_id_compares_last_record() -> None:
    before = [Record(id="a", metadata={"x": 1}), Record(id="a", metadata={"x": 2})]
    after = [Record(id="a", metadata={"x": 2})]
    assert diff_records(before, after) == {"added": [], "removed": [], "changed": []}


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
def test_diff_records_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        diff_records([], [Record(id="a", metadata={"x": value})])


def test_diff_records_does_not_modify_input() -> None:
    before = [Record(id="a", metadata={"x": [1.0]})]
    after = [Record(id="a", metadata={"x": [2.0]})]
    diff_records(before, after)
    assert repr(before + after) == (
        "[Record(id='a', metadata={'x': [1.0]}), Record(id='a', metadata={'x': [2.0]})]"
    )
