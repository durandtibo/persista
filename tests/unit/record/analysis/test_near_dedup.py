from __future__ import annotations

import pytest

from persista.record import Record
from persista.record.analysis import find_near_duplicate_record_ids

########################################
#     Tests for find_near_duplicate_record_ids     #
########################################


def test_find_near_duplicate_record_ids_no_similarity() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf"}),
        Record(id="b", metadata={"source": "z.pdf"}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4) == []


def test_find_near_duplicate_record_ids_identical_metadata_always_grouped() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf"}),
        Record(id="b", metadata={"source": "a.pdf"}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == [["a", "b"]]


def test_find_near_duplicate_record_ids_similar_but_not_identical() -> None:
    records = [
        Record(id="a", metadata={"source": "a.pdf", "page": 1, "lang": "en"}),
        Record(id="b", metadata={"source": "a.pdf", "page": 1, "lang": "fr"}),
        Record(id="c", metadata={"source": "z.pdf", "page": 9}),
    ]
    assert find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4) == [["a", "b"]]


def test_find_near_duplicate_record_ids_transitive_grouping() -> None:
    records = [
        Record(id="a", metadata={"x": 1, "y": 1, "z": 1, "w": 1}),
        Record(id="b", metadata={"x": 1, "y": 1, "z": 2, "w": 2}),
        Record(id="c", metadata={"x": 2, "y": 2, "z": 1, "w": 1}),
    ]
    result = find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4)
    assert result == [["a", "b", "c"]]


def test_find_near_duplicate_record_ids_empty_metadata_never_grouped() -> None:
    records = [Record(id="a", metadata={}), Record(id="b", metadata={})]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_empty_input() -> None:
    assert find_near_duplicate_record_ids([], num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_single_record() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    assert find_near_duplicate_record_ids(records, num_hashes=8, num_bands=4) == []


def test_find_near_duplicate_record_ids_invalid_band_count_raises() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    with pytest.raises(ValueError, match="must be evenly divisible"):
        find_near_duplicate_record_ids(records, num_hashes=8, num_bands=3)


def test_find_near_duplicate_record_ids_generator_input() -> None:
    def gen() -> object:
        yield Record(id="a", metadata={"source": "a.pdf"})
        yield Record(id="b", metadata={"source": "a.pdf"})

    result = find_near_duplicate_record_ids(gen(), num_hashes=4, num_bands=4)
    assert result == [["a", "b"]]


def test_find_near_duplicate_record_ids_default_args_do_not_raise() -> None:
    records = [Record(id="a", metadata={"source": "a.pdf"})]
    assert find_near_duplicate_record_ids(records) == []
