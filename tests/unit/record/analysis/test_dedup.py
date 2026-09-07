from __future__ import annotations

from persista.record import Record
from persista.record.analysis import find_duplicate_record_ids

########################################
#     Tests for find_duplicate_record_ids     #
########################################


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


def test_find_duplicate_record_ids_non_json_serializable_value_stringified() -> None:
    class Tag:
        def __str__(self) -> str:
            return "custom-tag"

    records = [
        Record(id="a", metadata={"tag": Tag()}),
        Record(id="b", metadata={"tag": Tag()}),
    ]
    assert find_duplicate_record_ids(records) == [["a", "b"]]
