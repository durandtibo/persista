from __future__ import annotations

import pytest

from persista.record import Record, sort_by_metadata


@pytest.fixture
def records() -> list[Record]:
    return [
        Record(id="b", metadata={"source": "b.txt", "category": "Science"}),
        Record(id="a", metadata={"source": "a.txt", "category": "Cooking"}),
        Record(id="c", metadata={"source": "c.txt", "category": "Technology"}),
    ]


##########################################
#     Tests for sort_by_metadata         #
##########################################


# --- Return type and non-mutation ---


def test_sort_by_metadata_returns_list(records: list[Record]) -> None:
    assert isinstance(sort_by_metadata(records, "source"), list)


def test_sort_by_metadata_does_not_mutate_input(records: list[Record]) -> None:
    original_order = [r.id for r in records]
    sort_by_metadata(records, "source")
    assert [r.id for r in records] == original_order


def test_sort_by_metadata_returns_new_list(records: list[Record]) -> None:
    assert sort_by_metadata(records, "source") is not records


# --- Sorting ---


def test_sort_by_metadata_ascending(records: list[Record]) -> None:
    result = sort_by_metadata(records, "source")
    assert [r.metadata["source"] for r in result] == ["a.txt", "b.txt", "c.txt"]


def test_sort_by_metadata_reverse(records: list[Record]) -> None:
    result = sort_by_metadata(records, "source", reverse=True)
    assert [r.metadata["source"] for r in result] == ["c.txt", "b.txt", "a.txt"]


def test_sort_by_metadata_already_sorted() -> None:
    records = [
        Record(id="a", metadata={"source": "a.txt"}),
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="c", metadata={"source": "c.txt"}),
    ]
    result = sort_by_metadata(records, "source")
    assert [r.metadata["source"] for r in result] == ["a.txt", "b.txt", "c.txt"]


def test_sort_by_metadata_integer_values() -> None:
    records = [
        Record(id="c", metadata={"page": 3}),
        Record(id="a", metadata={"page": 1}),
        Record(id="b", metadata={"page": 2}),
    ]
    result = sort_by_metadata(records, "page")
    assert [r.metadata["page"] for r in result] == [1, 2, 3]


# --- Missing keys ---


def test_sort_by_metadata_missing_key_placed_last_by_default() -> None:
    records = [
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="x"),
        Record(id="a", metadata={"source": "a.txt"}),
    ]
    result = sort_by_metadata(records, "source")
    assert result[-1].id == "x"
    assert [r.metadata.get("source") for r in result] == ["a.txt", "b.txt", None]


def test_sort_by_metadata_keep_missing_true() -> None:
    records = [
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="x"),
        Record(id="a", metadata={"source": "a.txt"}),
    ]
    result = sort_by_metadata(records, "source", keep_missing=True)
    assert len(result) == 3


def test_sort_by_metadata_keep_missing_false() -> None:
    records = [
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="x"),
        Record(id="a", metadata={"source": "a.txt"}),
    ]
    result = sort_by_metadata(records, "source", keep_missing=False)
    assert len(result) == 2
    assert all("source" in r.metadata for r in result)


def test_sort_by_metadata_keep_missing_false_preserves_order() -> None:
    records = [
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="x"),
        Record(id="a", metadata={"source": "a.txt"}),
    ]
    result = sort_by_metadata(records, "source", keep_missing=False)
    assert [r.metadata["source"] for r in result] == ["a.txt", "b.txt"]


def test_sort_by_metadata_all_missing_keep_true() -> None:
    records = [Record(id="a"), Record(id="b")]
    assert len(sort_by_metadata(records, "source")) == 2


def test_sort_by_metadata_all_missing_keep_false() -> None:
    records = [Record(id="a"), Record(id="b")]
    assert sort_by_metadata(records, "source", keep_missing=False) == []


# --- Edge cases ---


def test_sort_by_metadata_empty_list() -> None:
    assert sort_by_metadata([], "source") == []


def test_sort_by_metadata_single_record() -> None:
    records = [Record(id="a", metadata={"source": "a.txt"})]
    assert sort_by_metadata(records, "source") == records


def test_sort_by_metadata_reverse_missing_still_last() -> None:
    records = [
        Record(id="b", metadata={"source": "b.txt"}),
        Record(id="x"),
        Record(id="a", metadata={"source": "a.txt"}),
    ]
    result = sort_by_metadata(records, "source", reverse=True)
    assert result[-1].id == "x"
