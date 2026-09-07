from __future__ import annotations

from persista.record import Record
from persista.record.analysis import find_orphan_references

########################################
#     Tests for find_orphan_references     #
########################################


def test_find_orphan_references_no_orphans() -> None:
    records = [
        Record(id="doc1", metadata={}),
        Record(id="chunk1", metadata={"parent_id": "doc1"}),
    ]
    assert find_orphan_references(records, reference_key="parent_id") == []


def test_find_orphan_references_one_orphan() -> None:
    records = [
        Record(id="doc1", metadata={}),
        Record(id="chunk1", metadata={"parent_id": "missing"}),
    ]
    assert find_orphan_references(records, reference_key="parent_id") == ["chunk1"]


def test_find_orphan_references_multiple_orphans_in_order() -> None:
    records = [
        Record(id="chunk1", metadata={"parent_id": "missing1"}),
        Record(id="chunk2", metadata={"parent_id": "missing2"}),
    ]
    assert find_orphan_references(records, reference_key="parent_id") == [
        "chunk1",
        "chunk2",
    ]


def test_find_orphan_references_missing_key_not_an_orphan() -> None:
    records = [Record(id="a", metadata={})]
    assert find_orphan_references(records, reference_key="parent_id") == []


def test_find_orphan_references_none_value_not_an_orphan() -> None:
    records = [Record(id="a", metadata={"parent_id": None})]
    assert find_orphan_references(records, reference_key="parent_id") == []


def test_find_orphan_references_empty_input() -> None:
    assert find_orphan_references([], reference_key="parent_id") == []


def test_find_orphan_references_self_reference_not_orphan() -> None:
    records = [Record(id="a", metadata={"parent_id": "a"})]
    assert find_orphan_references(records, reference_key="parent_id") == []
