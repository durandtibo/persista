from __future__ import annotations

import math

import pytest

from persista.record import Record
from persista.record.analysis import find_id_collisions

########################################
#     Tests for find_id_collisions     #
########################################


def test_find_id_collisions_no_collision_unique_ids() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="b", metadata={"source": "y"}),
    ]
    assert find_id_collisions(records) == {}


def test_find_id_collisions_repeated_id_same_metadata_not_a_collision() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "x"}),
    ]
    assert find_id_collisions(records) == {}


def test_find_id_collisions_repeated_id_different_metadata() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}]}


def test_find_id_collisions_multiple_distinct_variants() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "z"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}, {"source": "z"}]}


def test_find_id_collisions_only_colliding_ids_included() -> None:
    records = [
        Record(id="a", metadata={"source": "x"}),
        Record(id="a", metadata={"source": "y"}),
        Record(id="b", metadata={"source": "z"}),
    ]
    assert find_id_collisions(records) == {"a": [{"source": "x"}, {"source": "y"}]}


def test_find_id_collisions_empty_input() -> None:
    assert find_id_collisions([]) == {}


def test_find_id_collisions_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "x"})
        yield Record(id="a", metadata={"source": "y"})

    assert find_id_collisions(gen()) == {"a": [{"source": "x"}, {"source": "y"}]}


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
def test_find_id_collisions_different_types(first: object, second: object) -> None:
    records = [Record(id="a", metadata={"x": first}), Record(id="a", metadata={"x": second})]
    assert find_id_collisions(records) == {"a": [{"x": first}, {"x": second}]}


def test_find_id_collisions_equal_numbers_not_a_collision() -> None:
    records = [Record(id="a", metadata={"x": 1}), Record(id="a", metadata={"x": 1.0})]
    assert find_id_collisions(records) == {}


def test_find_id_collisions_keeps_first_of_equal_metadata() -> None:
    records = [
        Record(id="a", metadata={"x": 1.0}),
        Record(id="a", metadata={"x": 2}),
        Record(id="a", metadata={"x": 1}),
    ]
    assert repr(find_id_collisions(records)) == "{'a': [{'x': 1.0}, {'x': 2}]}"


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
def test_find_id_collisions_value_that_cannot_be_compared(
    value: object, error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        find_id_collisions([Record(id="a", metadata={"x": value})])


def test_find_id_collisions_result_does_not_share_the_metadata() -> None:
    records = [Record(id="a", metadata={"x": 1}), Record(id="a", metadata={"x": 2})]
    find_id_collisions(records)["a"][0]["x"] = 3
    assert records[0].metadata == {"x": 1}
